from __future__ import annotations

import json
import subprocess
from pathlib import Path

from valkey_scale_lab.observer.failover_timeline import (
    build_clean_gate_diagnostics,
    build_layered_recovery_summary,
    build_recovery_endpoint_summary,
    derive_rto_metrics,
)

CAPABILITY = "clean_gate_diagnostics"


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def sample(sample_id: str, node_count: int, **overrides):
    row = {
        "schema_version": "v1",
        "capability_id": CAPABILITY,
        "run_id": f"run-{sample_id}",
        "scenario_name": "clean_gate_diagnostics",
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
        "clean_snapshot_passed_at_ms": 2200 + node_count,
        "timeline_source": "concurrent_failover_timeline_observer",
        "client_probe_source": "continuous_fault_period_set_get",
        "first_client_success_source": "client_recovery_samples.jsonl",
        "observer_samples_ref": f"observer_samples.jsonl#{sample_id}",
        "client_recovery_samples_ref": f"client_recovery_samples.jsonl#{sample_id}",
        "clean_gate_probe_rounds_ref": f"clean_gate_probe_rounds.jsonl#{sample_id}",
        "level_1_source": "observer",
        "level_2_source": "client_probe",
        "level_3_source": "clean_gate",
        "clean_snapshot_endpoint": "separate_clean_gate_after_cluster_ok",
    }
    row.update(derive_rto_metrics(row))
    row.update(overrides)
    return row


def round_for(row: dict, status: str = "PASS") -> dict:
    return {
        "schema_version": "v1",
        "artifact_type": "clean_gate_probe_round",
        "capability_id": CAPABILITY,
        "run_id": row["run_id"],
        "scenario_name": row["scenario_name"],
        "sample_id": row["sample_id"],
        "probe_start_ms": row["first_cluster_ok_at_ms"],
        "probe_end_ms": row["clean_snapshot_passed_at_ms"],
        "probe_duration_ms": row["clean_snapshot_passed_at_ms"] - row["first_cluster_ok_at_ms"],
        "sample_scope": "all_nodes",
        "sample_count": row["node_count"],
        "status": status,
        "failed_reason": "" if status == "PASS" else "membership_not_clean",
        "slowest_node": "node-1",
        "slowest_probe_ms": 5,
    }


def populate(base: Path, rows: list[dict]) -> None:
    base.mkdir(parents=True)
    rounds = [round_for(row) for row in rows]
    write_jsonl(base / "failover_timeline_samples.jsonl", rows)
    write_jsonl(base / "clean_gate_probe_rounds.jsonl", rounds)
    write_jsonl(base / "observer_samples.jsonl", [{"sample_id": row["sample_id"], "capability_id": CAPABILITY, "status": "PASS"} for row in rows])
    write_jsonl(base / "client_recovery_samples.jsonl", [{"sample_id": row["sample_id"], "capability_id": CAPABILITY, "status": "PASS", "timestamp_unix_ms": row["first_client_success_at_ms"]} for row in rows])
    write_json(base / "clean_gate_diagnostics.json", build_clean_gate_diagnostics(rows, rounds, capability_id=CAPABILITY, run_id="diag"))
    write_json(base / "layered_recovery_summary.json", build_layered_recovery_summary(rows, capability_id=CAPABILITY, run_id="summary"))
    write_json(base / "recovery_endpoint_summary.json", build_recovery_endpoint_summary(rows, capability_id=CAPABILITY, run_id="endpoints"))
    write_json(base / "dry_run_gt_200_projection.json", {"dry_run": True, "real_valkey": False, "runtime_resources_created": False, "node_count": 1000})


def run_script(name: str, base: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", f"scripts/{name}.py", "--capability-id", CAPABILITY, "--artifact-dir", str(base), "--require-scales", "30,50,100,200"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )


def test_clean_gate_diagnostics_layered_assertions_pass_on_full_fixture(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    populate(base, [sample("s30", 30), sample("s50", 50), sample("s100", 100), sample("s200", 200)])

    for name in ["assert_clean_gate_diagnostics", "assert_layered_recovery_semantics", "assert_no_clean_gate_rto_conflation"]:
        proc = subprocess.run(["python3", f"scripts/{name}.py", "--capability-id", CAPABILITY, "--artifact-dir", str(base)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        assert proc.returncode == 0, proc.stderr
    proc = subprocess.run(
        ["python3", "scripts/assert_no_clean_gate_partial_coverage.py", "--capability-id", CAPABILITY, "--artifact-dir", str(base), "--require-scales", "30,50,100,200", "--require-dry-run-gt-200"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


def test_clean_gate_diagnostics_conflation_assertion_rejects_clean_snapshot_substitution(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    bad = sample("s30", 30)
    bad["pfail_to_cluster_ok_ms"] = bad["kill_to_clean_snapshot_ms"]
    populate(base, [bad, sample("s50", 50), sample("s100", 100), sample("s200", 200)])

    proc = subprocess.run(["python3", "scripts/assert_no_clean_gate_rto_conflation.py", "--capability-id", CAPABILITY, "--artifact-dir", str(base)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)

    assert proc.returncode == 1
    assert "pfail_to_cluster_ok_ms" in proc.stderr


def test_clean_gate_diagnostics_partial_coverage_rejects_historical_capability(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    bad = sample("s30", 30, capability_id="failover_timeline")
    populate(base, [bad])

    proc = subprocess.run(["python3", "scripts/assert_no_clean_gate_partial_coverage.py", "--capability-id", CAPABILITY, "--artifact-dir", str(base), "--require-scales", "30,50,100,200"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)

    assert proc.returncode == 1
    assert "historical capability_id" in proc.stderr
