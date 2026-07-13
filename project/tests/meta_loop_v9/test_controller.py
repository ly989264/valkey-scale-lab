from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab.meta_loop_v9.controller import MetaLoopV9Controller
from valkey_scale_lab.meta_loop_v9.migration import V9MigrationReceipt


O1 = "O1_GOAL_SCHEDULER_AND_CONTRACTS"
O2 = "O2_CANONICAL_SCENARIO_DEFINITION"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _check(check_id: str) -> dict:
    return {"id": check_id, "level": 1, "command": ["python3", "pass.py"], "timeout_seconds": 20, "inputs": ["pass.py"]}


def _control() -> dict:
    scope = {
        "trigger_nodes": {"min": 30, "max": 2000, "exact": True},
        "required_real_scales": [50, 200],
        "supported_not_gated_scales": [30, 100],
        "normal_development_max_nodes": 100,
        "required_200_bounded_exception": True,
        "above_200": {
            "automatic": False,
            "operator_opt_in": True,
            "resource_preflight": True,
            "cost_acknowledgement": True,
            "silent_downscale": False,
        },
    }
    policy = {
        "max_attempts_per_objective": 3,
        "stagnation_limit": 2,
        "max_replans_per_objective": 1,
        "max_review_rounds_per_objective": 2,
        "max_new_gaps_per_review": 1,
        "failure_excerpt_bytes": 240,
        "max_context_bytes": 4000,
        "expensive_levels": [3, 4],
        "max_expensive_runs_per_input": 1,
    }
    return {
        "schema_version": "v9",
        "goal_id": "test-v9",
        "goal": "test",
        "scope_freeze": scope,
        "integrity": {
            "kernel_manifest": "kernel.json",
            "evaluator_paths": ["evaluator.py"],
            "evaluator_repair_allowed_paths": ["evaluator.py"],
            "product_roots": ["src"],
            "product_excludes": ["src/valkey_scale_lab/goal", "src/valkey_scale_lab/meta_loop", "scripts/meta_m1_"],
        },
        "controller_policy": policy,
        "common_checks": [_check("common")],
        "closure_checks": [_check("closure")],
        "evaluator_guard_checks": [_check("guard")],
        "objectives": [
            {"id": O1, "title": "First", "depends_on": [], "clauses": ["first"], "context_paths": ["src"], "checks": [_check("first")]},
            {"id": O2, "title": "Second", "depends_on": [O1], "clauses": ["second"], "context_paths": ["src"], "checks": [_check("second")]},
        ],
    }


def _receipt(*args) -> V9MigrationReceipt:
    values = [chr(ord("a") + index) * 64 for index in range(13)]
    return V9MigrationReceipt(
        source_state_path="v8.json",
        source_state_sha256=values[0],
        source_events_sha256=values[1],
        source_control_sha256=values[2],
        source_kernel_sha256=values[3],
        source_evaluator_sha256=values[4],
        source_last_event_hash=values[5],
        source_active_gap_sha256=values[6],
        source_review_check_id="old-check",
        source_review_test_sha256=values[7],
        source_retry_test_sha256=values[8],
        source_reproduction_log_sha256=values[9],
        source_v7_v6_receipt_sha256=values[10],
        successor_check_id="new-check",
        successor_test_sha256=values[11],
    )


def _controller(tmp_path: Path) -> MetaLoopV9Controller:
    project = tmp_path / "project"
    _write(project / "pass.py", "raise SystemExit(0)\n")
    _write(project / "evaluator.py", "VERSION = 1\n")
    _write(project / "kernel.py", "VERSION = 1\n")
    _write(project / "kernel.json", json.dumps({"schema_version": "meta-loop-v9-kernel-manifest-v1", "files": ["kernel.py"]}))
    _write(project / "control.json", json.dumps(_control()))
    controller = MetaLoopV9Controller(
        project_root=project,
        workspace_root=tmp_path,
        control_path=project / "control.json",
        state_root=tmp_path / "state-root",
        migration_verifier=_receipt,
    )
    controller.migrate_v8(tmp_path / "v8.json")
    return controller


def test_migration_preserves_review_budget_without_importing_pass_or_checks(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    state = controller.store.load()
    progress = state["objectives"][O1]
    assert state["cache"] == {}
    assert state["active_work_item"] is None
    assert (progress["status"], progress["attempts"], progress["replans"], progress["review_rounds"]) == ("REVERIFY", 0, 0, 2)
    assert progress["added_checks"] == []
    assert progress["check_anchors"] == {}
    assert progress["active_gap"] is None
    assert progress["completion_reason"] is None


def test_passing_verify_exhausts_review_budget_and_advances_to_o2(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    verify = controller.next_work_item()
    assert verify["type"] == "VERIFY"
    assert verify["objective_id"] == O1
    assert controller.evaluate_active()["status"] == "PASS"
    next_item = controller.next_work_item()
    assert next_item["type"] == "WORK"
    assert next_item["objective_id"] == O2
    progress = controller.store.load()["objectives"][O1]
    assert progress["status"] == "COMPLETE"
    assert progress["completion_reason"] == "PROGRAM_PASS_AND_REVIEW_BUDGET_EXHAUSTED"
