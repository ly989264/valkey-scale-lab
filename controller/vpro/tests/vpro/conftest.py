from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from valkey_scale_lab.vpro.integrity import FrameworkRelease
from valkey_scale_lab.vpro.runner import ProgramRunner
from valkey_scale_lab.vpro.service import VProController


TEST_STATE_KEY = b"vpro-test-state-seal-key-32-bytes-minimum"
TEST_APPROVAL_KEY = b"vpro-test-approval-key-32-bytes-minimum"


def _check(
    check_id: str,
    *,
    argv: list[str] | None = None,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    authority: str = "bundle",
    tier: str = "cheap",
    capabilities: list[str] | None = None,
    cache: str = "by_input_digest",
    mode: str = "standard",
) -> dict:
    return {
        "id": check_id,
        "tier": tier,
        "argv": argv or ["python3", "acceptance/pass.py"],
        "cwd": ".",
        "timeout_seconds": 30,
        "inputs": inputs or ["acceptance/pass.py"],
        "outputs": outputs or [],
        "authority": authority,
        "capabilities": capabilities or [],
        "cache": cache,
        "mode": mode,
    }


def _base_bundle() -> dict:
    return {
        "schema_version": "vpro-bundle-v1",
        "milestone": {
            "id": "SyntheticDelivery",
            "version": "1.0.0",
            "title": "Deliver a synthetic artifact",
            "goal": "Produce a checked local artifact without domain-specific controller behavior.",
        },
        "clauses": [{"id": "ArtifactExists", "text": "The requested artifact exists and passes acceptance."}],
        "tiers": [{"id": "cheap", "rank": 0, "cost": "cheap", "reviewer_admissible": True}],
        "checks": [
            _check("common"),
            _check("objective-check", inputs=["acceptance/pass.py", "product/work.txt"]),
            _check("closure", inputs=["acceptance/pass.py", "product"]),
            _check("evaluator-guard", inputs=["acceptance/pass.py", "evaluator/evaluator.py"]),
        ],
        "objectives": [
            {
                "id": "CreateArtifact",
                "title": "Create the artifact",
                "depends_on": [],
                "clause_ids": ["ArtifactExists"],
                "check_ids": ["objective-check"],
                "context_paths": ["product"],
                "worker_write_paths": ["product/work.txt"],
                "required_for_milestone": True,
            }
        ],
        "profiles": [
            {
                "id": "complete",
                "objective_ids": ["CreateArtifact"],
                "include_dependency_closure": True,
                "gate_ids": [],
                "claim": "MILESTONE_COMPLETE",
            }
        ],
        "gates": [],
        "acceptance": {
            "objective_rule": "CURRENT_PROGRAM_PASS_AND_BOUNDED_REVIEW",
            "milestone_rule": "ALL_SELECTED_REQUIRED_OBJECTIVES_GATES_AND_CLOSURE_CURRENT",
            "common_check_ids": ["common"],
            "closure_check_ids": ["closure"],
            "evaluator_guard_check_ids": ["evaluator-guard"],
            "max_attempts": 3,
            "stagnation_limit": 2,
            "max_replans": 1,
            "max_review_rounds": 2,
            "max_new_gaps_per_review": 1,
            "max_context_bytes": 16000,
            "failure_excerpt_bytes": 1000,
            "cache_unchanged_results": True,
            "max_expensive_runs_per_input": 1,
        },
        "integrity": {
            "product_roots": ["product"],
            "evaluator_paths": ["evaluator/evaluator.py"],
            "evaluator_repair_paths": ["evaluator"],
            "authoritative_check_paths": ["acceptance"],
            "evidence_roots": ["evidence"],
            "allowed_tools": ["python3"],
        },
    }


