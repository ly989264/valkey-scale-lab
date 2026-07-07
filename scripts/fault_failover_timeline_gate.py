#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from valkey_scale_lab import __version__  # noqa: E402
from valkey_scale_lab.config.validation import load_effective_config  # noqa: E402
from valkey_scale_lab.observer.failover_timeline import (  # noqa: E402
    ClientRecoveryAccumulator,
    FailoverTimelineObserver,
    ObserverEndpoint,
    build_rto_summary,
    derive_rto_metrics,
    monotonic_ms,
    moved_target,
    unix_ms,
)
from valkey_scale_lab.planner.plan import create_plan_file  # noqa: E402
from valkey_probe_lib import RespConnection, RespError, endpoints_from_state, load_state, wait_for_cluster_ok  # noqa: E402
from fault_failover_gate import (  # noqa: E402
    find_primary_with_replica,
    project_cleanup,
    run_cmd,
    wait_for_stable_cluster_ok,
    workload_target_for_logical,
)

PHASE = "P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY"
REQUIRED_REAL_SCALES = [30, 50, 100, 200]
SMOKE_SCALE = 10


def find_p44_primary_with_replica(probes: list[dict[str, Any]], state_nodes: list[dict[str, Any]]) -> tuple[str, str, str] | None:
    logical_to_id = {
        str(probe["logical_id"]): str(probe["myself_node_id"])
        for probe in probes
        if probe.get("status") == "PASS" and probe.get("logical_id") and probe.get("myself_node_id")
    }
    id_to_logical = {node_id: logical for logical, node_id in logical_to_id.items()}
    merged_nodes: dict[str, dict[str, Any]] = {}
    for probe in probes:
        if probe.get("status") == "PASS":
            merged_nodes.update(probe.get("cluster_nodes") or {})
    candidates: list[tuple[str, str, str]] = []
    for node_id, node in merged_nodes.items():
        if node.get("role") != "primary" or node_id not in id_to_logical:
            continue
        replicas = []
        for replica_id, replica in merged_nodes.items():
            flags = set(replica.get("flags") or [])
            if replica.get("master_id") == node_id and replica.get("link_state") == "connected" and not flags.intersection({"fail", "fail?", "pfail"}):
                replicas.append(replica_id)
        if replicas:
            candidates.append((id_to_logical[node_id], node_id, sorted(replicas)[0]))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        return candidates[len(candidates) // 2]
    return find_primary_with_replica(probes, state_nodes)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_from_ms(value: Any) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000.0, timezone.utc).isoformat().replace("+00:00", "Z")
    return utc_now()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="P44 real failover RTO timeline observer gate")
    parser.add_argument("--phase", default=PHASE)
    parser.add_argument("--artifact-dir", default=f"artifacts/phases/{PHASE}")
    parser.add_argument("--scales", default="10,30,50,100,200")
    parser.add_argument("--samples-per-scale", type=int, default=1)
    parser.add_argument("--probe-interval-ms", type=int)
    parser.add_argument("--client-probe-interval-ms", type=int)
    parser.add_argument("--probe-timeout-ms", type=int)
    parser.add_argument("--max-observer-endpoints", type=int)
    parser.add_argument("--wait-after-fault", type=float, default=180.0)
    parser.add_argument("--require-data-path", action="store_true")
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir)
    if not artifact_dir.is_absolute():
        artifact_dir = ROOT / artifact_dir
    artifact_dir.mkdir(parents=True, exist_ok=True)
    scales = [int(item) for item in args.scales.split(",") if item]
    required = [scale for scale in REQUIRED_REAL_SCALES if scale in scales]
    errors: list[str] = []
    samples: list[dict[str, Any]] = []
    observer_rows: list[dict[str, Any]] = []
    client_rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    cleanup_reports: list[dict[str, Any]] = []

    for scale in scales:
        ok, preflight_path, reason = run_resource_preflight(args.phase, scale, artifact_dir)
        if not ok:
            errors.append(f"resource preflight failed for scale {scale}: {reason}; see {rel(preflight_path)}")
            continue
        for index in range(1, args.samples_per_scale + 1):
            result = run_single_sample(args, artifact_dir, scale, index)
            samples.append(result["timeline_sample"])
            observer_rows.extend(result["observer_samples"])
            client_rows.extend(result["client_samples"])
            events.extend(result["events"])
            metrics.extend(result["metrics"])
            cleanup_reports.append(result["cleanup_report"])
            if result["timeline_sample"].get("status") != "PASS":
                errors.extend(result["errors"])

    write_jsonl(artifact_dir / "failover_timeline_samples.jsonl", samples)
    write_jsonl(artifact_dir / "observer_samples.jsonl", observer_rows)
    write_jsonl(artifact_dir / "client_recovery_samples.jsonl", client_rows)
    write_jsonl(artifact_dir / "events.jsonl", events)
    write_jsonl(artifact_dir / "metrics_timeseries.jsonl", metrics)
    write_common_artifacts(args.phase, artifact_dir, samples, client_rows, cleanup_reports, errors)
    write_gt_200_projection(args.phase, artifact_dir, errors)

    observed = {sample.get("node_count") for sample in samples if sample.get("status") == "PASS" and sample.get("real_valkey") is True}
    missing = sorted(set(required) - observed)
    if missing:
        errors.append(f"missing required real P44 scales {missing}")
    if errors:
        write_blocked(args.phase, errors)
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    clear_blocked(args.phase)
    print(f"PASS P44 failover timeline artifacts at {artifact_dir}")
    return 0


