from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from valkey_scale_lab.vpro.contracts import load_bundle
from valkey_scale_lab.vpro.milestone import validate_milestone


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPO_ROOT / "project"
BUNDLE_ROOT = REPO_ROOT / "controller/bundles/valkey-scale-lab"
SCHEMA_PATH = REPO_ROOT / "controller/vpro/schemas/vpro/milestone_bundle.schema.json"
ADAPTER_PATH = PROJECT_ROOT / "checks/vpro/milestone_check.py"


def _adapter():
    spec = importlib.util.spec_from_file_location("tested_vpro_milestone_adapter", ADAPTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _isolated_pytest_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "operator-bin/pytest"
    executable.parent.mkdir(parents=True)
    site_root = Path(pytest.__file__).resolve().parent.parent
    executable.write_text(
        f"#!{sys.executable}\n"
        "import runpy, sys\n"
        f"sys.path.insert(0, {str(site_root)!r})\n"
        "sys.argv[0] = 'pytest'\n"
        "runpy.run_module('pytest', run_name='__main__')\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def test_all_product_milestone_bundles_are_valid_and_complete() -> None:
    expected = {
        "milestone1.bundle.json": ("Milestone1LocalLifecycle", ("M1Exact50", "M1Exact200")),
        "milestone2.bundle.json": ("Milestone2NativeMultiECS", ("M2MultiECS50", "M2MultiECS200")),
        "milestone3.bundle.json": ("Milestone3MultiECSScaleOut", ("M3Exact500", "M3Exact1000", "M3Exact2000")),
    }
    for name, (milestone_id, gate_ids) in expected.items():
        bundle = load_bundle(BUNDLE_ROOT / name, project_root=PROJECT_ROOT)
        resolved = bundle.resolve_profile("complete")
        assert bundle.milestone.id == milestone_id
        assert resolved.claim == "MILESTONE_COMPLETE"
        assert resolved.gate_ids == gate_ids
        assert "pytest" in bundle.integrity.allowed_tools
        assert set(clause.id for clause in bundle.clauses) == {
            clause_id
            for objective in resolved.objectives
            for clause_id in objective.clause_ids
        }


def test_authoritative_safety_scan_reads_only_declared_inputs() -> None:
    adapter = _adapter()
    expected = {
        "checks/vpro/milestone_check.py",
        *adapter.SAFETY_SCAN_DIRS,
        *adapter.SAFETY_SCAN_FILES,
    }
    for milestone in (1, 2, 3):
        bundle = load_bundle(
            BUNDLE_ROOT / f"milestone{milestone}.bundle.json",
            project_root=PROJECT_ROOT,
        )
        assert set(bundle.check(f"m{milestone}-static-safety").inputs) == expected


def test_all_milestones_report_missing_independent_authority_as_blocked() -> None:
    expected_evaluators = {
        "milestone1.bundle.json": "evaluators/vpro/milestone1_evidence_policy.py",
        "milestone2.bundle.json": "evaluators/vpro/milestone2_evidence_policy.py",
        "milestone3.bundle.json": "evaluators/vpro/milestone3_evidence_policy.py",
    }
    for name, evaluator_path in expected_evaluators.items():
        report = validate_milestone(
            BUNDLE_ROOT / name,
            project_root=PROJECT_ROOT,
            schema_path=SCHEMA_PATH,
        )
        assert report["status"] == "PASS"
        assert report["execution_readiness"]["status"] == "BLOCKED"
        assert report["execution_readiness"]["missing_authority_paths"]
        assert evaluator_path in report["execution_readiness"]["missing_authority_paths"]

    m1 = validate_milestone(
        BUNDLE_ROOT / "milestone1.bundle.json",
        project_root=PROJECT_ROOT,
        schema_path=SCHEMA_PATH,
    )["execution_readiness"]["missing_authority_paths"]
    assert set(m1) == {
        "evaluators/vpro/milestone1_evidence_policy.py",
        "tests/vpro_milestones/test_milestone1_evidence_policy.py",
        "tests/vpro_milestones/test_milestone1_sandbox_network_proxy.py",
    }

    m2 = validate_milestone(
        BUNDLE_ROOT / "milestone2.bundle.json",
        project_root=PROJECT_ROOT,
        schema_path=SCHEMA_PATH,
    )["execution_readiness"]["missing_authority_paths"]
    assert "checks/vpro/milestone2_preflight.py" in m2
    assert "checks/vpro/milestone2_prerequisite.py" in m2


def test_missing_milestone2_acceptance_suite_fails_closed() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "checks/vpro/milestone_check.py",
            "suite",
            "--id",
            "m2-runtime-parity",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed.returncode == 2
    assert "BLOCKED: externally authored acceptance paths are missing" in completed.stdout


def test_missing_distributed_evidence_evaluator_fails_closed() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "checks/vpro/milestone_check.py",
            "evaluator-guard",
            "--milestone",
            "2",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed.returncode == 1
    assert "Milestone 2 authoritative evidence evaluator is missing" in completed.stdout


def test_handwritten_prerequisite_is_not_accepted_without_an_external_verifier(
    tmp_path: Path,
    monkeypatch,
) -> None:
    adapter = _adapter()
    project = tmp_path / "project"
    receipt = project / "milestones/prerequisites/milestone1-completion.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {
                "milestone": 1,
                "claim": "MILESTONE_COMPLETE",
                "completion_digest": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(adapter, "PROJECT_ROOT", project)
    monkeypatch.setitem(
        adapter.PREREQUISITE_VERIFIER_PATHS,
        2,
        project / "checks/vpro/milestone2_prerequisite.py",
    )

    with pytest.raises(RuntimeError, match="prerequisite verifier is missing"):
        adapter._verified_prerequisite(
            2,
            "milestones/prerequisites/milestone1-completion.json",
        )


def test_authoritative_safety_policy_does_not_trust_the_product_scanner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    adapter = _adapter()
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "scripts").mkdir()
    (project / "src/unsafe.py").write_text("sudo = True\n", encoding="utf-8")
    (project / "scripts/safety_scan.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    monkeypatch.setattr(adapter, "PROJECT_ROOT", project)

    assert adapter._static_safety() == 1


def test_suite_child_ignores_worker_sitecustomize_and_root_conftest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    adapter = _adapter()
    project = tmp_path / "project"
    source = project / "src"
    test_path = project / "tests/probe/test_fail.py"
    source.mkdir(parents=True)
    test_path.parent.mkdir(parents=True)
    (source / "sitecustomize.py").write_text("import os\nos._exit(0)\n", encoding="utf-8")
    (project / "conftest.py").write_text(
        "import os\ndef pytest_sessionstart(session): os._exit(0)\n",
        encoding="utf-8",
    )
    test_path.write_text("def test_real_result(): assert False\n", encoding="utf-8")
    monkeypatch.setattr(adapter, "PROJECT_ROOT", project)
    monkeypatch.setattr(adapter, "SOURCE_ROOT", source)
    monkeypatch.setitem(adapter.SUITES, "isolation-probe", ("tests/probe/test_fail.py",))
    pytest_executable = _isolated_pytest_executable(tmp_path)
    monkeypatch.setenv(
        "VPRO_SEALED_TOOLS_JSON",
        json.dumps({"pytest": str(pytest_executable)}),
    )

    assert adapter._suite("isolation-probe") == 1


def test_authoritative_suite_rejects_skipped_required_tests(
    tmp_path: Path,
    monkeypatch,
    capfd,
) -> None:
    adapter = _adapter()
    project = tmp_path / "project"
    source = project / "src"
    test_path = project / "tests/probe/test_skip.py"
    source.mkdir(parents=True)
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "import pytest\ndef test_required_behavior(): pytest.skip('sandbox denied it')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(adapter, "PROJECT_ROOT", project)
    monkeypatch.setattr(adapter, "SOURCE_ROOT", source)
    monkeypatch.setitem(adapter.SUITES, "skip-probe", ("tests/probe/test_skip.py",))
    pytest_executable = _isolated_pytest_executable(tmp_path)
    monkeypatch.setenv(
        "VPRO_SEALED_TOOLS_JSON",
        json.dumps({"pytest": str(pytest_executable)}),
    )

    assert adapter._suite("skip-probe") == 1
    assert "FAIL: authoritative acceptance skipped 1 required test(s)" in capfd.readouterr().out


def test_milestone1_replaces_sandbox_skips_with_external_authority(monkeypatch) -> None:
    adapter = _adapter()
    bundle = load_bundle(
        BUNDLE_ROOT / "milestone1.bundle.json",
        project_root=PROJECT_ROOT,
    )
    replacement = "tests/vpro_milestones/test_milestone1_sandbox_network_proxy.py"

    assert replacement in adapter.SUITES["m1-runtime"]
    assert replacement in bundle.check("m1-runtime-safety-contract").inputs
    assert "tests/fault/test_network_proxy.py" not in adapter.SUITES["m1-compatibility"]
    captured: list[str] = []
    monkeypatch.setattr(adapter, "_pytest", lambda *arguments: captured.extend(arguments) or 0)
    assert adapter._closure() == 0
    assert "--ignore=tests/fault/test_network_proxy.py" in captured


def test_bare_pass_evaluator_decision_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    adapter = _adapter()
    evidence = tmp_path / "evidence"
    capture = evidence / "m1/scale-50/capture"
    capture.mkdir(parents=True)
    (capture / "raw.json").write_text("{}\n", encoding="utf-8")
    for name, value in {
        "VPRO_EVIDENCE_ROOT": str(evidence),
        "VPRO_PRODUCT_DIGEST": "a" * 64,
        "VPRO_RUN_ID": "run-1",
        "VPRO_FRAMEWORK_DIGEST": "b" * 64,
        "VPRO_BUNDLE_DIGEST": "c" * 64,
    }.items():
        monkeypatch.setenv(name, value)

    class BarePass:
        @staticmethod
        def evaluate(**kwargs):
            return {"status": "PASS"}

    monkeypatch.setattr(adapter, "_evaluator", lambda milestone: BarePass)

    with pytest.raises(RuntimeError, match="decision schema_version"):
        adapter._admission(
            1,
            50,
            "m1/scale-50/capture",
            "m1/scale-50/admission",
            None,
            None,
        )
    assert not (evidence / "m1/scale-50/admission").exists()


def test_prior_scale_decision_is_canonical_and_bound_to_product(
    tmp_path: Path,
    monkeypatch,
) -> None:
    adapter = _adapter()
    root = tmp_path / "evidence"
    prior = root / "m2/scale-50/admission"
    prior.mkdir(parents=True)
    product_digest = "a" * 64
    decision = {
        "schema_version": "vpro-milestone-admission-decision-v1",
        "milestone": 2,
        "scale": 50,
        "status": "PASS",
        "errors": [],
        "product_digest": product_digest,
        "capture_admission_digest": "b" * 64,
        "prior_decision_digest": None,
    }
    decision["decision_digest"] = adapter._canonical_digest(decision)
    (prior / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
    monkeypatch.setenv("VPRO_EVIDENCE_ROOT", str(root))

    assert adapter._prior(
        "m2/scale-50/admission",
        milestone=2,
        scale=200,
        product_digest=product_digest,
    )["scale"] == 50

    decision["product_digest"] = "c" * 64
    decision.pop("decision_digest")
    decision["decision_digest"] = adapter._canonical_digest(decision)
    (prior / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
    with pytest.raises(RuntimeError, match="another product digest"):
        adapter._prior(
            "m2/scale-50/admission",
            milestone=2,
            scale=200,
            product_digest=product_digest,
        )
