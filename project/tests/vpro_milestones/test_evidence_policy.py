from __future__ import annotations

import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = PROJECT_ROOT / "evaluators/vpro/evidence_policy.py"


def _policy():
    spec = importlib.util.spec_from_file_location("tested_vpro_evidence_policy", POLICY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_distributed_policy_rejects_partial_evidence(tmp_path: Path) -> None:
    capture = tmp_path / "capture"
    capture.mkdir()
    (capture / "admission.json").write_text(
        json.dumps(
            {
                "schema_version": "vpro-distributed-admission-v1",
                "execution_kind": "REAL_VALKEY_EXACT_SCALE",
                "runtime_backend": "NATIVE_MULTI_ECS",
                "requested_nodes": 200,
                "observed_nodes": 199,
                "status": "PASS",
                "product_digest": "a" * 64,
                "coverage": {},
                "cleanup": {"status": "PASS", "residual_owned_resources": 0},
            }
        ),
        encoding="utf-8",
    )

    decision = _policy().evaluate(
        milestone=2,
        scale=200,
        capture_root=capture,
        product_digest="a" * 64,
        prior_decision=None,
    )

    assert decision["status"] == "FAIL"
    assert any("observed_nodes" in error for error in decision["errors"])
    assert any("coverage" in error for error in decision["errors"])


def test_scale_promotion_must_bind_the_prior_decision(tmp_path: Path) -> None:
    policy = _policy()
    candidate = {
        "schema_version": "vpro-distributed-admission-v1",
        "execution_kind": "REAL_VALKEY_EXACT_SCALE",
        "runtime_backend": "NATIVE_MULTI_ECS",
        "requested_nodes": 1000,
        "observed_nodes": 1000,
        "status": "PASS",
        "product_digest": "b" * 64,
        "placement": {"hosts": ["h1", "h2"], "availability_zones": ["az1", "az2"]},
        "clock_offsets_ms": {"h1": 0.1, "h2": -0.2},
        "coverage": {name: "PASS" for name in policy.REQUIRED_COVERAGE},
        "cleanup": {"status": "PASS", "residual_owned_resources": 0},
        "promoted_from_admission_digest": "c" * 64,
    }
    candidate["admission_digest"] = policy._canonical_digest(candidate)
    capture = tmp_path / "capture"
    capture.mkdir()
    (capture / "admission.json").write_text(json.dumps(candidate), encoding="utf-8")

    decision = policy.evaluate(
        milestone=3,
        scale=1000,
        capture_root=capture,
        product_digest="b" * 64,
        prior_decision={"status": "PASS", "decision_digest": "d" * 64},
    )

    assert decision["status"] == "FAIL"
    assert any("promotion" in error for error in decision["errors"])


def test_milestone2_scale_promotion_also_binds_the_prior_decision(tmp_path: Path) -> None:
    policy = _policy()
    candidate = {
        "schema_version": "vpro-distributed-admission-v1",
        "execution_kind": "REAL_VALKEY_EXACT_SCALE",
        "runtime_backend": "NATIVE_MULTI_ECS",
        "requested_nodes": 200,
        "observed_nodes": 200,
        "status": "PASS",
        "product_digest": "e" * 64,
        "placement": {"hosts": ["h1", "h2"], "availability_zones": ["az1", "az2"]},
        "clock_offsets_ms": {"h1": 0.1, "h2": -0.2},
        "coverage": {name: "PASS" for name in policy.REQUIRED_COVERAGE},
        "cleanup": {"status": "PASS", "residual_owned_resources": 0},
        "promoted_from_admission_digest": "f" * 64,
    }
    candidate["admission_digest"] = policy._canonical_digest(candidate)
    capture = tmp_path / "capture"
    capture.mkdir()
    (capture / "admission.json").write_text(json.dumps(candidate), encoding="utf-8")

    decision = policy.evaluate(
        milestone=2,
        scale=200,
        capture_root=capture,
        product_digest="e" * 64,
        prior_decision={"status": "PASS", "decision_digest": "a" * 64},
    )

    assert decision["status"] == "FAIL"
    assert any("promotion" in error for error in decision["errors"])
