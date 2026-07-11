from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from valkey_scale_lab.meta_loop.contracts import ContractError, validate_control_block
from valkey_scale_lab.meta_loop.controller import MetaLoopController, MetaLoopError
from valkey_scale_lab.meta_loop.runner import ProgramRunner


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_control(project: Path) -> Path:
    control = {
        "schema_version": "v2",
        "goal_id": "test-goal",
        "goal": "test",
        "scope_freeze": {
            "source": "test",
            "trigger_nodes": {"min": 30, "max": 2000, "exact": True},
            "required_real_scales": [50, 200],
            "supported_not_gated_scales": [30, 100],
            "above_200": {
                "automatic": False,
                "operator_opt_in": True,
                "resource_preflight": True,
                "cost_acknowledgement": True,
                "silent_downscale": False,
            },
        },
        "controller_policy": {
            "max_attempts_per_objective": 3,
            "stagnation_limit": 2,
            "max_replans_per_objective": 1,
            "max_review_rounds_per_objective": 2,
            "max_new_gaps_per_review": 1,
            "failure_excerpt_bytes": 500,
            "max_context_bytes": 12000,
            "cache_unchanged_results": True,
            "expensive_levels": [3, 4],
            "max_expensive_runs_per_input": 1,
        },
        "levels": {str(i): f"level {i}" for i in range(5)},
        "common_checks": [check("common", "scripts/pass.py", 0)],
        "objectives": [
            {
                "id": "O1",
                "title": "one",
                "depends_on": [],
                "clauses": ["clause one"],
                "context_paths": ["src"],
                "checks": [check("objective-one", "scripts/objective.py", 1)],
            },
            {
                "id": "O2",
                "title": "two",
                "depends_on": ["O1"],
                "clauses": ["clause two"],
                "context_paths": ["src"],
                "checks": [check("objective-two", "scripts/pass.py", 1)],
            },
        ],
    }
    path = project / "codex" / "meta_m1" / "control_block.json"
    write_json(path, control)
    return path


def check(check_id: str, path: str, level: int) -> dict:
    return {
        "id": check_id,
        "level": level,
        "command": ["python3", path],
        "timeout_seconds": 20,
        "inputs": [path],
    }


