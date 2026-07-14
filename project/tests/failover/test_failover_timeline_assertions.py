from __future__ import annotations

import json
import subprocess
from pathlib import Path

from valkey_scale_lab.observer.failover_timeline import derive_rto_metrics

CAPABILITY = "failover_timeline"


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def sample(sample_id: str, node_count: int, **overrides):
    row = {
        "schema_version": "v1",
        "capability_id": CAPABILITY,
        "run_id": f"run-{sample_id}",
        "scenario_name": f"scenario-{sample_id}",
        "sample_id": sample_id,
        "status": "PASS",
        "execution_mode": "real_valkey",
        "real_valkey": True,
        "node_count": node_count,
        "scale": str(node_count),
        "fault_apply_at_ms": 1000 + node_count,
        "target_process_gone_at_ms": 1100 + node_count,
        "first_pfail_seen_at_ms": 1200 + node_count,
        "first_fail_seen_at_ms": 1300 + node_count,
        "first_promotion_seen_at_ms": 1400 + node_count,
        "first_slots_covered_at_ms": 1500 + node_count,
        "first_cluster_ok_at_ms": 1600 + node_count,
        "first_client_success_at_ms": 1700 + node_count,
        "clean_snapshot_passed_at_ms": 2100 + node_count,
        "timeline_source": "concurrent_failover_timeline_observer",
        "client_probe_source": "continuous_fault_period_set_get",
        "first_client_success_source": "client_recovery_samples.jsonl",
        "observer_samples_ref": f"observer_samples.jsonl#{sample_id}",
        "client_recovery_samples_ref": f"client_recovery_samples.jsonl#{sample_id}",
    }
    row.update(derive_rto_metrics(row))
    row.update(overrides)
    return row


def populate(base: Path, samples: list[dict]) -> None:
    base.mkdir(parents=True)
    write_jsonl(base / "failover_timeline_samples.jsonl", samples)
    write_jsonl(
        base / "client_recovery_samples.jsonl",
        [
            {
                "schema_version": "v1",
                "capability_id": CAPABILITY,
                "run_id": row["run_id"],
                "scenario_name": row["scenario_name"],
                "sample_id": row["sample_id"],
                "timestamp_unix_ms": row["first_client_success_at_ms"],
                "monotonic_ms": row["first_client_success_at_ms"],
                "status": "PASS",
                "probe_type": "continuous_fault_period_set_get",
                "fault_active": True,
                "key": f"key-{row['sample_id']}",
                "set_status": "PASS",
                "get_status": "PASS",
                "latency_ms": 1.0,
                "moved_count": 0,
                "ask_count": 0,
                "timeout": False,
            }
            for row in samples
        ],
    )
    write_jsonl(
        base / "observer_samples.jsonl",
        [
            {
                "schema_version": "v1",
                "capability_id": CAPABILITY,
                "run_id": row["run_id"],
                "scenario_name": row["scenario_name"],
                "sample_id": row["sample_id"],
                "timestamp_unix_ms": row["first_cluster_ok_at_ms"],
                "monotonic_ms": row["first_cluster_ok_at_ms"],
                "node_count": row["node_count"],
                "status": "PASS",
                "cluster_state": "ok",
                "cluster_slots_assigned": 16384,
                "cluster_slots_ok": 16384,
                "pfail_count": 1,
                "fail_count": 1,
                "handshake_count": 0,
                "target_reachable": False,
                "expected_replica_promoted": True,
                "observed_node_count": row["node_count"],
                "probe_status_counts": {"PASS": 1, "FAIL": 0},
            }
            for row in samples
        ],
    )
    windows = []
    for row in samples:
        empty_metrics = {
            "requested_qps": 4.0,
            "achieved_qps": "MISSING",
            "ok_ops": 0,
            "error_ops": 0,
            "error_rate": "MISSING",
            "latency_p50_ms": "MISSING",
            "latency_p90_ms": "MISSING",
            "latency_p95_ms": "MISSING",
            "latency_p99_ms": "MISSING",
            "latency_p999_ms": "MISSING",
            "timeout_count": 0,
            "connection_error_count": 0,
            "moved_redirection_count": 0,
            "ask_redirection_count": 0,
            "cluster_down_error_count": 0,
            "readonly_error_count": 0,
            "tryagain_error_count": 0,
            "unknown_error_count": 0,
            "sample_count": 0,
            "missing_reasons": {"window_samples": "no rows in fake assertion fixture"},
        }
        all_run_metrics = {
            **empty_metrics,
            "achieved_qps": round(1 / ((row["clean_snapshot_passed_at_ms"] - row["fault_apply_at_ms"]) / 1000), 3),
            "ok_ops": 1,
            "error_rate": 0.0,
            "latency_p50_ms": 1.0,
            "latency_p90_ms": 1.0,
            "latency_p95_ms": 1.0,
            "latency_p99_ms": 1.0,
            "latency_p999_ms": 1.0,
            "sample_count": 1,
            "missing_reasons": {},
        }
        for name in ["baseline", "pre_event", "event", "recovery", "post_recovery"]:
            windows.append(
                {
                    "window_name": name,
                    "sample_id": row["sample_id"],
                    "start_event_id": f"{row['sample_id']}-{name}-start",
                    "end_event_id": f"{row['sample_id']}-{name}-end",
                    "metrics": empty_metrics,
                }
            )
        windows.append(
            {
                "window_name": "all_run",
                "sample_id": row["sample_id"],
                "start_event_id": f"{row['sample_id']}-fault_apply",
                "end_event_id": f"{row['sample_id']}-clean_snapshot_passed",
                "start_time_unix_ms": row["fault_apply_at_ms"],
                "end_time_unix_ms": row["clean_snapshot_passed_at_ms"],
                "metrics": all_run_metrics,
            }
        )
    write_json(
        base / "workload_windows.json",
        {
            "schema_version": "v1",
            "artifact_type": "workload_windows",
            "capability_id": CAPABILITY,
            "run_id": "workload-windows",
            "windows": windows,
        },
    )
    write_json(
        base / "failover_rto_summary.json",
        {
            "schema_version": "v1",
            "artifact_type": "failover_rto_summary",
            "capability_id": CAPABILITY,
            "run_id": "summary",
            "status": "PASS",
            "sample_count": len(samples),
            "sample_refs": [row["sample_id"] for row in samples],
            "timeout_config_ms": 30000,
            "server_profile": "global_default",
            "nodehost_strategy": "configured_plan",
            "node_count": max(row["node_count"] for row in samples),
            "scale": "30,50,100,200",
            "observed_real_scales": sorted({row["node_count"] for row in samples}),
            "derived_series": {
                metric: {
                    "sample_count": len(samples),
                    "p50_ms": samples[0][metric],
                    "p95_ms": max(row[metric] for row in samples),
                    "max_ms": max(row[metric] for row in samples),
                    "percentile_method": "nearest_rank_round_index",
                }
                for metric in [
                    "kill_to_pfail_ms",
                    "pfail_to_cluster_ok_ms",
                    "kill_to_client_recovered_ms",
                    "cluster_ok_to_clean_snapshot_ms",
                    "kill_to_clean_snapshot_ms",
                ]
            },
        },
    )


