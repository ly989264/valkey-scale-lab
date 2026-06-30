from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def load(path: str) -> dict:
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def assert_normal_real_evidence(path: str, scenario: str) -> None:
    evidence = load(path)
    producer = evidence["producer"]["name"]

    assert producer == "scripts/valkey_e2e_gate.py"
    assert evidence["status"] == "PASS"
    assert evidence["real_valkey"] is True
    assert evidence["nodes_observed"] == 6
    assert evidence["cluster_state_observed"] == "ok"
    assert evidence["data_path_result"] == "PASS"
    assert evidence["cleanup"]["status"] == "PASS"
    assert evidence["scenario"] == scenario
    assert evidence["valkey_versions"]
    assert all(version.startswith("9.1.") for version in evidence["valkey_versions"])


def test_normal_small_real_wrapper_evidence_contracts() -> None:
    cases = [
        ("artifacts/phases/P03_LOCAL_DOCKER_VALKEY/valkey_e2e_evidence.json", "cluster_smoke"),
        ("artifacts/phases/P04_CLUSTER_MANAGEMENT_OPS/valkey_e2e_evidence.json", "management_ops"),
        ("artifacts/phases/P05_WORKLOAD_ENGINE/valkey_e2e_evidence.json", "workload_smoke"),
        ("artifacts/phases/P06_OBSERVABILITY_METRICS/valkey_e2e_evidence.json", "observability_smoke"),
        ("artifacts/phases/P09_ANALYSIS_REPORTING/valkey_e2e_evidence.json", "reporting_source_smoke"),
        ("artifacts/phases/P10_MULTI_HOST_ORCHESTRATION/valkey_e2e_evidence.json", "orchestrated_localhost"),
        ("artifacts/phases/P11_STABILITY_SOAK/valkey_e2e_evidence.json", "stability_soak_smoke"),
    ]

    for path, scenario in cases:
        assert_normal_real_evidence(path, scenario)


def test_fault_sandbox_real_evidence_and_safety_contract() -> None:
    evidence = load("artifacts/phases/P07_FAULT_INJECTION_SANDBOX/valkey_e2e_evidence.json")
    report = load("artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_report.json")

    assert evidence["producer"]["name"] == "scripts/fault_safety_gate.py"
    assert evidence["status"] == "PASS"
    assert evidence["real_valkey"] is True
    assert evidence["nodes_observed"] == 6
    assert evidence["cluster_state_observed"] == "ok"
    assert evidence["data_path_result"] == "SKIPPED_WITH_REASON"
    assert evidence["cleanup"]["status"] == "PASS"
    assert all(version.startswith("9.1.") for version in evidence["valkey_versions"])

    safety = report["safety_checks"]
    assert safety["sandbox_only"] is True
    assert safety["host_network_mutated"] is False
    assert safety["global_firewall_mutated"] is False
    assert safety["fault_state_cleared"] is True


def test_failover_primary_stop_contract_preserves_missing_split_brain() -> None:
    evidence = load("artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/valkey_e2e_evidence.json")
    report = load("artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/failover_report.json")
    state = load("artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/state_failover.json")

    assert evidence["producer"]["name"] == "scripts/fault_failover_gate.py"
    assert evidence["status"] == "PASS"
    assert evidence["real_valkey"] is True
    assert evidence["nodes_observed"] >= 5
    assert evidence["cluster_state_observed"] == "ok"
    assert evidence["data_path_result"] == "SKIPPED_WITH_REASON"
    assert evidence["cleanup"]["status"] == "PASS"
    assert all(version.startswith("9.1.") for version in evidence["valkey_versions"])

    assert len(state["nodes"]) == 6
    assert report["summary"]["primary_stop_observed"] is True
    assert report["summary"]["promotion_observed"] is True
    assert report["failovers"][0]["failover_latency_ms"] > 0
    split = report["summary"]["split_brain_duration_ms"]
    assert split["value"] is None
    assert split["status"] == "MISSING"
    assert split["reason"] == "not_measured_by_primary_stop_gate"