def make_controller(tmp_path: Path, objective_exit: int = 0) -> tuple[MetaLoopController, Path]:
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    (project / "src").mkdir()
    (scripts / "pass.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (scripts / "objective.py").write_text(f"raise SystemExit({objective_exit})\n", encoding="utf-8")
    (scripts / "meta_m1_evidence_gate.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    control_path = make_control(project)
    controller = MetaLoopController(project, control_path, tmp_path / "state", tmp_path)
    return controller, project


def test_control_contract_freezes_scale_semantics(tmp_path: Path) -> None:
    _, project = make_controller(tmp_path)
    control = json.loads((project / "codex/meta_m1/control_block.json").read_text())
    control["scope_freeze"]["required_real_scales"] = [30, 50, 100, 200]
    with pytest.raises(ContractError, match="exactly"):
        validate_control_block(control)


def test_next_is_idempotent_and_context_is_compact(tmp_path: Path) -> None:
    controller, _ = make_controller(tmp_path)
    controller.bootstrap()
    first = controller.next_work_item()
    second = controller.next_work_item()
    assert first == second
    assert first["type"] == "WORK"
    assert len(json.dumps(first).encode()) < 12000


def test_program_pass_requires_reviewer_before_completion(tmp_path: Path) -> None:
    controller, _ = make_controller(tmp_path)
    controller.bootstrap()
    controller.next_work_item()
    assert controller.evaluate_active()["status"] == "PASS"
    review = controller.next_work_item()
    assert review["type"] == "REVIEW_ACCEPTANCE"
    status = controller.submit_review({"work_item_id": review["work_item_id"], "decision": "NO_GAP"})
    assert status["objectives"][0]["status"] == "COMPLETE"
    assert controller.next_work_item()["objective_id"] == "O2"


def test_review_cannot_close_stale_program_pass(tmp_path: Path) -> None:
    controller, project = make_controller(tmp_path)
    controller.bootstrap()
    controller.next_work_item()
    controller.evaluate_active()
    review = controller.next_work_item()
    (project / "scripts/objective.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    result = controller.submit_review({"work_item_id": review["work_item_id"], "decision": "NO_GAP"})
    assert result["status"] == "STALE_PROGRAM_RESULT"
    assert controller.next_work_item()["type"] == "WORK"


def test_unchanged_failure_is_cached_and_routes_to_replan(tmp_path: Path) -> None:
    controller, _ = make_controller(tmp_path, objective_exit=7)
    controller.bootstrap()
    results = []
    for _ in range(3):
        controller.next_work_item()
        results.append(controller.evaluate_active())
    assert results[0]["failed_check"]["cached"] is False
    assert results[1]["failed_check"]["cached"] is True
    assert results[2]["failed_check"]["cached"] is True
    assert controller.next_work_item()["type"] == "REVIEW_REPLAN"


def test_check_that_creates_evidence_is_cached_by_post_run_inputs(tmp_path: Path) -> None:
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    producer = scripts / "producer.py"
    producer.write_text(
        "from pathlib import Path\nPath('evidence').mkdir(exist_ok=True)\nPath('evidence/result.json').write_text('{}')\n",
        encoding="utf-8",
    )
    runner = ProgramRunner(project, tmp_path, tmp_path / "logs", 200)
    cache: dict = {}
    item = {"id": "producer", "level": 3, "command": ["python3", "scripts/producer.py"], "timeout_seconds": 20, "inputs": ["scripts/producer.py", "evidence"]}
    assert runner.run(item, cache)["cached"] is False
    assert runner.run(item, cache)["cached"] is True


def test_replan_resets_attempt_budget_once(tmp_path: Path) -> None:
    controller, _ = make_controller(tmp_path, objective_exit=4)
    controller.bootstrap()
    for _ in range(3):
        controller.next_work_item()
        controller.evaluate_active()
    review = controller.next_work_item()
    status = controller.submit_review(
        {"work_item_id": review["work_item_id"], "diagnosis": "wrong layer", "recommended_focus": ["planner boundary"]}
    )
    assert status["objectives"][0]["replans"] == 1
    assert controller.next_work_item()["attempt"] == 1


def test_reviewer_gap_must_be_in_scope_and_failing(tmp_path: Path) -> None:
    controller, project = make_controller(tmp_path)
    controller.bootstrap()
    controller.next_work_item()
    controller.evaluate_active()
    review = controller.next_work_item()
    bad = project / "scripts" / "review_gap.py"
    bad.write_text("raise SystemExit(1)\n", encoding="utf-8")
    report = {
        "work_item_id": review["work_item_id"],
        "decision": "GAP",
        "contract_clause": "not frozen",
        "finding": "concrete bug",
        "program_check": check("review-gap", "scripts/review_gap.py", 1),
    }
    with pytest.raises(MetaLoopError, match="frozen contract clause"):
        controller.submit_review(report)


def test_reviewer_gap_becomes_program_check(tmp_path: Path) -> None:
    controller, project = make_controller(tmp_path)
    controller.bootstrap()
    controller.next_work_item()
    controller.evaluate_active()
    review = controller.next_work_item()
    gap = project / "scripts" / "review_gap.py"
    gap.write_text("raise SystemExit(1)\n", encoding="utf-8")
    status = controller.submit_review(
        {
            "work_item_id": review["work_item_id"],
            "decision": "GAP",
            "contract_clause": "clause one",
            "finding": "one observable is not checked",
            "program_check": check("review-gap", "scripts/review_gap.py", 1),
        }
    )
    assert status["objectives"][0]["status"] == "PENDING"
    gap.write_text("raise SystemExit(0)\n", encoding="utf-8")
    controller.next_work_item()
    assert controller.evaluate_active()["status"] == "PASS"


def test_reviewer_cannot_claim_a_gap_that_already_passes(tmp_path: Path) -> None:
    controller, _ = make_controller(tmp_path)
    controller.bootstrap()
    controller.next_work_item()
    controller.evaluate_active()
    review = controller.next_work_item()
    with pytest.raises(MetaLoopError, match="not reproduced"):
        controller.submit_review(
            {
                "work_item_id": review["work_item_id"],
                "decision": "GAP",
                "contract_clause": "clause one",
                "finding": "unsupported assertion",
                "program_check": check("false-gap", "scripts/pass.py", 1),
            }
        )


def test_harness_changes_after_bootstrap_are_detected(tmp_path: Path) -> None:
    controller, project = make_controller(tmp_path)
    controller.bootstrap()
    (project / "scripts/meta_m1_evidence_gate.py").write_text("raise SystemExit(2)\n", encoding="utf-8")
    assert controller.doctor()["status"] == "FAIL"
    with pytest.raises(MetaLoopError, match="evaluator changed"):
        controller.next_work_item()


def load_evidence_gate():
    path = Path(__file__).resolve().parents[2] / "scripts" / "meta_m1_evidence_gate.py"
    spec = importlib.util.spec_from_file_location("meta_m1_evidence_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_scale_evidence_gate_rejects_wrong_observed_nodes(tmp_path: Path) -> None:
    gate = load_evidence_gate()
    base = tmp_path / "scale-50"
    base.mkdir()
    write_json(base / "admission.json", {"observed_nodes": 49})
    errors = gate.evaluate(50, tmp_path)
    assert any("observed_nodes" in error for error in errors)


def test_exact_scale_evidence_gate_accepts_complete_hashed_bundle(tmp_path: Path) -> None:
    gate = load_evidence_gate()
    base = tmp_path / "scale-50"
    base.mkdir()
    artifacts = []
    for kind in sorted(gate.REQUIRED_ARTIFACT_KINDS):
        path = base / f"{kind}.json"
        path.write_text('{"status":"PASS"}\n', encoding="utf-8")
        artifacts.append({"kind": kind, "path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    admission = {
        "schema_version": "meta-m1-admission-v1",
        "execution_kind": "REAL_VALKEY_EXACT_SCALE",
        "requested_nodes": 50,
        "observed_nodes": 50,
        "status": "PASS",
        "run_id": "real-50",
        "source_commit": "a" * 40,
        "source_tree_digest": gate.source_tree_digest(),
        "valkey_versions": ["9.1.0"],
        "resource_preflight": {"status": "PASS", "requested_nodes": 50},
        "independent_probe": {"status": "PASS", "observed_nodes": 50, "cluster_state": "ok", "slots_assigned": 16384, "slots_ok": 16384, "endpoint_count": 2},
        "lifecycle_steps": [{"id": item, "status": "PASS", "duration_ms": 1} for item in gate.REQUIRED_LIFECYCLE],
        "scenario_matrix": [{"id": item, "status": "REAL_PASS"} for item in gate.REQUIRED_SCENARIOS],
        "cleanup": {"status": "PASS", "residual_owned_resources": 0},
        "artifacts": artifacts,
    }
    write_json(base / "admission.json", admission)
    assert gate.evaluate(50, tmp_path) == []
