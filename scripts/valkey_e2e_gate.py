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
sys.path.insert(0, str(ROOT / "scripts"))
from valkey_probe_lib import endpoints_from_state, execute_cluster_command, load_state, probe_endpoint, wait_for_cluster_ok  # noqa: E402

P13_TIMING_NAMES = [
    "nodehost_start",
    "process_config_prepare",
    "process_start",
    "process_ready_wait",
    "primary_cluster_create",
    "replica_meet",
    "replica_replicate",
    "runtime_representative_probe",
    "runtime_final_full_probe",
    "runtime_diagnostic_full_probe",
    "wrapper_wait_cluster_ok",
    "wrapper_data_path_probe",
    "cleanup",
    "setup_command_wall",
    "setup_stdout_write",
    "setup_stderr_write",
    "state_load",
    "cleanup_command_wall",
    "cleanup_stdout_write",
    "cleanup_stderr_write",
    "artifact_write",
]

P13_ACCOUNTING_NAMES = [
    "setup_command_wall",
    "setup_stdout_write",
    "setup_stderr_write",
    "state_load",
    "wrapper_wait_cluster_ok",
    "wrapper_data_path_probe",
    "cleanup_command_wall",
    "cleanup_stdout_write",
    "cleanup_stderr_write",
    "artifact_write",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_cmd(cmd: list[str], timeout: int, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}" + merged.get("PYTHONPATH", "")
    if env:
        merged.update(env)
    return subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=merged)


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def write_text_timed(
    path: Path,
    text: str,
    timings: dict[str, dict[str, Any]],
    name: str,
    *,
    details: dict[str, Any] | None = None,
) -> None:
    started = time.monotonic()
    path.write_text(text, encoding="utf-8", errors="replace")
    record_timing(timings, name, started, details=details or {"path": str(path)})


def role_counts_from_probes(probes: list[dict[str, Any]]) -> dict[str, int]:
    for probe in probes:
        cluster_nodes = probe.get("cluster_nodes")
        if probe.get("status") != "PASS" or not isinstance(cluster_nodes, dict):
            continue
        counts = {"primary": 0, "replica": 0, "handshake": 0, "fail": 0, "pfail": 0}
        for node in cluster_nodes.values():
            flags = set(node.get("flags") or [])
            if "handshake" in flags:
                counts["handshake"] += 1
            if "fail" in flags:
                counts["fail"] += 1
            if "fail?" in flags or "pfail" in flags:
                counts["pfail"] += 1
            if node.get("link_state") != "connected" or flags.intersection({"handshake", "fail", "noaddr"}):
                continue
            role = str(node.get("role"))
            if role in {"primary", "replica"}:
                counts[role] += 1
        return counts
    return {"primary": 0, "replica": 0, "handshake": 0, "fail": 0, "pfail": 0}


def record_timing(
    timings: dict[str, dict[str, Any]],
    name: str,
    started: float,
    *,
    status: str = "PASS",
    details: dict[str, Any] | None = None,
) -> None:
    duration = max(time.monotonic() - started, 0.0)
    entry = timings.setdefault(
        name,
        {
            "name": name,
            "status": "PASS",
            "duration_seconds": 0.0,
            "count": 0,
            "details": {},
        },
    )
    entry["duration_seconds"] = round(float(entry.get("duration_seconds", 0.0)) + duration, 6)
    entry["count"] = int(entry.get("count", 0)) + 1
    if status == "FAIL":
        entry["status"] = "FAIL"
    if status == "SKIPPED_WITH_REASON" and entry.get("status") != "FAIL":
        entry["status"] = "SKIPPED_WITH_REASON"
    if details:
        entry.setdefault("details", {}).update(details)