def config_for_scale(scale: int) -> Path:
    return ROOT / "templates" / "configs" / f"scale_{scale}.yaml"


def run_resource_preflight(phase: str, scale: int, artifact_dir: Path) -> tuple[bool, Path, str]:
    out = artifact_dir / f"resource_preflight_{scale}.json"
    proc = run_cmd(
        [
            sys.executable,
            "-m",
            "valkey_scale_lab.cli",
            "resource",
            "preflight",
            "--config",
            str(config_for_scale(scale)),
            "--out",
            str(out),
            "--phase",
            phase,
            "--scenario",
            f"p44_scale_{scale}_timeline_sample_01",
        ],
        timeout=240,
    )
    report = load_json_if_exists(out)
    ok = proc.returncode == 0 and report.get("can_run") is True and int(report.get("node_count", 0) or 0) == scale
    report.update(
        {
            "schema_version": "v1",
            "artifact_type": "resource_preflight",
            "phase_id": phase,
            "status": "PASS" if ok else "FAIL",
            "node_count": scale,
            "p44_exact_scale_required": True,
            "dry_run": False,
        }
    )
    write_json(out, report)
    reason = "" if ok else (proc.stderr[-1000:] or f"can_run={report.get('can_run')} node_count={report.get('node_count')}")
    return ok, out, reason