def _with_evidence_gate(bundle: dict) -> dict:
    bundle = copy.deepcopy(bundle)
    bundle["tiers"].append(
        {"id": "operator", "rank": 1, "cost": "operator", "reviewer_admissible": False}
    )
    bundle["checks"].extend(
        [
            _check("preflight"),
            _check(
                "capture",
                argv=["python3", "acceptance/capture.py"],
                inputs=["acceptance/capture.py", "product/work.txt"],
                outputs=["evidence/capture.json"],
                tier="operator",
                capabilities=["container"],
                cache="never",
                mode="capture",
            ),
            _check(
                "admission",
                argv=["python3", "acceptance/admit.py"],
                inputs=["acceptance/admit.py", "evaluator/evaluator.py", "evidence/capture.json"],
                outputs=["evidence/admission.json"],
                authority="evaluator",
                mode="admission",
            ),
        ]
    )
    bundle["gates"] = [
        {
            "id": "release-gate",
            "kind": "evidence",
            "after_objective_ids": ["CreateArtifact"],
            "preflight_check_ids": ["preflight"],
            "capture_check_id": "capture",
            "admission_check_ids": ["admission"],
            "operator_approval_required": True,
            "required_for_milestone": True,
        }
    ]
    bundle["profiles"][0]["gate_ids"] = ["release-gate"]
    return bundle


@pytest.fixture
def vpro_project(tmp_path: Path) -> SimpleNamespace:
    workspace = tmp_path / "worker"
    project = workspace / "project"
    (project / "acceptance").mkdir(parents=True)
    (project / "evaluator").mkdir()
    (project / "product").mkdir()
    (project / "acceptance/pass.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (project / "acceptance/fail.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    (project / "acceptance/capture.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "root = Path(os.environ['VPRO_EVIDENCE_ROOT'])\n"
        "root.mkdir(parents=True, exist_ok=True)\n"
        "(root / 'capture.json').write_text('{\"captured\": true}\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (project / "acceptance/admit.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "root = Path(os.environ['VPRO_EVIDENCE_ROOT'])\n"
        "if not (root / 'capture.json').is_file():\n"
        "    raise SystemExit(1)\n"
        "(root / 'admission.json').write_text('{\"status\": \"PASS\"}\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (project / "evaluator/evaluator.py").write_text("EVALUATOR_VERSION = 1\n", encoding="utf-8")
    (project / "product/fail.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    (project / "product/work.txt").write_text("ready\n", encoding="utf-8")
    operator = tmp_path / "operator"
    return SimpleNamespace(
        root=project,
        workspace=workspace,
        operator=operator,
        state_root=operator / "runs" / "run-1",
    )


@pytest.fixture
def bundle_factory():
    def factory(*, evidence_gate: bool = False) -> dict:
        bundle = _base_bundle()
        return _with_evidence_gate(bundle) if evidence_gate else bundle

    return factory


@pytest.fixture
def controller_factory(vpro_project: SimpleNamespace, bundle_factory, monkeypatch):
    sandbox_seal = {
        "backend": "test",
        "entrypoint": "/sealed/test-sandbox",
        "path": "/sealed/test-sandbox",
        "sha256": "0" * 64,
    }
    monkeypatch.setattr(ProgramRunner, "seal_sandbox", staticmethod(lambda **kwargs: sandbox_seal))
    monkeypatch.setattr(ProgramRunner, "verify_sandbox_seal", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(
        ProgramRunner,
        "_sandboxed_command",
        lambda self, command, **kwargs: command,
    )

    def factory(
        *,
        evidence_gate: bool = False,
        bundle: dict | None = None,
        protected_paths: tuple[str, ...] = (),
        framework_root: Path | None = None,
        bundle_path: Path | None = None,
        state_root: Path | None = None,
    ) -> tuple[VProController, Path, dict]:
        raw = copy.deepcopy(bundle) if bundle is not None else bundle_factory(evidence_gate=evidence_gate)
        selected_bundle_path = bundle_path or vpro_project.operator / "bundles" / "bundle.json"
        selected_bundle_path.parent.mkdir(parents=True, exist_ok=True)
        selected_bundle_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        framework_root = framework_root or vpro_project.operator / "framework"
        release = FrameworkRelease(
            version="1.0.0",
            digest="f" * 64,
            root=framework_root,
            manifest_path=framework_root / "codex/vpro/framework_manifest.json",
            protected_paths=protected_paths,
        )
        controller = VProController(
            project_root=vpro_project.root,
            workspace_root=vpro_project.workspace,
            bundle_path=selected_bundle_path,
            profile_id="complete",
            state_root=state_root or vpro_project.state_root,
            release=release,
            state_seal_key=TEST_STATE_KEY,
            approval_key=TEST_APPROVAL_KEY,
        )
        return controller, selected_bundle_path, raw

    return factory
