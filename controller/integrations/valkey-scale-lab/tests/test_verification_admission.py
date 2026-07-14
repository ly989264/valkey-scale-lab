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
RUNNER_PATH = INTEGRATION_ROOT / "tools/run_verification.py"
RESULTS_SCHEMA = INTEGRATION_ROOT / "schemas/verification_results.schema.json"


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


RUNNER = _module("tested_verification_runner", RUNNER_PATH)
ADMISSION = _module(
    "tested_verification_admission", EVALUATOR_ROOT / "verification_admission.py"
)


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _stage(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    workspace = tmp_path / "workspace"
    product = workspace / "product"
    milestone_path = product / "milestones/m1/milestone.json"
    catalog_path = product / "verification/catalog.json"
    milestone = {
        "schema_version": "valkey-milestone-v2",
        "milestone": {"id": "m1", "version": "2.0.0", "title": "sample", "final_goal": "sample"},
        "prerequisite_milestone_ids": [],
        "success_conditions": [
            {
                "id": "sample.condition",
                "statement": "sample",
                "suite_ids": ["sample.contract"],
                "evidence_requirement_ids": [],
                "required": True,
            }
        ],
        "real_evidence_requirements": [],
    }
    catalog = {
        "schema_version": "verification-catalog-v1",
        "suites": [
            {
                "id": "sample.contract",
                "title": "sample",
                "kind": "pytest",
                "status": "READY",
                "argv": ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                "timeout_seconds": 60,
                "capabilities": [],
                "outputs": [],
                "skip_policy": "FAIL",
            }
        ],
    }
    _write(milestone_path, milestone)
    _write(catalog_path, catalog)
    shutil.copy2(PROJECT_ROOT / "verification/run.py", product / "verification/run.py")
    (product / "tests").mkdir()
    (product / "tests/test_sample.py").write_text(
        "def test_sample():\n    assert True\n", encoding="utf-8"
    )
    digest = RUNNER.product_tree_digest(product)
    return workspace, milestone_path, catalog_path, digest


def test_current_structured_results_are_admitted(tmp_path: Path) -> None:
    workspace, milestone_path, catalog_path, digest = _stage(tmp_path)
    evidence_root = tmp_path / "evidence"
    bundle = RUNNER.produce(
        python=Path(sys.executable),
        workspace_root=workspace,
        product_relative="product",
        milestone_id="m1",
        run_id="run-1",
        expected_product_digest=digest,
        evidence_root=evidence_root,
    )
    assert [row["status"] for row in bundle["results"]] == ["PASS"]
    results = ADMISSION.evaluate(
        milestone_path=milestone_path,
        catalog_path=catalog_path,
        results_schema_path=RESULTS_SCHEMA,
        evidence_root=evidence_root,
        run_id="run-1",
        product_digest=digest,
        now_unix=bundle["generated_at_unix"],
    )
    assert results[0]["status"] == "PASS"


def test_tampered_log_and_handcrafted_skip_are_rejected(tmp_path: Path) -> None:
    workspace, milestone_path, catalog_path, digest = _stage(tmp_path)
    evidence_root = tmp_path / "evidence"
    bundle = RUNNER.produce(
        python=Path(sys.executable),
        workspace_root=workspace,
        product_relative="product",
        milestone_id="m1",
        run_id="run-1",
        expected_product_digest=digest,
        evidence_root=evidence_root,
    )
    (evidence_root / bundle["results"][0]["log"]["path"]).write_text("forged\n")
    bundle_path = evidence_root / "verification/results.json"
    changed = json.loads(bundle_path.read_text())
    changed["results"][0]["skipped"] = 1
    _write(bundle_path, changed)
    results = ADMISSION.evaluate(
        milestone_path=milestone_path,
        catalog_path=catalog_path,
        results_schema_path=RESULTS_SCHEMA,
        evidence_root=evidence_root,
        run_id="run-1",
        product_digest=digest,
        now_unix=bundle["generated_at_unix"],
    )
    errors = results[0]["provenance"]["errors"]
    assert any("skipped" in error for error in errors)
    assert any("log" in error for error in errors)
    assert any("digest" in error for error in errors)