def run_single_sample(args: argparse.Namespace, artifact_dir: Path, scale: int, index: int) -> dict[str, Any]:
    sample_id = f"scale-{scale}-timeline-sample-{index:02d}"
    scenario = f"p44_scale_{scale}_timeline_sample_{index:02d}"
    sample_dir = artifact_dir / "_p44_samples" / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    state_path = sample_dir / "state_failover.json"
    run_id = f"{args.phase}-{sample_id}-real"
    errors: list[str] = []
    observer_samples: list[dict[str, Any]] = []
    client_samples: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    cleanup_report: dict[str, Any] = {"status": "MISSING", "resources_remaining": [{"reason": "cleanup did not run"}]}
    timeline_sample = _missing_timeline_sample(args.phase, run_id, scenario, sample_id, scale)
    state: dict[str, Any] = {}

    try:
        setup = run_cmd(
            [
                sys.executable,
                "-m",
                "valkey_scale_lab.cli",
                "gate",
                "scenario",
                "--phase",
                args.phase,
                "--scenario",
                scenario,
                "--config",
                str(config_for_scale(scale)),
                "--artifacts-dir",
                str(sample_dir),
                "--state-out",
                str(state_path),
            ],
            timeout=max(900, scale * 12),
        )
        (sample_dir / "setup.stdout.log").write_text(setup.stdout, encoding="utf-8", errors="replace")
        (sample_dir / "setup.stderr.log").write_text(setup.stderr, encoding="utf-8", errors="replace")
        if setup.returncode != 0:
            raise RuntimeError(f"setup failed exit={setup.returncode}")
        state = load_state(state_path)
        runtime_config = state.get("runtime", {}) if isinstance(state.get("runtime"), dict) else {}
        server_profile_value = runtime_config.get("server_profile", "MISSING")
        if isinstance(server_profile_value, dict):
            server_profile_value = (
                server_profile_value.get("profile_name")
                or server_profile_value.get("server_profile")
                or server_profile_value.get("source_profile")
                or "configured"
            )
        effective_config = load_effective_config(config_for_scale(scale))
        observer_config = effective_config.get("observability", {}).get("failover_timeline_observer", {})
        probe_interval_ms = int(args.probe_interval_ms or observer_config.get("probe_interval_ms", 250))
        client_probe_interval_ms = int(args.client_probe_interval_ms or observer_config.get("client_probe_interval_ms", 250))
        probe_timeout_ms = int(args.probe_timeout_ms or observer_config.get("probe_timeout_ms", 1000))
        max_observer_endpoints = int(args.max_observer_endpoints or observer_config.get("max_observer_endpoints", 32))
        endpoints = endpoints_from_state(state)
        observer_endpoints = [ObserverEndpoint.from_node(node) for node in state.get("nodes", [])]
        ok, before = wait_for_stable_cluster_ok(endpoints, scale, timeout_seconds=max(180, scale * 2), interval=1)
        if not ok:
            raise RuntimeError("cluster not OK before P44 failover")
        selection = find_p44_primary_with_replica(before, state.get("nodes", []))
        if not selection:
            raise RuntimeError("no primary with replica available for P44 failover")
        selected_logical, old_primary_id, expected_replica_id = selection
        valkey_versions = sorted({str(probe.get("version")) for probe in before if probe.get("status") == "PASS" and probe.get("version")})
        if not valkey_versions or any(not version.startswith("9.1.") for version in valkey_versions):
            raise RuntimeError(f"P44 requires Valkey 9.1.x evidence, observed={valkey_versions}")
        workload_target = workload_target_for_logical(endpoints, before, selected_logical)
        if not workload_target:
            raise RuntimeError("no failed-primary slot workload target")
        observer = FailoverTimelineObserver(
            phase_id=args.phase,
            run_id=run_id,
            scenario_name=scenario,
            sample_id=sample_id,
            node_count=scale,
            endpoints=observer_endpoints,
            target_primary_logical_id=selected_logical,
            target_primary_node_id=old_primary_id,
            expected_replica_node_id=expected_replica_id,
            probe_interval_ms=probe_interval_ms,
            timeout_seconds=probe_timeout_ms / 1000.0,
            max_observer_endpoints=max_observer_endpoints,
        )
        fault_spec = {
            "fault_id": f"p44-primary-stop-{sample_id}",
            "type": "node_stop",
            "scope": "owned_container_or_process",
            "forbid_host_network_mutation": True,
            "target_logical_id": selected_logical,
        }
        fault_spec_path = sample_dir / "fault_primary_stop_spec.json"
        write_json(fault_spec_path, fault_spec)
        fault_apply_at_ms = unix_ms()
        observer.markers.clear()
        observer.start()
        apply = run_cmd(
            [
                sys.executable,
                "-m",
                "valkey_scale_lab.cli",
                "fault",
                "apply",
                "--state",
                str(state_path),
                "--target-logical-id",
                selected_logical,
                "--fault-json",
                str(fault_spec_path),
                "--out",
                str(sample_dir / "fault_apply.json"),
            ],
            timeout=180,
        )
        (sample_dir / "fault_apply.stdout.log").write_text(apply.stdout, encoding="utf-8", errors="replace")
        (sample_dir / "fault_apply.stderr.log").write_text(apply.stderr, encoding="utf-8", errors="replace")
        if apply.returncode != 0:
            errors.append(f"fault apply failed exit={apply.returncode}")
        accumulator = ClientRecoveryAccumulator(sample_id, fault_apply_at_ms, client_probe_interval_ms)
        deadline = time.monotonic() + args.wait_after_fault
        first_client_success_at_ms: int | None = None
        while time.monotonic() < deadline:
            client_row = run_client_probe(args.phase, run_id, scenario, sample_id, endpoints, workload_target, fault_apply_at_ms)
            accumulator.record(client_row)
            client_samples.append(client_row)
            summary = accumulator.summary()
            markers = dict(observer.markers)
            cluster_ok_at_ms = markers.get("first_cluster_ok_at_ms")
            if isinstance(cluster_ok_at_ms, int):
                first_client_success_at_ms = accumulator.first_success_at_or_after(cluster_ok_at_ms)
            if cluster_ok_at_ms and first_client_success_at_ms:
                break
            time.sleep(client_probe_interval_ms / 1000.0)
        clear = run_cmd(
            [
                sys.executable,
                "-m",
                "valkey_scale_lab.cli",
                "fault",
                "clear",
                "--state",
                str(state_path),
                "--fault-id",
                fault_spec["fault_id"],
                "--out",
                str(sample_dir / "fault_clear.json"),
            ],
            timeout=180,
        )
        (sample_dir / "fault_clear.stdout.log").write_text(clear.stdout, encoding="utf-8", errors="replace")
        (sample_dir / "fault_clear.stderr.log").write_text(clear.stderr, encoding="utf-8", errors="replace")
        clean_ok, _clean_probes = wait_for_stable_cluster_ok(endpoints, scale, timeout_seconds=max(180, scale * 2), interval=2)
        clean_snapshot_passed_at_ms = unix_ms() if clean_ok else "MISSING"
        observer.stop()
        observer_samples = list(observer.samples)
        client_summary = accumulator.summary()
        row = {
            "schema_version": "v1",
            "phase_id": args.phase,
            "run_id": run_id,
            "scenario_name": scenario,
            "sample_id": sample_id,
            "status": "PENDING",
            "execution_mode": "real_valkey",
            "real_valkey": True,
            "node_count": scale,
            "scale": str(scale),
            "target_primary_logical_id": selected_logical,
            "target_primary_node_id": old_primary_id,
            "expected_replica_node_id": expected_replica_id,
            "valkey_versions": valkey_versions,
            "timeout_config_ms": int(runtime_config.get("effective_cluster_node_timeout_ms", 30000) or 30000),
            "server_profile": str(server_profile_value),
            "nodehost_strategy": str(runtime_config.get("nodehost_strategy", runtime_config.get("nodehost_density", {}).get("nodehost_strategy", "MISSING"))),
            "evidence_probes": [
                {
                    "logical_id": probe.get("logical_id", "MISSING"),
                    "host": probe.get("host", "MISSING"),
                    "port": probe.get("port", 0),
                    "status": probe.get("status", "FAIL"),
                    "version": probe.get("version", "MISSING"),
                    "cluster_state": probe.get("cluster_state", "unknown"),
                }
                for probe in before
                if probe.get("status") == "PASS"
            ][: min(scale, 16)],
            "fault_apply_at_ms": fault_apply_at_ms,
            "target_process_gone_at_ms": observer.markers.get("target_process_gone_at_ms", "MISSING"),
            "first_pfail_seen_at_ms": observer.markers.get("first_pfail_seen_at_ms", "MISSING"),
            "first_fail_seen_at_ms": observer.markers.get("first_fail_seen_at_ms", "MISSING"),
            "first_promotion_seen_at_ms": observer.markers.get("first_promotion_seen_at_ms", "MISSING"),
            "first_slots_covered_at_ms": observer.markers.get("first_slots_covered_at_ms", "MISSING"),
            "first_cluster_ok_at_ms": observer.markers.get("first_cluster_ok_at_ms", "MISSING"),
            "first_client_success_at_ms": first_client_success_at_ms if first_client_success_at_ms else "MISSING",
            "clean_snapshot_passed_at_ms": clean_snapshot_passed_at_ms,
            "timeline_source": "concurrent_failover_timeline_observer",
            "client_probe_source": "continuous_fault_period_set_get",
            "first_client_success_source": "client_recovery_samples.jsonl",
            "observer_samples_ref": f"observer_samples.jsonl#{sample_id}",
            "client_recovery_samples_ref": f"client_recovery_samples.jsonl#{sample_id}",
            "client_probe_interval_ms": client_summary["client_probe_interval_ms"],
            "observer_config": observer_config,
            "first_success_after_fault_ms": client_summary["first_success_after_fault_ms"],
            "error_count_before_recovery": client_summary["error_count_before_recovery"],
            "timeout_count_before_recovery": client_summary["timeout_count_before_recovery"],
            "moved_count": client_summary["moved_count"],
            "ask_count": client_summary["ask_count"],
            "clean_snapshot_endpoint": "separate_clean_gate_after_cluster_ok",
            "state_ref": rel(state_path),
            "cleanup_ref": rel(sample_dir / "cleanup_report.json"),
        }
        try:
            row.update(derive_rto_metrics(row))
            row["status"] = "PASS"
        except Exception as exc:  # noqa: BLE001
            for metric_name in [
                "kill_to_pfail_ms",
                "pfail_to_cluster_ok_ms",
                "kill_to_client_recovered_ms",
                "cluster_ok_to_client_success_ms",
                "cluster_ok_to_clean_snapshot_ms",
                "kill_to_clean_snapshot_ms",
            ]:
                row.setdefault(metric_name, "MISSING")
            row["status"] = "FAIL"
            errors.append(f"{sample_id} timeline derivation failed: {exc}")
        timeline_sample = row
        events = event_rows(row)
        metrics = metric_rows(row)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{sample_id}: {exc}")
    finally:
        if "observer" in locals():
            observer.stop()
        if state_path.exists():
            cleanup_status, cleanup_path = project_cleanup(args.phase, state_path, sample_dir, sample_dir / "cleanup_report.json")
            cleanup_report = load_json_if_exists(cleanup_path)
            if cleanup_status != "PASS":
                errors.append(f"{sample_id}: cleanup failed")
        if args.require_data_path and timeline_sample.get("first_client_success_at_ms") == "MISSING":
            errors.append(f"{sample_id}: required continuous client data-path recovery missing")
    if errors and timeline_sample.get("status") == "PASS":
        timeline_sample["status"] = "FAIL"
    return {
        "timeline_sample": timeline_sample,
        "observer_samples": observer_samples,
        "client_samples": client_samples,
        "events": events,
        "metrics": metrics,
        "cleanup_report": cleanup_report,
        "errors": errors,
    }


