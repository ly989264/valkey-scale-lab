from __future__ import annotations

import pytest

from valkey_scale_lab.observer.failover_timeline import (
    build_clean_gate_diagnostics,
    build_layered_recovery_summary,
    derive_rto_metrics,
)

CAPABILITY = "clean_gate_diagnostics"


def sample(**overrides):
    row = {
        "schema_version": "v1",
        "capability_id": CAPABILITY,
        "run_id": "run",
        "scenario_name": "clean_gate_diagnostics",
        "sample_id": "s30",
        "status": "PASS",
        "execution_mode": "real_valkey",
        "real_valkey": True,
        "node_count": 30,
        "scale": "30",
        "fault_apply_at_ms": 1000,
        "target_process_gone_at_ms": 1100,
        "first_pfail_seen_at_ms": 1200,
        "first_fail_seen_at_ms": 1300,
        "first_promotion_seen_at_ms": 1400,
        "first_slots_covered_at_ms": 1500,
        "first_cluster_ok_at_ms": 1600,
        "first_client_success_at_ms": 1700,
        "clean_snapshot_passed_at_ms": 2200,
        "observer_samples_ref": "observer_samples.jsonl#s30",
        "client_recovery_samples_ref": "client_recovery_samples.jsonl#s30",
        "clean_gate_probe_rounds_ref": "clean_gate_probe_rounds.jsonl#s30",
    }
    row.update(derive_rto_metrics(row))
    row.update(overrides)
    return row


def rounds():
    return [
        {
            "schema_version": "v1",
            "capability_id": CAPABILITY,
            "run_id": "run",
            "scenario_name": "clean_gate_diagnostics",
            "sample_id": "s30",
            "probe_start_ms": 1600,
            "probe_end_ms": 1650,
            "probe_duration_ms": 50,
            "sample_scope": "representative",
            "sample_count": 4,
            "status": "FAIL",
            "failed_reason": "membership_not_clean",
            "slowest_node": "node-1",
            "slowest_probe_ms": 50,
        },
        {
            "schema_version": "v1",
            "capability_id": CAPABILITY,
            "run_id": "run",
            "scenario_name": "clean_gate_diagnostics",
            "sample_id": "s30",
            "probe_start_ms": 2150,
            "probe_end_ms": 2200,
            "probe_duration_ms": 50,
            "sample_scope": "all_nodes",
            "sample_count": 30,
            "status": "PASS",
            "failed_reason": "",
            "slowest_node": "node-29",
            "slowest_probe_ms": 80,
        },
    ]


def test_clean_gate_diagnostics_aggregate_rounds_and_last_reason() -> None:
    diagnostics = build_clean_gate_diagnostics([sample()], rounds(), capability_id=CAPABILITY, run_id="diag")

    assert diagnostics["probe_round_count"] == 2
    assert diagnostics["full_probe_count"] == 1
    assert diagnostics["first_representative_clean_at_ms"] == "MISSING"
    assert diagnostics["first_all_nodes_clean_at_ms"] == 2200
    assert diagnostics["clean_gate_total_ms"] == 600
    assert diagnostics["slowest_probe_node"] == "node-29"
    assert diagnostics["last_failing_reason"] == "membership_not_clean"


def test_layered_summary_preserves_source_boundaries() -> None:
    summary = build_layered_recovery_summary([sample()], capability_id=CAPABILITY, run_id="summary")
    row = summary["per_sample"][0]

    assert row["pfail_to_cluster_ok_ms"] == 400
    assert row["level_1"]["source"] == "observer"
    assert row["level_2"]["source"] == "client_probe"
    assert row["level_3"]["source"] == "clean_gate"
    assert summary["clean_gate"]["final_all_node_clean_required"] is True


def test_layered_summary_rejects_non_monotonic_clean_tail() -> None:
    bad = sample(clean_snapshot_passed_at_ms=1500)
    with pytest.raises(Exception):
        build_layered_recovery_summary([bad], capability_id=CAPABILITY, run_id="summary")
