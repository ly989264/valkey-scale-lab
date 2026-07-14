from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = REPOSITORY_ROOT / "project"
INTEGRATION_ROOT = REPOSITORY_ROOT / "controller/integrations/valkey-scale-lab"


def _compiler():
    spec = importlib.util.spec_from_file_location(
        "valkey_controller_compiler", INTEGRATION_ROOT / "compile_contract.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPILER = _compiler()


def test_compiled_milestone_preserves_product_goal_conditions_and_evidence() -> None:
    source = json.loads((PROJECT_ROOT / "milestones/m1/milestone.json").read_text())
    compiled = COMPILER.compile_contract("m1")
    assert set(compiled) == {
        "schema_version",
        "milestone",
        "success_conditions",
        "evidence_requirements",
        "termination",
    }
    assert compiled["milestone"]["goal"] == source["milestone"]["final_goal"]
    assert [item["id"] for item in compiled["success_conditions"]] == [
        item["id"] for item in source["success_conditions"]
    ]
    compiled_evidence_ids = {item["id"] for item in compiled["evidence_requirements"]}
    source_suite_ids = {
        suite_id
        for condition in source["success_conditions"]
        for suite_id in condition["suite_ids"]
    }
    assert {f"verification.{suite_id}" for suite_id in source_suite_ids}.issubset(
        compiled_evidence_ids
    )
    assert {
        f"evidence.{item['id']}" for item in source["real_evidence_requirements"]
    }.issubset(compiled_evidence_ids)
    assert all(condition["evidence_requirement_ids"] for condition in compiled["success_conditions"])
    assert "evaluators" not in compiled
    assert "safety" not in compiled
    assert "resource_budget" not in compiled


def test_compiled_milestone_is_accepted_by_the_minimal_parser(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(REPOSITORY_ROOT / "controller/src"))
    from controller.contracts import parse_milestone

    parsed = parse_milestone(COMPILER.compile_contract("m1"))
    assert parsed.id == "m1"
    assert len(parsed.success_conditions) == 9
    assert len(parsed.evidence_requirements) == 9
    real = [item for item in parsed.evidence_requirements if item.kind == "REAL"]
    assert {item.parameters["nodes"] for item in real} == {50, 200}
    assert all(item.freshness_seconds == 86400 for item in parsed.evidence_requirements)


def test_compiler_rejects_weakened_real_evidence(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(PROJECT_ROOT / "milestones", project / "milestones")
    shutil.copytree(PROJECT_ROOT / "verification", project / "verification")
    path = project / "milestones/m1/milestone.json"
    source = json.loads(path.read_text())
    source["real_evidence_requirements"][0]["substitution_policy"] = "ALLOWED"
    path.write_text(json.dumps(source), encoding="utf-8")
    try:
        COMPILER.compile_contract("m1", project_root=project)
    except COMPILER.CompileError as exc:
        assert "weakens real evidence" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("weakened evidence was accepted")


def test_run_policy_separates_worker_paths_from_acceptance_paths() -> None:
    policy = json.loads((INTEGRATION_ROOT / "policy.json").read_text())
    assert policy["schema_version"] == "valkey-controller-run-policy-v1"
    assert set(policy["allowed_write_paths"]).isdisjoint(policy["protected_paths"])
    assert {"milestones", "verification", "tests"}.issubset(policy["protected_paths"])
    assert "src/valkey_scale_lab/scenarios/definitions" in policy["protected_paths"]
    assert "capability_limits" not in policy


def test_verification_uses_the_product_digest_contract(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from valkey_scale_lab.gates.real import product_tree_digest

    runner_spec = importlib.util.spec_from_file_location(
        "verification_digest_runner", INTEGRATION_ROOT / "tools/run_verification.py"
    )
    assert runner_spec is not None and runner_spec.loader is not None
    runner = importlib.util.module_from_spec(runner_spec)
    runner_spec.loader.exec_module(runner)
    assert runner.product_tree_digest(PROJECT_ROOT) == product_tree_digest(PROJECT_ROOT)


def test_compiler_cli_writes_the_same_minimal_document(tmp_path: Path) -> None:
    output = tmp_path / "m1.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(INTEGRATION_ROOT / "compile_contract.py"),
            "--milestone",
            "m1",
            "--output",
            str(output),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout
    assert json.loads(output.read_text()) == COMPILER.compile_contract("m1")


def test_full_valkey_evaluator_runs_directly_through_controller(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    product = workspace / "product"
    (product / "src").mkdir(parents=True)
    (product / "src/work.txt").write_text("ready\n", encoding="utf-8")
    milestone = {
        "schema_version": "valkey-milestone-v2",
        "milestone": {"id": "m1", "version": "1.0.0", "title": "sample", "final_goal": "sample"},
        "prerequisite_milestone_ids": [],
        "success_conditions": [
            {
                "id": "sample.condition",
                "statement": "sample passes",
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
                "argv": [
                    "python3",
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "tests/test_sample.py",
                ],
                "timeout_seconds": 60,
                "capabilities": [],
                "outputs": [],
                "skip_policy": "FAIL",
            }
        ],
    }
    milestone_path = product / "milestones/m1/milestone.json"
    catalog_path = product / "verification/catalog.json"
    milestone_path.parent.mkdir(parents=True)
    catalog_path.parent.mkdir(parents=True)
    milestone_path.write_text(json.dumps(milestone), encoding="utf-8")
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    shutil.copy2(PROJECT_ROOT / "verification/run.py", product / "verification/run.py")
    (product / "tests").mkdir()
    (product / "tests/test_sample.py").write_text(
        "def test_sample():\n    assert True\n", encoding="utf-8"
    )
    compiled_path = tmp_path / "compiled.json"
    compiled_path.write_text(
        json.dumps(COMPILER.compile_contract("m1", project_root=product)), encoding="utf-8"
    )

    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    subprocess.run(["git", "-C", str(workspace), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "initial",
        ],
        check=True,
    )

    monkeypatch.syspath_prepend(str(REPOSITORY_ROOT / "controller/src"))
    from controller import Controller, TerminalStatus

    spec = importlib.util.spec_from_file_location(
        "full_valkey_evaluator", INTEGRATION_ROOT / "full_evaluator.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluator = module.ValkeyEvaluator(evidence_root=tmp_path / "evidence", run_id="run-1")
    controller = Controller(
        milestone_path=compiled_path,
        project_root=product,
        allowed_write_paths=("src",),
        protected_paths=("milestones", "verification"),
        evaluator=evaluator,
    )
    result = controller.run(
        lambda context: (_ for _ in ()).throw(AssertionError("Planner must not run")),
        lambda objective, root: None,
    )
    assert result.status is TerminalStatus.SUCCESS
    assert result.goal_state is not None
    assert result.goal_state.evidence_results[0].artifact == "verification/results.json"


def test_prerequisite_builder_consumes_a_real_controller_result(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "product"
    (project / "src").mkdir(parents=True)
    (project / "src/work.txt").write_text("done\n")
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    subprocess.run(["git", "-C", str(workspace), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "initial",
        ],
        check=True,
    )
    compiled_path = tmp_path / "compiled.json"
    compiled_path.write_text(
        json.dumps(
            {
                "schema_version": "controller-milestone-v1",
                "milestone": {"id": "m1", "title": "M1", "goal": "Complete M1."},
                "success_conditions": [
                    {
                        "id": "real.complete",
                        "statement": "Real evidence passes.",
                        "evidence_requirement_ids": ["evidence.local.exact.50"],
                    }
                ],
                "evidence_requirements": [
                    {
                        "id": "evidence.local.exact.50",
                        "statement": "Exact 50-node evidence.",
                        "kind": "REAL",
                        "source_id": "local.exact.50",
                        "freshness_seconds": 60,
                        "provenance_required": True,
                        "substitution_policy": "FORBIDDEN",
                        "parameters": {"nodes": 50},
                    }
                ],
                "termination": {
                    "max_iterations": 1,
                    "max_stagnant_iterations": 1,
                    "max_environment_retries": 1,
                    "max_no_plan_rounds": 1,
                    "max_wall_seconds": 60,
                },
            }
        )
    )
    monkeypatch.syspath_prepend(str(REPOSITORY_ROOT / "controller/src"))
    from controller import Controller, TerminalStatus

    builder_spec = importlib.util.spec_from_file_location(
        "prerequisite_builder", INTEGRATION_ROOT / "tools/build_prerequisite.py"
    )
    assert builder_spec is not None and builder_spec.loader is not None
    builder = importlib.util.module_from_spec(builder_spec)
    builder_spec.loader.exec_module(builder)
    admission = {
        "status": "PASS",
        "requested_nodes": 50,
        "observed_nodes": 50,
        "product_digest": "a" * 64,
        "invocation_run_id": "run-1",
    }
    admission["admission_digest"] = builder.canonical_digest(admission)
    admission_path = tmp_path / "admission.json"
    admission_path.write_text(json.dumps(admission))

    def evaluator(milestone, root):
        return {
            "condition_results": [
                {"id": "real.complete", "status": "PASS", "summary": "accepted"}
            ],
            "evidence_results": [
                {
                    "id": "evidence.local.exact.50",
                    "status": "PASS",
                    "summary": "accepted",
                    "artifact": str(admission_path),
                    "provenance": {
                        "admission_digest": admission["admission_digest"],
                        "product_digest": admission["product_digest"],
                        "run_id": admission["invocation_run_id"],
                        "captured_at_unix": 2_000_000_000,
                    },
                }
            ],
        }

    result = Controller(
        milestone_path=compiled_path,
        project_root=project,
        allowed_write_paths=("src",),
        evaluator=evaluator,
    ).run(lambda context: None, lambda objective, root: None)
    assert result.status is TerminalStatus.SUCCESS
    terminal_path = tmp_path / "terminal.json"
    terminal_path.write_text(json.dumps(result.as_dict()))
    product_milestone_path = tmp_path / "product-milestone.json"
    product_milestone_path.write_text(
        json.dumps(
            {
                "schema_version": "valkey-milestone-v2",
                "milestone": {"id": "m1"},
                "real_evidence_requirements": [
                    {
                        "id": "local.exact.50",
                        "parameters": {"nodes": 50},
                        "promotion_source_id": None,
                    }
                ],
            }
        )
    )
    completion = builder.build(
        milestone_path=product_milestone_path,
        terminal_path=terminal_path,
        final_admission_path=admission_path,
        output_dir=tmp_path / "prerequisite",
    )
    assert completion["terminal_status"] == "SUCCESS"
    assert completion["final_admission_digest"] == admission["admission_digest"]