def run_client_probe(
    phase: str,
    run_id: str,
    scenario: str,
    sample_id: str,
    endpoints: list[Any],
    target: dict[str, Any],
    fault_apply_at_ms: int,
) -> dict[str, Any]:
    ts = unix_ms()
    key = f"{target['slot_key']}:p44:{sample_id}:{ts}"
    value = f"value-{ts}"
    status = "FAIL"
    set_status = "FAIL"
    get_status = "FAIL"
    moved = 0
    ask = 0
    timeout = False
    error = ""
    start = time.monotonic()
    try:
        set_reply, moved_set, ask_set = execute_redirecting(endpoints, "SET", key, value)
        moved += moved_set
        ask += ask_set
        set_status = "PASS" if str(set_reply) == "OK" else "FAIL"
        get_reply, moved_get, ask_get = execute_redirecting(endpoints, "GET", key)
        moved += moved_get
        ask += ask_get
        get_status = "PASS" if str(get_reply) == value else "FAIL"
        status = "PASS" if set_status == "PASS" and get_status == "PASS" else "FAIL"
    except Exception as exc:  # noqa: BLE001
        error = repr(exc)[:200]
        timeout = "timeout" in error.lower() or "timed out" in error.lower()
    return {
        "schema_version": "v1",
        "phase_id": phase,
        "run_id": run_id,
        "scenario_name": scenario,
        "sample_id": sample_id,
        "timestamp_unix_ms": ts,
        "monotonic_ms": monotonic_ms(),
        "status": status,
        "probe_type": "continuous_fault_period_set_get",
        "fault_active": ts >= fault_apply_at_ms,
        "key": key,
        "set_status": set_status,
        "get_status": get_status,
        "latency_ms": round((time.monotonic() - start) * 1000, 3),
        "moved_count": moved,
        "ask_count": ask,
        "timeout": timeout,
        "error": error,
    }