def merge_timing_entries(*entry_groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for entries in entry_groups:
        for entry in entries:
            name = str(entry.get("name", "MISSING"))
            if not name or name == "MISSING":
                continue
            if entry.get("status") == "MISSING" and name in merged:
                continue
            merged[name] = dict(entry)
    return merged


def timing_entries(timings: dict[str, dict[str, Any]], required_names: list[str] | None = None) -> list[dict[str, Any]]:
    names = required_names or sorted(timings)
    entries: list[dict[str, Any]] = []
    for name in names:
        if name in timings:
            entries.append(timings[name])
        else:
            entries.append(
                {
                    "name": name,
                    "status": "MISSING",
                    "duration_seconds": None,
                    "count": 0,
                    "details": {"reason": "not recorded in this artifact producer"},
                }
            )
    return entries


def timing_duration(timings: dict[str, dict[str, Any]], name: str) -> float | str:
    value = timings.get(name, {}).get("duration_seconds")
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    return "MISSING"


def sum_timing_durations(timings: dict[str, dict[str, Any]], names: list[str]) -> float | str:
    values = [timing_duration(timings, name) for name in names]
    if not all(isinstance(value, (int, float)) for value in values):
        return "MISSING"
    return round(sum(float(value) for value in values), 6)


def accounting_summary(timings: dict[str, dict[str, Any]], total_gate_seconds: float) -> dict[str, Any]:
    accounted = 0.0
    missing: list[str] = []
    summary: dict[str, Any] = {"total_gate_seconds": round(total_gate_seconds, 6)}
    for name in P13_ACCOUNTING_NAMES:
        key = f"{name}_seconds"
        value = timing_duration(timings, name)
        summary[key] = value
        if isinstance(value, (int, float)):
            accounted += float(value)
        else:
            missing.append(name)
    unattributed = round(max(float(total_gate_seconds) - accounted, 0.0), 6)
    summary["accounted_seconds"] = round(accounted, 6)
    summary["unattributed_seconds"] = unattributed
    summary["unattributed_status"] = "PASS" if unattributed <= 10.0 and not missing else "FAIL"
    if missing:
        summary["unattributed_explanation"] = {
            "status": "MISSING",
            "reason": f"missing accounting entries: {', '.join(missing)}",
        }
    elif unattributed > 10.0:
        summary["unattributed_explanation"] = {
            "status": "FAIL",
            "reason": "unattributed wall time exceeded 10 seconds",
        }
    else:
        summary["unattributed_explanation"] = {
            "status": "PASS",
            "reason": "accounted wrapper timings explain gate wall time within 10 seconds",
        }
    return summary


def write_p13_timing_breakdown(
    path: Path,
    *,
    phase: str,
    scenario: str,
    run_id: str,
    node_count: int,
    runtime_entries: list[dict[str, Any]],
    wrapper_timings: dict[str, dict[str, Any]],
    accounting_timings: dict[str, dict[str, Any]],
    wait_timing: dict[str, Any],
    status: str,
    gate_started_monotonic: float,
) -> dict[str, Any]:
    timings = merge_timing_entries(runtime_entries, list(wrapper_timings.values()), list(accounting_timings.values()))
    final_full_probe_duration = timing_duration(wait_timing, "final_full_probe")
    diagnostic_full_probe_duration = timing_duration(wait_timing, "diagnostic_full_probe")
    total_gate_seconds = round(max(time.monotonic() - gate_started_monotonic, 0.0), 6)
    accounting = accounting_summary(timings, total_gate_seconds)
    artifact = {
        "schema_version": "v1",
        "artifact_type": "p13_timing_breakdown",
        "phase_id": phase,
        "run_id": run_id,
        "scenario": scenario,
        "created_at": utc_now(),
        "producer": {"name": "scripts/valkey_e2e_gate.py", "version": "v1"},
        "status": status,
        "node_count": node_count,
        "timings": timing_entries(timings, P13_TIMING_NAMES),
        "wrapper_probe_details": {
            "representative_probe_duration_seconds": timing_duration(wait_timing, "representative_probe"),
            "final_full_probe_duration_seconds": final_full_probe_duration,
            "diagnostic_full_probe_duration_seconds": diagnostic_full_probe_duration,
            "wait_cluster_ok_probe_counts": {
                name: wait_timing.get(name, {}).get("count", 0)
                for name in ["representative_probe", "final_full_probe", "diagnostic_full_probe"]
            },
        },
        "summary": {
            "cluster_create_duration_seconds": sum_timing_durations(
                timings,
                ["primary_cluster_create", "replica_meet", "replica_replicate"],
            ),
            "replica_config_duration_seconds": timing_duration(timings, "replica_replicate"),
            "wrapper_probe_duration_seconds": sum_timing_durations(
                timings,
                ["wrapper_wait_cluster_ok", "wrapper_data_path_probe"],
            ),
            "final_full_probe_duration_seconds": final_full_probe_duration,
            "diagnostic_full_probe_duration_seconds": diagnostic_full_probe_duration,
        },
        "accounting": accounting,
    }
    artifact["summary"].update(accounting)
    artifact_write_started = time.monotonic()
    write_json(path, artifact)
    record_timing(
        accounting_timings,
        "artifact_write",
        artifact_write_started,
        details={"path": str(path), "artifact": "p13_timing_breakdown"},
    )
    timings = merge_timing_entries(runtime_entries, list(wrapper_timings.values()), list(accounting_timings.values()))
    accounting = accounting_summary(timings, round(max(time.monotonic() - gate_started_monotonic, 0.0), 6))
    artifact["timings"] = timing_entries(timings, P13_TIMING_NAMES)
    artifact["accounting"] = accounting
    artifact["summary"].update(accounting)
    write_json(path, artifact)
    return artifact


def node_processes_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    keys = [
        "logical_id",
        "nodehost_id",
        "pid",
        "pid_file",
        "client_port",
        "cluster_bus_port",
        "role",
        "shard_id",
        "data_dir",
        "log_file",
        "config_file",
    ]
    return [{key: node.get(key, "MISSING") for key in keys} for node in state.get("nodes", [])]


def cleanup(phase: str, state_path: Path, artifact_dir: Path, timeout: int) -> tuple[str, Path, str, str, int]:
    cleanup_path = artifact_dir / "cleanup_report.json"
    cmd = [
        sys.executable, "-m", "valkey_scale_lab.cli", "gate", "cleanup",
        "--state", str(state_path),
        "--artifacts-dir", str(artifact_dir),
        "--out", str(cleanup_path),
    ]
    try:
        proc = run_cmd(cmd, timeout=timeout)
        status = "PASS" if proc.returncode == 0 else "FAIL"
        if not cleanup_path.exists():
            write_json(cleanup_path, {
                "schema_version": "v1",
                "artifact_type": "cleanup_report",
                "phase_id": phase,
                "run_id": f"phase-{phase}",
                "created_at": utc_now(),
                "producer": {"name": "valkey-scale-lab", "version": "unknown"},
                "status": "FAIL",
                "resources_remaining": [{"type": "unknown", "reason": "cleanup command did not write cleanup_report"}],
                "cleanup_actions": [],
            })
        return status, cleanup_path, proc.stdout, proc.stderr, proc.returncode
    except Exception as exc:  # noqa: BLE001
        write_json(cleanup_path, {
            "schema_version": "v1",
            "artifact_type": "cleanup_report",
            "phase_id": phase,
            "run_id": f"phase-{phase}",
            "created_at": utc_now(),
            "producer": {"name": "valkey-scale-lab", "version": "unknown"},
            "status": "FAIL",
            "resources_remaining": [{"type": "unknown", "reason": repr(exc)}],
            "cleanup_actions": [],
        })
        return "FAIL", cleanup_path, "", repr(exc), 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent real Valkey e2e gate wrapper")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-nodes", type=int, default=1)
    parser.add_argument("--expected-version-prefix", default="9.1.")
    parser.add_argument("--require-data-path", action="store_true")
    parser.add_argument("--setup-timeout", type=int, default=900)
    parser.add_argument("--cleanup-timeout", type=int, default=300)
    parser.add_argument("--probe-timeout", type=float, default=2.0)
    parser.add_argument("--wait-cluster-timeout", type=float, default=90.0)
    args = parser.parse_args()
    gate_started_monotonic = time.monotonic()

    out = Path(args.out)
    artifact_dir = out.parent
    artifact_dir.mkdir(parents=True, exist_ok=True)
    state_path = artifact_dir / f"state_{args.scenario}.json"
    setup_stdout = artifact_dir / f"{args.scenario}_setup.stdout.log"
    setup_stderr = artifact_dir / f"{args.scenario}_setup.stderr.log"

    setup_cmd = [
        sys.executable, "-m", "valkey_scale_lab.cli", "gate", "scenario",
        "--phase", args.phase,
        "--scenario", args.scenario,
        "--config", args.config,
        "--artifacts-dir", str(artifact_dir),
        "--state-out", str(state_path),
    ]

    started = utc_now()
    setup_status = "FAIL"
    cleanup_status = "FAIL"
    probes: list[dict[str, Any]] = []
    data_path_result = "SKIPPED_WITH_REASON" if not args.require_data_path else "FAIL"
    errors: list[str] = []
    valkey_versions: list[str] = []
    cluster_state = "unknown"
    state: dict[str, Any] = {}
    wrapper_timings: dict[str, dict[str, Any]] = {}
    accounting_timings: dict[str, dict[str, Any]] = {}
    wait_timing: dict[str, Any] = {}
    timing_breakdown_artifact: dict[str, Any] | None = None
    timing_breakdown_path: Path | None = None

    try:
        setup_command_started = time.monotonic()
        proc = run_cmd(setup_cmd, timeout=args.setup_timeout)
        record_timing(
            accounting_timings,
            "setup_command_wall",
            setup_command_started,
            status="PASS" if proc.returncode == 0 else "FAIL",
            details={"command": setup_cmd, "exit_code": proc.returncode},
        )
        write_text_timed(setup_stdout, proc.stdout, accounting_timings, "setup_stdout_write")
        write_text_timed(setup_stderr, proc.stderr, accounting_timings, "setup_stderr_write")
        if state_path.exists():
            try:
                state_load_started = time.monotonic()
                state = load_state(state_path)
                record_timing(accounting_timings, "state_load", state_load_started, details={"path": str(state_path)})
            except Exception as exc:  # noqa: BLE001
                record_timing(
                    accounting_timings,
                    "state_load",
                    state_load_started,
                    status="FAIL",
                    details={"path": str(state_path), "error": repr(exc)},
                )
                errors.append(f"setup wrote unreadable state file: {exc!r}")
        if proc.returncode != 0:
            errors.append(f"setup command failed exit={proc.returncode}")
        elif not state_path.exists():
            errors.append(f"setup did not write state file {state_path}")
        else:
            setup_status = "PASS"
            runtime = state.get("runtime", {})
            if runtime.get("sandbox_network") is not True:
                errors.append("state.runtime.sandbox_network must be true")
            endpoints = endpoints_from_state(state)
            wait_started = time.monotonic()
            ok, probes = wait_for_cluster_ok(
                endpoints,
                min_nodes=args.min_nodes,
                timeout_seconds=args.wait_cluster_timeout,
                timing=wait_timing,
            )
            record_timing(
                wrapper_timings,
                "wrapper_wait_cluster_ok",
                wait_started,
                status="PASS" if ok else "FAIL",
                details={
                    "min_nodes": args.min_nodes,
                    "endpoint_count": len(endpoints),
                    "representative_probe_duration_seconds": timing_duration(wait_timing, "representative_probe"),
                    "final_full_probe_duration_seconds": timing_duration(wait_timing, "final_full_probe"),
                    "diagnostic_full_probe_duration_seconds": timing_duration(wait_timing, "diagnostic_full_probe"),
                },
            )
            if not ok:
                errors.append("cluster did not reach observable OK state with required node count")
            for p in probes:
                if p.get("status") == "PASS":
                    if p.get("version"):
                        valkey_versions.append(str(p["version"]))
                    if p.get("cluster_state") == "ok":
                        cluster_state = "ok"
            bad_versions = [v for v in valkey_versions if not v.startswith(args.expected_version_prefix)]
            if bad_versions:
                errors.append(f"observed Valkey versions do not match {args.expected_version_prefix}: {bad_versions}")
            if args.require_data_path:
                key = f"{{vslab-probe}}:{args.phase}:{int(time.time())}"
                value = f"value-{args.scenario}"
                data_path_started = time.monotonic()
                data_path_status = "FAIL"
                try:
                    set_res = execute_cluster_command(endpoints, "SET", key, value, timeout=args.probe_timeout)
                    get_res = execute_cluster_command(endpoints, "GET", key, timeout=args.probe_timeout)
                    if str(set_res).upper() == "OK" and get_res == value:
                        data_path_result = "PASS"
                        data_path_status = "PASS"
                    else:
                        data_path_result = "FAIL"
                        errors.append(f"SET/GET mismatch set={set_res!r} get={get_res!r}")
                except Exception as exc:  # noqa: BLE001
                    data_path_result = "FAIL"
                    errors.append(f"data path probe failed: {exc!r}")
                finally:
                    record_timing(
                        wrapper_timings,
                        "wrapper_data_path_probe",
                        data_path_started,
                        status=data_path_status,
                        details={"required": True},
                    )
            else:
                skipped_started = time.monotonic()
                record_timing(
                    wrapper_timings,
                    "wrapper_data_path_probe",
                    skipped_started,
                    status="SKIPPED_WITH_REASON",
                    details={"required": False, "reason": "data path proof not requested"},
                )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"setup/probe exception: {exc!r}")
    finally:
        cleanup_started = time.monotonic()
        if state_path.exists():
            cleanup_command_started = time.monotonic()
            cleanup_status, cleanup_path, cleanup_stdout, cleanup_stderr, cleanup_exit = cleanup(
                args.phase, state_path, artifact_dir, args.cleanup_timeout
            )
            record_timing(
                accounting_timings,
                "cleanup_command_wall",
                cleanup_command_started,
                status=cleanup_status,
                details={"cleanup_path": str(cleanup_path), "exit_code": cleanup_exit},
            )
            write_text_timed(
                artifact_dir / f"{args.scenario}_cleanup.stdout.log",
                cleanup_stdout,
                accounting_timings,
                "cleanup_stdout_write",
            )
            write_text_timed(
                artifact_dir / f"{args.scenario}_cleanup.stderr.log",
                cleanup_stderr,
                accounting_timings,
                "cleanup_stderr_write",
            )
            if cleanup_status != "PASS":
                errors.append(f"cleanup failed exit={cleanup_exit}")
        else:
            cleanup_path = artifact_dir / "cleanup_report.json"
            write_json(cleanup_path, {
                "schema_version": "v1",
                "artifact_type": "cleanup_report",
                "phase_id": args.phase,
                "run_id": f"phase-{args.phase}",
                "created_at": utc_now(),
                "producer": {"name": "valkey-scale-lab", "version": "unknown"},
                "status": "FAIL",
                "resources_remaining": [{"type": "unknown", "reason": "no state file, cleanup could not run"}],
                "cleanup_actions": [],
            })
            cleanup_exit = 1
            skipped_started = time.monotonic()
            record_timing(
                accounting_timings,
                "cleanup_command_wall",
                skipped_started,
                status="FAIL",
                details={"cleanup_path": str(cleanup_path), "exit_code": cleanup_exit, "reason": "missing state file"},
            )
        record_timing(
            wrapper_timings,
            "cleanup",
            cleanup_started,
            status=cleanup_status,
            details={
                "cleanup_path": str(cleanup_path),
                "exit_code": cleanup_exit,
                "cleanup_command_wall_seconds": timing_duration(accounting_timings, "cleanup_command_wall"),
            },
        )

    status = "PASS" if not errors else "FAIL"
    if args.phase == "P13_SCALE_LADDER_50_100":
        timing_breakdown_path = artifact_dir / f"p13_timing_breakdown_{args.scenario}.json"
        timing_breakdown_artifact = write_p13_timing_breakdown(
            timing_breakdown_path,
            phase=args.phase,
            scenario=args.scenario,
            run_id=f"phase-{args.phase}-{args.scenario}",
            node_count=len(state.get("nodes", [])),
            runtime_entries=list(state.get("runtime", {}).get("timings", [])),
            wrapper_timings=wrapper_timings,
            accounting_timings=accounting_timings,
            wait_timing=wait_timing,
            status=status,
            gate_started_monotonic=gate_started_monotonic,
        )
    evidence = {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "phase_id": args.phase,
        "run_id": f"phase-{args.phase}-{args.scenario}",
        "created_at": utc_now(),
        "producer": {"name": "scripts/valkey_e2e_gate.py", "version": "v1"},
        "status": status,
        "real_valkey": True,
        "valkey_version_prefix_required": args.expected_version_prefix,
        "probe_result": "PASS" if not errors else "FAIL",
        "nodes_observed": len([p for p in probes if p.get("status") == "PASS"]),
        "cluster_state_observed": cluster_state,
        "data_path_result": data_path_result,
        "valkey_versions": sorted(set(valkey_versions)),
        "scenario": args.scenario,
        "started_at": started,
        "finished_at": utc_now(),
        "setup": {
            "command": setup_cmd,
            "status": setup_status,
            "stdout_path": str(setup_stdout),
            "stderr_path": str(setup_stderr),
        },
        "probes": probes,
        "runtime": state.get("runtime", {}),
        "nodehosts": state.get("nodehosts", []),
        "node_processes": node_processes_from_state(state),
        "role_counts": role_counts_from_probes(probes),
        "cluster_snapshots": state.get("cluster_snapshots", []),
        "timing_breakdown_path": str(timing_breakdown_path) if timing_breakdown_path is not None else "SKIPPED_WITH_REASON",
        "timing_breakdown": timing_breakdown_artifact.get("summary") if timing_breakdown_artifact else {
            "status": "SKIPPED_WITH_REASON",
            "reason": "P13 timing breakdown is only emitted for P13 scale gates",
        },
        "cleanup": {
            "status": cleanup_status,
            "path": str(cleanup_path),
        },
        "errors": errors,
    }
    write_json(out, evidence)
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS real_valkey_e2e scenario={args.scenario} nodes={evidence['nodes_observed']} out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
