from __future__ import annotations

import json
from pathlib import Path

import pytest

from valkey_scale_lab.goal import GoalServiceError
from valkey_scale_lab.meta_loop_v8.controller import MetaLoopV8Controller
from valkey_scale_lab.meta_loop_v8.migration import V8MigrationReceipt


O1 = "O1_GOAL_SCHEDULER_AND_CONTRACTS"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _check(check_id: str) -> dict:
    return {
        "id": check_id,
        "level": 1,
        "command": ["python3", "pass.py"],
        "timeout_seconds": 20,
        "inputs": ["pass.py"],
    }


def _control() -> dict:
    return {
        "schema_version": "v8",
        "goal_id": "test-v8",
        "goal": "test",
        "scope_freeze": {
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
        },
        "integrity": {
            "kernel_manifest": "kernel.json",
            "evaluator_paths": ["evaluator.py"],
            "evaluator_repair_allowed_paths": ["evaluator.py"],
            "product_roots": ["src"],
            "product_excludes": ["src/valkey_scale_lab/goal", "src/valkey_scale_lab/meta_loop", "scripts/meta_m1_"],
        },
        "controller_policy": {
            "max_attempts_per_objective": 3,
            "stagnation_limit": 2,
            "max_replans_per_objective": 1,
            "max_review_rounds_per_objective": 2,
            "max_new_gaps_per_review": 1,
            "failure_excerpt_bytes": 240,
            "max_context_bytes": 4000,
            "expensive_levels": [3, 4],
            "max_expensive_runs_per_input": 1,
        },
        "common_checks": [_check("common")],
        "closure_checks": [_check("closure")],
        "evaluator_guard_checks": [_check("guard")],
        "objectives": [
            {
                "id": O1,
                "title": "Retry accounting",
                "depends_on": [],
                "clauses": ["attempt budget is monotonic"],
                "context_paths": ["src"],
                "checks": [_check("objective")],
            }
        ],
    }


def _receipt(*args) -> V8MigrationReceipt:
    return V8MigrationReceipt(
        source_state_path="v7.json",
        source_state_sha256="a" * 64,
        source_control_sha256="b" * 64,
        source_kernel_sha256="c" * 64,
        source_evaluator_sha256="d" * 64,
        source_last_event_hash="e" * 64,
        source_active_work_sha256="f" * 64,
        source_active_gap_sha256="0" * 64,
        source_review_check_id="old-check",
        source_review_test_sha256="1" * 64,
        source_reproduction_log_sha256="2" * 64,
        source_v6_receipt_sha256="3" * 64,
        successor_check_id="new-check",
        successor_test_sha256="4" * 64,
    )


def _controller(tmp_path: Path) -> MetaLoopV8Controller:
    project = tmp_path / "project"
    _write(project / "pass.py", "raise SystemExit(0)\n")
    _write(project / "evaluator.py", "VERSION = 1\n")
    _write(project / "kernel.py", "VERSION = 1\n")
    _write(project / "tests/retry.py", "VERSION = 1\n")
    _write(project / "kernel.json", json.dumps({"schema_version": "meta-loop-v8-kernel-manifest-v1", "files": ["kernel.py", "tests/retry.py"]}))
    _write(project / "control.json", json.dumps(_control()))
    controller = MetaLoopV8Controller(
        project_root=project,
        workspace_root=tmp_path,
        control_path=project / "control.json",
        state_root=tmp_path / "state-root",
        migration_verifier=_receipt,
    )
    controller.migrate_v7(tmp_path / "v7.json")
    return controller


def _failure(check_id: str, *, level: int = 1) -> dict:
    return {
        "check_id": check_id,
        "level": level,
        "status": "FAIL",
        "cached": False,
        "returncode": 1,
        "timed_out": False,
        "input_digest": check_id,
        "excerpt": check_id,
    }


def _pass(check_id: str, *, level: int = 0) -> dict:
    return {
        "check_id": check_id,
        "level": level,
        "status": "PASS",
        "cached": False,
        "returncode": 0,
        "timed_out": False,
        "input_digest": check_id,
        "excerpt": "",
    }


def test_changing_failure_identity_cannot_reset_objective_retry_budget(tmp_path: Path, monkeypatch) -> None:
    controller = _controller(tmp_path)
    failures = iter(("failure-a", "failure-b", "failure-a"))

    def fail_with_changing_identity(checks, state, goal):
        return [_failure(next(failures))]

    monkeypatch.setattr(controller, "_run_checks", fail_with_changing_identity)
    observed_attempts = []
    assert controller.next_work_item()["type"] == "VERIFY"
    for expected in (1, 2, 3):
        assert controller.evaluate_active()["status"] == "FAIL"
        observed_attempts.append(controller.store.load()["objectives"][O1]["attempts"])
        if expected < 3:
            item = controller.next_work_item()
            assert item["type"] == "WORK"
            assert item["attempt"] == expected + 1
    assert observed_attempts == [1, 2, 3]
    assert controller.next_work_item()["type"] == "REVIEW_REPLAN"


def test_failure_identity_resets_stagnation_only(tmp_path: Path, monkeypatch) -> None:
    controller = _controller(tmp_path)
    results = iter(([_failure("failure-a")], [_failure("failure-a")], [_failure("failure-b")]))
    monkeypatch.setattr(controller, "_run_checks", lambda checks, state, goal: next(results))

    controller.next_work_item()
    controller.evaluate_active()
    controller.next_work_item()
    controller.evaluate_active()
    progress = controller.store.load()["objectives"][O1]
    assert (progress["attempts"], progress["stagnant_attempts"]) == (2, 1)

    controller.next_work_item()
    controller.evaluate_active()
    progress = controller.store.load()["objectives"][O1]
    assert (progress["attempts"], progress["replans"], progress["stagnant_attempts"]) == (3, 0, 0)


def test_same_fingerprint_improved_score_resets_stagnation(tmp_path: Path, monkeypatch) -> None:
    controller = _controller(tmp_path)
    results = iter(
        (
            [_failure("failure-a")],
            [_failure("failure-a")],
            [_pass("earlier"), _failure("failure-a")],
        )
    )
    monkeypatch.setattr(controller, "_run_checks", lambda checks, state, goal: next(results))
    controller.next_work_item()
    controller.evaluate_active()
    controller.next_work_item()
    controller.evaluate_active()
    assert controller.store.load()["objectives"][O1]["stagnant_attempts"] == 1
    controller.next_work_item()
    controller.evaluate_active()
    progress = controller.store.load()["objectives"][O1]
    assert progress["attempts"] == 3
    assert progress["stagnant_attempts"] == 0
    assert progress["best_score"] == 99


def test_v7_gap_migration_preserves_budget_but_imports_no_pass_or_cache(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    state = controller.store.load()
    progress = state["objectives"][O1]
    assert state["cache"] == {}
    assert state["active_work_item"] is None
    assert (progress["status"], progress["attempts"], progress["replans"], progress["review_rounds"]) == ("REVERIFY", 1, 0, 1)
    assert progress["added_checks"] == []
    assert progress["check_anchors"] == {}
    assert progress["active_gap"] is None
    assert progress["completion_reason"] is None
    assert progress["last_result"]["status"] == "MIGRATED_KERNEL_GAP_REVERIFY"


def test_frozen_successor_test_tamper_is_kernel_drift(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    successor = controller.project_root / "tests/retry.py"
    successor.write_text("VERSION = 2\n", encoding="utf-8")
    with pytest.raises(GoalServiceError, match="controller kernel changed"):
        controller.status()