def execute_redirecting(endpoints: list[Any], *command: Any) -> tuple[Any, int, int]:
    endpoint = endpoints[0]
    moved = 0
    ask = 0
    for _ in range(10):
        try:
            return RespConnection(endpoint.host, endpoint.port, endpoint.password, timeout=2.0).execute(*command), moved, ask
        except RespError as exc:
            target = moved_target(exc.message)
            if not target:
                raise
            if exc.message.startswith("MOVED"):
                moved += 1
            if exc.message.startswith("ASK"):
                ask += 1
            endpoint = redirect_endpoint(endpoints, target[0], target[1], endpoint.password)
            if exc.message.startswith("ASK"):
                RespConnection(endpoint.host, endpoint.port, endpoint.password, timeout=2.0).execute("ASKING")
    raise RuntimeError("too many redirects")


def redirect_endpoint(endpoints: list[Any], host: str, port: int, password: str | None) -> Any:
    for endpoint in endpoints:
        if endpoint.host == host and endpoint.port == port:
            return endpoint
        if getattr(endpoint, "container_ip", None) == host and endpoint.port == port:
            return endpoint
        if getattr(endpoint, "container_ip", None) == host and port == 6379:
            return endpoint
    return type(endpoints[0])(logical_id=f"redirect-{host}:{port}", host=host, port=port, password=password)


