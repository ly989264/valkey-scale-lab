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
from fault_failover_gate import workload_target_for_logical, workload_window  # noqa: E402
from valkey_probe_lib import endpoints_from_state, load_state, probe_endpoint, wait_for_cluster_ok  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n")


def run_cmd(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}" + env.get("PYTHONPATH", "")
    return subprocess.run(cmd, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def summarize_probes(probes: list[dict[str, Any]]) -> dict[str, Any]:
    versions = sorted({str(probe.get("version")) for probe in probes if probe.get("status") == "PASS"})
    ok = [probe for probe in probes if probe.get("status") == "PASS" and probe.get("cluster_state") == "ok"]
    return {
        "nodes_observed": len(ok),
        "probe_pass_count": len([probe for probe in probes if probe.get("status") == "PASS"]),
        "cluster_ok_count": len(ok),
        "valkey_versions": versions,
    }


def sample(
    endpoints: list[Any],
    *,
    run_id: str,
    elapsed_seconds: float,
    interval_index: int,
    metrics_out: Path,
    workload_target: dict[str, Any],
) -> dict[str, Any]:
    probes = [probe_endpoint(endpoint, timeout=2.0) for endpoint in endpoints]
    workload = workload_window("before_fault", endpoints, 1, f"{run_id}:{interval_index}", workload_target)
    workload_status = "PASS" if workload.get("roundtrip_failures") == 0 and workload.get("operation_count") == 2 else "FAIL"
    summary = summarize_probes(probes)
    row = {
        "schema_version": "v1",
        "artifact_type": "cml08_soak_sample",
        "run_id": run_id,
        "timestamp": utc_now(),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "interval_index": interval_index,
        "node_count": len(endpoints),
        "probe_summary": summary,
        "workload": {
            "status": workload_status,
            "latency_ms": workload.get("latency_ms"),
            "errors_total": workload.get("errors_total"),
            "timeouts_total": workload.get("timeouts_total"),
            "operation_count": workload.get("operation_count"),
            "roundtrip_successes": workload.get("roundtrip_successes"),
            "roundtrip_failures": workload.get("roundtrip_failures"),
            "samples": workload.get("samples", []),
        },
    }
    append_jsonl(metrics_out, row)
    return row


def checkpoint_status(samples: list[dict[str, Any]], checkpoint_seconds: int, min_nodes: int) -> dict[str, Any]:
    eligible = [sample for sample in samples if float(sample.get("elapsed_seconds", 0.0)) >= checkpoint_seconds]
    if not eligible:
        return {
            "checkpoint_seconds": checkpoint_seconds,
            "status": "MISSING",
            "reason": "checkpoint duration not reached",
        }
    sample = eligible[0]
    probe_summary = sample.get("probe_summary", {})
    workload = sample.get("workload", {})
    status = "PASS"
    reasons: list[str] = []
    if int(probe_summary.get("nodes_observed", 0)) < min_nodes:
        status = "FAIL"
        reasons.append("insufficient live nodes")
    if workload.get("status") != "PASS":
        status = "FAIL"
        reasons.append("data path workload failed")
    return {
        "checkpoint_seconds": checkpoint_seconds,
        "status": status,
        "observed_elapsed_seconds": sample.get("elapsed_seconds"),
        "nodes_observed": probe_summary.get("nodes_observed"),
        "probe_pass_count": probe_summary.get("probe_pass_count"),
        "workload_status": workload.get("status"),
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="CML08 real 30-node bounded soak runner")
    parser.add_argument("--phase", default="P12_SCALE_LADDER_10_30")
    parser.add_argument("--scenario", default="scale_30")
    parser.add_argument("--config", default="templates/configs/scale_30.yaml")
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--state-out", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--soak-report", required=True)
    parser.add_argument("--metrics-out", required=True)
    parser.add_argument("--cleanup-report", required=True)
    parser.add_argument("--duration-seconds", type=int, default=3600)
    parser.add_argument("--checkpoint-seconds", type=int, nargs="+", default=[1800, 3600])
    parser.add_argument("--sample-interval-seconds", type=int, default=60)
    parser.add_argument("--min-nodes", type=int, default=30)
    args = parser.parse_args()

    artifacts_dir = Path(args.artifacts_dir)
    state_out = Path(args.state_out)
    out = Path(args.out)
    soak_report = Path(args.soak_report)
    metrics_out = Path(args.metrics_out)
    cleanup_report = Path(args.cleanup_report)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in [out, soak_report, metrics_out, cleanup_report]:
        stale_path.unlink(missing_ok=True)
    run_id = f"phase-{args.phase}-{args.scenario}-cml08-bounded-soak"
    setup_started = utc_now()
    setup_cmd = [
        sys.executable,
        "-m",
        "valkey_scale_lab.cli",
        "gate",
        "scenario",
        "--phase",
        args.phase,
        "--scenario",
        args.scenario,
        "--config",
        args.config,
        "--artifacts-dir",
        str(artifacts_dir),
        "--state-out",
        str(state_out),
    ]
    cleanup_obj: dict[str, Any] = {"status": "NOT_RUN"}
    samples: list[dict[str, Any]] = []
    setup = run_cmd(setup_cmd, timeout=900)
    setup_stdout = artifacts_dir / "cml08_setup.stdout.log"
    setup_stderr = artifacts_dir / "cml08_setup.stderr.log"
    setup_stdout.write_text(setup.stdout, encoding="utf-8", errors="replace")
    setup_stderr.write_text(setup.stderr, encoding="utf-8", errors="replace")
    try:
        if setup.returncode != 0:
            raise RuntimeError(f"setup failed with exit {setup.returncode}")
        state = load_state(state_out)
        endpoints = endpoints_from_state(state)
        ok, initial_probes = wait_for_cluster_ok(endpoints, min_nodes=args.min_nodes, timeout_seconds=120.0, interval=2.0)
        if not ok:
            raise RuntimeError("cluster did not reach ok before soak")
        primary = next((endpoint for endpoint in endpoints if getattr(endpoint, "role", None) == "primary"), None)
        workload_target = workload_target_for_logical(endpoints, initial_probes, getattr(primary, "logical_id", None))
        if not workload_target:
            raise RuntimeError("could not select CML08 workload target")
        soak_started = time.monotonic()
        interval_index = 0
        while True:
            elapsed = time.monotonic() - soak_started
            samples.append(
                sample(
                    endpoints,
                    run_id=run_id,
                    elapsed_seconds=elapsed,
                    interval_index=interval_index,
                    metrics_out=metrics_out,
                    workload_target=workload_target,
                )
            )
            if elapsed >= args.duration_seconds:
                break
            interval_index += 1
            sleep_for = min(float(args.sample_interval_seconds), max(float(args.duration_seconds) - elapsed, 0.0))
            if sleep_for > 0:
                time.sleep(sleep_for)
        final_probes = [probe_endpoint(endpoint, timeout=2.0) for endpoint in endpoints]
        checkpoints = [checkpoint_status(samples, checkpoint, args.min_nodes) for checkpoint in args.checkpoint_seconds]
        data_path_result = "PASS" if samples and all(sample.get("workload", {}).get("status") == "PASS" for sample in samples) else "FAIL"
        status = "PASS" if data_path_result == "PASS" and all(checkpoint.get("status") == "PASS" for checkpoint in checkpoints) else "FAIL"
        report = {
            "schema_version": "v1",
            "artifact_type": "cml08_bounded_soak_report",
            "phase_id": args.phase,
            "scenario": args.scenario,
            "run_id": run_id,
            "created_at": utc_now(),
            "status": status,
            "node_count": len(endpoints),
            "duration_seconds": round(time.monotonic() - soak_started, 3),
            "sample_interval_seconds": args.sample_interval_seconds,
            "sample_count": len(samples),
            "checkpoints": checkpoints,
            "data_path_result": data_path_result,
            "initial_probe_summary": summarize_probes(initial_probes),
            "final_probe_summary": summarize_probes(final_probes),
            "metrics_path": str(metrics_out),
        }
        write_json(soak_report, report)
        evidence = {
            "schema_version": "v1",
            "artifact_type": "valkey_e2e_evidence",
            "phase_id": args.phase,
            "run_id": run_id,
            "created_at": utc_now(),
            "producer": {"name": "tools/cml08_bounded_soak_runner.py", "version": "v1"},
            "status": status,
            "real_valkey": True,
            "valkey_version_prefix_required": "9.1.",
            "probe_result": "PASS" if report["final_probe_summary"]["nodes_observed"] >= args.min_nodes else "FAIL",
            "nodes_observed": report["final_probe_summary"]["nodes_observed"],
            "cluster_state_observed": "ok" if report["final_probe_summary"]["nodes_observed"] >= args.min_nodes else "unknown",
            "data_path_result": data_path_result,
            "valkey_versions": report["final_probe_summary"]["valkey_versions"],
            "scenario": args.scenario,
            "started_at": setup_started,
            "finished_at": utc_now(),
            "soak_report_path": str(soak_report),
        }
        write_json(out, evidence)
    finally:
        if state_out.exists():
            cleanup_cmd = [
                sys.executable,
                "-m",
                "valkey_scale_lab.cli",
                "gate",
                "cleanup",
                "--state",
                str(state_out),
                "--artifacts-dir",
                str(artifacts_dir),
                "--out",
                str(cleanup_report),
            ]
            cleanup = run_cmd(cleanup_cmd, timeout=300)
            cleanup_obj = {
                "status": "PASS" if cleanup.returncode == 0 else "FAIL",
                "returncode": cleanup.returncode,
                "stdout": cleanup.stdout,
                "stderr": cleanup.stderr,
            }
            if cleanup_report.exists():
                try:
                    cleanup_obj.update(json.loads(cleanup_report.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    pass
            write_json(cleanup_report, cleanup_obj)
    final_evidence = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"status": "FAIL"}
    if cleanup_obj.get("status") != "PASS":
        final_evidence["status"] = "FAIL"
        final_evidence["cleanup_status"] = cleanup_obj.get("status")
        write_json(out, final_evidence)
    print(f"{final_evidence.get('status')} cml08_bounded_soak out={out} cleanup={cleanup_obj.get('status')}")
    return 0 if final_evidence.get("status") == "PASS" and cleanup_obj.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
