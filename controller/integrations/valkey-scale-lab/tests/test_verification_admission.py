from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = INTEGRATION_ROOT.parents[2]
PROJECT_ROOT = REPOSITORY_ROOT / "project"
EVALUATOR_ROOT = INTEGRATION_ROOT / "evaluators"
PRODUCER_PATH = INTEGRATION_ROOT / "tools/run_verification.py"
RECEIPT_SCHEMA = INTEGRATION_ROOT / "schemas/verification_receipts.schema.json"
POLICY_SCHEMA = INTEGRATION_ROOT / "schemas/verification_policy.schema.json"


def _module(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


PRODUCER = _module("tested_verification_producer", PRODUCER_PATH)
EVALUATOR = _module(
    "tested_verification_admission", EVALUATOR_ROOT / "verification_admission.py"
)


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _stage(tmp_path: Path) -> tuple[Path, Path, Path, Path, str]:
    workspace = tmp_path / "workspace"
    product = workspace / "product"
    milestone_path = product / "milestones/m1/milestone.json"
    catalog_path = product / "verification/catalog.json"
    runner_path = product / "verification/run.py"
    milestone = {
        "schema_version": "valkey-milestone-v1",
        "milestone": {"id": "m1", "version": "1.0.0", "title": "sample", "goal": "sample"},
        "prerequisite_milestone_ids": [],
        "success_conditions": [
            {
                "id": "sample.condition",
                "statement": "sample",
                "suite_ids": ["sample.contract"],
                "evidence_gate_ids": [],
            }
        ],
        "evidence_gates": [],
    }
    catalog = {
        "schema_version": "verification-catalog-v1",
        "suites": [
            {
                "id": "sample.contract",
                "title": "sample",
                "kind": "command",
                "status": "READY",
                "argv": ["python3", "-c", "print('verified')"],
                "timeout_seconds": 60,
                "capabilities": [],
                "outputs": [],
                "skip_policy": "FAIL",
            }
        ],
    }
    _write(milestone_path, milestone)
    _write(catalog_path, catalog)
    runner_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT_ROOT / "verification/run.py", runner_path)
    policy_path = tmp_path / "authority/verification_policy.json"
    _write(policy_path, PRODUCER.fingerprint(Path(sys.executable)))
    digest = PRODUCER.product_tree_digest(product)
    return workspace, milestone_path, catalog_path, policy_path, digest


def test_operator_producer_emits_current_receipts_admitted_by_independent_evaluator(
    tmp_path: Path,
) -> None:
    workspace, milestone_path, catalog_path, policy_path, digest = _stage(tmp_path)
    evidence_root = tmp_path / "run_evidence"
    envelope = PRODUCER.produce(
        python=Path(sys.executable),
        workspace_root=workspace,
        product_relative="product",
        milestone_id="m1",
        run_id="vpro-run-1",
        expected_product_digest=digest,
        evidence_root=evidence_root,
        policy_path=policy_path,
        allowed_capabilities=[],
    )
    assert [row["status"] for row in envelope["receipts"]] == ["PASS"]
    results = EVALUATOR.evaluate(
        milestone_path=milestone_path,
        catalog_path=catalog_path,
        receipts_schema_path=RECEIPT_SCHEMA,
        verification_policy_path=policy_path,
        verification_policy_schema_path=POLICY_SCHEMA,
        producer_path=PRODUCER_PATH,
        evidence_root=evidence_root,
        run_id="vpro-run-1",
        product_digest=digest,
        now_unix=envelope["generated_at_unix"],
    )
    assert results[0]["status"] == "PASS"


def test_tampered_log_and_handcrafted_skip_are_rejected(tmp_path: Path) -> None:
    workspace, milestone_path, catalog_path, policy_path, digest = _stage(tmp_path)
    evidence_root = tmp_path / "run_evidence"
    envelope = PRODUCER.produce(
        python=Path(sys.executable),
        workspace_root=workspace,
        product_relative="product",
        milestone_id="m1",
        run_id="vpro-run-1",
        expected_product_digest=digest,
        evidence_root=evidence_root,
        policy_path=policy_path,
        allowed_capabilities=[],
    )
    log_path = evidence_root / envelope["receipts"][0]["log"]["path"]
    log_path.write_text("forged\n", encoding="utf-8")
    receipt_path = evidence_root / "verification/receipts.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["receipts"][0]["skipped"] = 1
    _write(receipt_path, receipt)
    results = EVALUATOR.evaluate(
        milestone_path=milestone_path,
        catalog_path=catalog_path,
        receipts_schema_path=RECEIPT_SCHEMA,
        verification_policy_path=policy_path,
        verification_policy_schema_path=POLICY_SCHEMA,
        producer_path=PRODUCER_PATH,
        evidence_root=evidence_root,
        run_id="vpro-run-1",
        product_digest=digest,
        now_unix=envelope["generated_at_unix"],
    )
    errors = results[0]["provenance"]["errors"]
    assert any("skipped" in error for error in errors)
    assert any("log" in error for error in errors)
    assert any("digest" in error for error in errors)