def event_rows(sample: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for event_type, field in [
        ("fault_apply", "fault_apply_at_ms"),
        ("target_process_gone", "target_process_gone_at_ms"),
        ("first_pfail_seen", "first_pfail_seen_at_ms"),
        ("first_fail_seen", "first_fail_seen_at_ms"),
        ("first_promotion_seen", "first_promotion_seen_at_ms"),
        ("first_slots_covered", "first_slots_covered_at_ms"),
        ("first_cluster_ok", "first_cluster_ok_at_ms"),
        ("first_client_success", "first_client_success_at_ms"),
        ("clean_snapshot_passed", "clean_snapshot_passed_at_ms"),
    ]:
        timestamp = sample.get(field, "MISSING")
        rows.append(
            {
                "schema_version": "v1",
                "artifact_type": "event",
                "run_id": sample["run_id"],
                "phase_id": sample["phase_id"],
                "timestamp": iso_from_ms(timestamp),
                "scenario_name": sample["scenario_name"],
                "sample_id": sample["sample_id"],
                "event_id": f"{sample['sample_id']}-{event_type}",
                "event_type": event_type,
                "timestamp_unix_ms": timestamp,
                "monotonic_ms": timestamp if isinstance(timestamp, (int, float)) else "MISSING",
                "severity": "info" if sample.get("status") == "PASS" else "error",
                "subject_type": "failover_timeline",
                "subject_id": sample.get("target_primary_logical_id", "MISSING"),
                "operation_id": "",
                "fault_id": f"p44-primary-stop-{sample['sample_id']}",
                "message": f"P44 {event_type} for {sample['sample_id']}",
                "metadata": {"node_count": sample.get("node_count"), "field": field},
            }
        )
    return rows


def metric_rows(sample: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for metric in [
        "kill_to_pfail_ms",
        "pfail_to_cluster_ok_ms",
        "kill_to_client_recovered_ms",
        "cluster_ok_to_client_success_ms",
        "cluster_ok_to_clean_snapshot_ms",
        "kill_to_clean_snapshot_ms",
    ]:
        value = sample.get(metric, "MISSING")
        rows.append(
            {
                "schema_version": "v1",
                "artifact_type": "metric_sample",
                "run_id": sample["run_id"],
                "phase_id": sample["phase_id"],
                "timestamp": iso_from_ms(sample.get("clean_snapshot_passed_at_ms", "MISSING")),
                "source": "p44_failover_timeline",
                "metrics": {metric: value},
                "scenario_name": sample["scenario_name"],
                "sample_id": sample["sample_id"],
                "timestamp_unix_ms": sample.get("clean_snapshot_passed_at_ms", "MISSING"),
                "monotonic_ms": sample.get("clean_snapshot_passed_at_ms", "MISSING"),
                "source_type": "harness",
                "source_id": sample["sample_id"],
                "metric_name": metric,
                "metric_value": value,
                "metric_unit": "ms",
                "labels": {"node_count": sample.get("node_count"), "scale": sample.get("scale")},
                "missing_reason": "" if isinstance(value, (int, float)) else f"{metric} not observed by P44 timeline",
            }
        )
    return rows


def write_common_artifacts(
    phase: str,
    base: Path,
    samples: list[dict[str, Any]],
    client_rows: list[dict[str, Any]],
    cleanup_reports: list[dict[str, Any]],
    errors: list[str],
) -> None:
    status = "PASS" if not errors and samples and all(sample.get("status") == "PASS" for sample in samples) else "FAIL"
    refs = [rel(base / name) for name in ["failover_timeline_samples.jsonl", "observer_samples.jsonl", "client_recovery_samples.jsonl", "failover_rto_summary.json"]]
    pass_samples = [sample for sample in samples if sample.get("status") == "PASS"]
    first_sample = pass_samples[0] if pass_samples else {}
    summary = build_rto_summary(
        samples,
        phase_id=phase,
        run_id=f"{phase}-summary",
        timeout_config_ms=int(first_sample.get("timeout_config_ms", 30000) or 30000),
        server_profile=str(first_sample.get("server_profile", "MISSING")),
        nodehost_strategy=str(first_sample.get("nodehost_strategy", "MISSING")),
        scale="10,30,50,100,200",
    )
    summary["status"] = status
    write_json(base / "failover_rto_summary.json", summary)
    write_json(
        base / "phase_summary.json",
        base_artifact(
            phase,
            "phase_summary",
            status,
            summary="P44 failover RTO timeline observability",
            required_artifacts=refs,
            missing_metrics=[] if status == "PASS" else [{"metric": "p44_real_timeline_coverage", "status": "MISSING", "reason": "; ".join(errors)[:500]}],
            risks=[],
        ),
    )
    write_json(
        base / "quant_summary.json",
        base_artifact(
            phase,
            "quant_summary",
            status,
            summary="P44 RTO metrics derived only from failover_timeline_samples.jsonl.",
            artifact_refs=refs,
            source_artifacts=refs,
            missing_data=[] if status == "PASS" else [{"field": "p44_real_timeline_coverage", "status": "MISSING", "reason": "; ".join(errors)[:500]}],
            runtime_claims={"real_valkey_claimed": status == "PASS", "management_runtime_claimed": False, "fault_runtime_claimed": True},
        ),
    )
    write_json(base / "analysis_summary.json", base_artifact(phase, "analysis_summary", status, source_artifacts=refs, findings=[], missing_metrics=[] if status == "PASS" else [{"metric": "p44_real_timeline_coverage", "status": "MISSING", "reason": "; ".join(errors)[:500]}]))
    write_json(base / "report_index.json", base_artifact(phase, "report_index", status, source_artifacts=refs, reports=[]))
    write_json(base / "cleanup_report.json", merge_cleanup_reports(phase, cleanup_reports))
    write_json(base / "workload_windows.json", workload_windows_artifact(phase, samples, client_rows, status))
    write_json(base / "valkey_e2e_evidence.json", evidence_artifact(phase, samples, status, errors))


def write_gt_200_projection(phase: str, base: Path, errors: list[str]) -> None:
    try:
        projection = create_plan_file(ROOT / "templates/configs/scale_1000_dryrun_optin.yaml", base / "dry_run_gt_200_projection.json", dry_run=True)
        projection.update(
            {
                "phase_id": phase,
                "stage_id": phase,
                "dry_run": True,
                "real_valkey": False,
                "runtime_resources_created": False,
                "projection_only_reason": "Greater-than-200 P44 coverage is dry-run projection only.",
            }
        )
        write_json(base / "dry_run_gt_200_projection.json", projection)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"greater-than-200 dry-run projection failed: {exc}")


def evidence_artifact(phase: str, samples: list[dict[str, Any]], status: str, errors: list[str]) -> dict[str, Any]:
    scales = sorted({sample.get("node_count") for sample in samples if sample.get("status") == "PASS" and sample.get("real_valkey") is True})
    versions = sorted({version for sample in samples for version in sample.get("valkey_versions", []) if version})
    probes = [probe for sample in samples for probe in sample.get("evidence_probes", []) if probe.get("status") == "PASS"]
    return base_artifact(
        phase,
        "valkey_e2e_evidence",
        status,
        scenario="p44_failover_timeline",
        real_valkey=True,
        valkey_version_prefix_required="9.1.",
        probe_result="PASS" if status == "PASS" else "FAIL",
        nodes_observed=max([int(scale) for scale in scales if isinstance(scale, int)] or [0]),
        valkey_versions=versions,
        sample_refs=[sample.get("sample_id") for sample in samples],
        observed_real_scales=scales,
        errors=errors,
        cluster_state_observed="ok" if status == "PASS" else "unknown",
        data_path_result="PASS" if status == "PASS" else "FAIL",
        probes=probes or [{"logical_id": "MISSING", "host": "MISSING", "port": 0, "status": "FAIL", "error": "no passing samples"}],
        cleanup={"status": "PASS" if status == "PASS" else "FAIL", "path": "cleanup_report.json"},
    )


def workload_windows_artifact(
    phase: str,
    samples: list[dict[str, Any]],
    client_rows: list[dict[str, Any]],
    status: str,
) -> dict[str, Any]:
    rows_by_sample: dict[str, list[dict[str, Any]]] = {}
    for row in client_rows:
        rows_by_sample.setdefault(str(row.get("sample_id", "MISSING")), []).append(row)
    windows = []
    for sample in samples:
        sample_id = str(sample.get("sample_id", "MISSING"))
        sample_rows = rows_by_sample.get(sample_id, [])
        bounds = [
            ("baseline", "baseline_start", "baseline_end", "MISSING", "MISSING"),
            ("pre_event", "pre_event_start", "fault_apply", "MISSING", sample.get("fault_apply_at_ms", "MISSING")),
            ("event", "fault_apply", "first_cluster_ok", sample.get("fault_apply_at_ms", "MISSING"), sample.get("first_cluster_ok_at_ms", "MISSING")),
            ("recovery", "first_cluster_ok", "first_client_success", sample.get("first_cluster_ok_at_ms", "MISSING"), sample.get("first_client_success_at_ms", "MISSING")),
            ("post_recovery", "first_client_success", "clean_snapshot_passed", sample.get("first_client_success_at_ms", "MISSING"), sample.get("clean_snapshot_passed_at_ms", "MISSING")),
            ("all_run", "fault_apply", "clean_snapshot_passed", sample.get("fault_apply_at_ms", "MISSING"), sample.get("clean_snapshot_passed_at_ms", "MISSING")),
        ]
        for name, start_event, end_event, start_ms, end_ms in bounds:
            window_rows = _client_rows_in_window(sample_rows, start_ms, end_ms)
            windows.append(
                {
                    "window_name": name,
                    "sample_id": sample_id,
                    "start_event_id": f"{sample_id}-{start_event}",
                    "end_event_id": f"{sample_id}-{end_event}",
                    "start_time_unix_ms": start_ms,
                    "end_time_unix_ms": end_ms,
                    "metrics": _client_window_metrics(sample, window_rows, start_ms, end_ms),
                }
            )
    return base_artifact(phase, "workload_windows", status, windows=windows)


def _client_rows_in_window(rows: list[dict[str, Any]], start_ms: Any, end_ms: Any) -> list[dict[str, Any]]:
    if not isinstance(start_ms, (int, float)) or not isinstance(end_ms, (int, float)) or end_ms < start_ms:
        return []
    return [
        row
        for row in rows
        if isinstance(row.get("timestamp_unix_ms"), int) and start_ms <= row["timestamp_unix_ms"] <= end_ms
    ]


def _percentile_or_missing(values: list[float], pct: float, missing_reasons: dict[str, str], field: str) -> float | str:
    if not values:
        missing_reasons[field] = "No client probe latency samples fell inside this workload window."
        return "MISSING"
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return round(ordered[index], 3)


def _client_window_metrics(sample: dict[str, Any], rows: list[dict[str, Any]], start_ms: Any, end_ms: Any) -> dict[str, Any]:
    missing_reasons: dict[str, str] = {}
    requested_qps = round(1000 / max(float(sample.get("client_probe_interval_ms", 250) or 250), 1), 3)
    sample_count = len(rows)
    ok_ops = sum(1 for row in rows if row.get("status") == "PASS")
    error_ops = sample_count - ok_ops
    duration_seconds = ((float(end_ms) - float(start_ms)) / 1000.0) if isinstance(start_ms, (int, float)) and isinstance(end_ms, (int, float)) and end_ms > start_ms else 0.0
    if not rows:
        missing_reasons["window_samples"] = "No continuous client probe samples fell inside this window."
    latencies = [
        float(row["latency_ms"])
        for row in rows
        if isinstance(row.get("latency_ms"), (int, float))
    ]
    error_text = "\n".join(str(row.get("error", "")) for row in rows if row.get("status") != "PASS").lower()
    timeout_count = sum(1 for row in rows if row.get("timeout") is True)
    cluster_down_error_count = error_text.count("clusterdown")
    readonly_error_count = error_text.count("readonly")
    tryagain_error_count = error_text.count("tryagain")
    connection_error_count = sum(
        1
        for row in rows
        if row.get("status") != "PASS"
        and any(token in str(row.get("error", "")).lower() for token in ["connection", "refused", "reset", "empty resp"])
    )
    categorized = timeout_count + cluster_down_error_count + readonly_error_count + tryagain_error_count + connection_error_count
    metrics = {
        "requested_qps": requested_qps,
        "achieved_qps": round(ok_ops / duration_seconds, 3) if duration_seconds > 0 else "MISSING",
        "ok_ops": ok_ops,
        "error_ops": error_ops,
        "error_rate": round(error_ops / sample_count, 6) if sample_count else "MISSING",
        "latency_p50_ms": _percentile_or_missing(latencies, 0.50, missing_reasons, "latency_p50_ms"),
        "latency_p90_ms": _percentile_or_missing(latencies, 0.90, missing_reasons, "latency_p90_ms"),
        "latency_p95_ms": _percentile_or_missing(latencies, 0.95, missing_reasons, "latency_p95_ms"),
        "latency_p99_ms": _percentile_or_missing(latencies, 0.99, missing_reasons, "latency_p99_ms"),
        "latency_p999_ms": _percentile_or_missing(latencies, 0.999, missing_reasons, "latency_p999_ms"),
        "timeout_count": timeout_count,
        "connection_error_count": connection_error_count,
        "moved_redirection_count": sum(int(row.get("moved_count", 0) or 0) for row in rows),
        "ask_redirection_count": sum(int(row.get("ask_count", 0) or 0) for row in rows),
        "cluster_down_error_count": cluster_down_error_count,
        "readonly_error_count": readonly_error_count,
        "tryagain_error_count": tryagain_error_count,
        "unknown_error_count": max(0, error_ops - categorized),
        "sample_count": sample_count,
        "duration_ms": round(duration_seconds * 1000, 3) if duration_seconds > 0 else "MISSING",
        "source": "client_recovery_samples.jsonl",
        "missing_reasons": missing_reasons,
    }
    if metrics["achieved_qps"] == "MISSING":
        missing_reasons["achieved_qps"] = "Window has no positive duration."
    if metrics["error_rate"] == "MISSING":
        missing_reasons["error_rate"] = "Window has no client probe samples."
    return metrics


def merge_cleanup_reports(phase: str, reports: list[dict[str, Any]]) -> dict[str, Any]:
    remaining = []
    actions = []
    for report in reports:
        remaining.extend(report.get("resources_remaining", []) if isinstance(report, dict) else [])
        actions.extend(report.get("cleanup_actions", []) if isinstance(report, dict) else [])
    return base_artifact(
        phase,
        "cleanup_report",
        "PASS" if reports and not remaining and all(report.get("status") == "PASS" for report in reports) else "FAIL",
        resources_remaining=remaining,
        cleanup_actions=actions,
        per_sample_reports=reports,
    )


def base_artifact(phase: str, artifact_type: str, status: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": artifact_type,
        "phase_id": phase,
        "run_id": f"{phase}-{artifact_type}",
        "created_at": utc_now(),
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": status,
        **extra,
    }


def _missing_timeline_sample(phase: str, run_id: str, scenario: str, sample_id: str, scale: int) -> dict[str, Any]:
    row = {
        "schema_version": "v1",
        "phase_id": phase,
        "run_id": run_id,
        "scenario_name": scenario,
        "sample_id": sample_id,
        "status": "FAIL",
        "execution_mode": "real_valkey",
        "real_valkey": True,
        "node_count": scale,
        "scale": str(scale),
        "timeline_source": "concurrent_failover_timeline_observer",
        "client_probe_source": "continuous_fault_period_set_get",
        "first_client_success_source": "client_recovery_samples.jsonl",
        "observer_samples_ref": f"observer_samples.jsonl#{sample_id}",
        "client_recovery_samples_ref": f"client_recovery_samples.jsonl#{sample_id}",
    }
    for field in [
        "fault_apply_at_ms",
        "target_process_gone_at_ms",
        "first_pfail_seen_at_ms",
        "first_fail_seen_at_ms",
        "first_promotion_seen_at_ms",
        "first_slots_covered_at_ms",
        "first_cluster_ok_at_ms",
        "first_client_success_at_ms",
        "clean_snapshot_passed_at_ms",
        "kill_to_pfail_ms",
        "pfail_to_cluster_ok_ms",
        "kill_to_client_recovered_ms",
        "cluster_ok_to_client_success_ms",
        "cluster_ok_to_clean_snapshot_ms",
        "kill_to_clean_snapshot_ms",
    ]:
        row[field] = "MISSING"
    return row


def write_blocked(phase: str, errors: list[str]) -> None:
    path = ROOT / "artifacts" / "goal_loop" / phase / "BLOCKED.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"# BLOCKED - {phase}",
                "",
                "P44 cannot pass without real Valkey failover timeline observer evidence for 30/50/100/200.",
                "",
                "Blocking reasons:",
                *[f"- {error}" for error in errors],
                "",
                "No fake PASS artifacts or greater-than-200 real runtime path were used.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def clear_blocked(phase: str) -> None:
    path = ROOT / "artifacts" / "goal_loop" / phase / "BLOCKED.md"
    if path.exists():
        path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