def run_script(name: str, base: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", f"scripts/{name}.py", "--capability-id", CAPABILITY, "--artifact-dir", str(base), "--require-scales", "30,50,100,200"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )


def test_completeness_assertion_passes_on_full_real_coverage(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    populate(base, [sample("s30", 30), sample("s50", 50), sample("s100", 100), sample("s200", 200)])

    proc = run_script("assert_failover_timeline_completeness", base)

    assert proc.returncode == 0, proc.stderr


def test_completeness_assertion_fails_on_missing_pfail(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    populate(base, [sample("s30", 30, first_pfail_seen_at_ms="MISSING"), sample("s50", 50), sample("s100", 100), sample("s200", 200)])

    proc = run_script("assert_failover_timeline_completeness", base)

    assert proc.returncode == 1
    assert "first_pfail_seen_at_ms" in proc.stderr


def test_semantics_assertion_rejects_clean_gate_substitution(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    bad = sample("s30", 30)
    bad["pfail_to_cluster_ok_ms"] = bad["kill_to_clean_snapshot_ms"]
    populate(base, [bad, sample("s50", 50), sample("s100", 100), sample("s200", 200)])

    proc = subprocess.run(
        ["python3", "scripts/assert_rto_metric_semantics.py", "--capability-id", CAPABILITY, "--artifact-dir", str(base)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )

    assert proc.returncode == 1
    assert "pfail_to_cluster_ok_ms" in proc.stderr


def test_partial_coverage_assertion_rejects_one_scale_only(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    populate(base, [sample("s30", 30)])
    write_json(base / "dry_run_gt_200_projection.json", {"dry_run": True, "real_valkey": False, "runtime_resources_created": False, "node_count": 1000})

    proc = subprocess.run(
        [
            "python3",
            "scripts/assert_no_rto_partial_coverage.py",
            "--capability-id",
            CAPABILITY,
            "--artifact-dir",
            str(base),
            "--require-scales",
            "30,50,100,200",
            "--require-dry-run-gt-200",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )

    assert proc.returncode == 1
    assert "only one scale" in proc.stderr


def test_partial_coverage_assertion_rejects_synthetic_workload_metrics(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    populate(base, [sample("s30", 30), sample("s50", 50), sample("s100", 100), sample("s200", 200)])
    write_json(base / "dry_run_gt_200_projection.json", {"dry_run": True, "real_valkey": False, "runtime_resources_created": False, "node_count": 1000})
    artifact = json.loads((base / "workload_windows.json").read_text(encoding="utf-8"))
    for window in artifact["windows"]:
        if window["window_name"] == "all_run" and window["sample_id"] == "s30":
            window["metrics"]["sample_count"] = 999
    write_json(base / "workload_windows.json", artifact)

    proc = subprocess.run(
        [
            "python3",
            "scripts/assert_no_rto_partial_coverage.py",
            "--capability-id",
            CAPABILITY,
            "--artifact-dir",
            str(base),
            "--require-scales",
            "30,50,100,200",
            "--require-dry-run-gt-200",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )

    assert proc.returncode == 1
    assert "all_run sample_count" in proc.stderr
