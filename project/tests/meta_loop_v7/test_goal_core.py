from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from valkey_scale_lab.goal import ContractError, GoalController, GoalServiceError, MigrationReceipt, ProgramRunner, parse_check, parse_goal_definition


SCOPE = {
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
POLICY = {
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


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _check(check_id: str, script: str) -> dict:
    return {
        "id": check_id,
        "level": 1,
        "command": ["python3", script],
        "timeout_seconds": 20,
        "inputs": [script],
    }


def _control(*, first_script: str = "pass.py", second: bool = True) -> dict:
    objectives = [
        {
            "id": "O1",
            "title": "First",
            "depends_on": [],
            "clauses": ["first clause"],
            "context_paths": ["src"],
            "checks": [_check("objective-one", first_script)],
        }
    ]
    if second:
        objectives.append(
            {
                "id": "O2",
                "title": "Second",
                "depends_on": ["O1"],
                "clauses": ["second clause"],
                "context_paths": ["src"],
                "checks": [_check("objective-two", "pass.py")],
            }
        )
    return {
        "schema_version": "v7",
        "goal_id": "test-v7",
        "goal": "test",
        "scope_freeze": json.loads(json.dumps(SCOPE)),
        "integrity": {
            "kernel_manifest": "kernel.json",
            "evaluator_paths": ["evaluator.py"],
            "evaluator_repair_allowed_paths": ["evaluator.py"],
            "product_roots": ["src"],
            "product_excludes": ["src/valkey_scale_lab/goal", "src/valkey_scale_lab/meta_loop", "scripts/meta_m1_"],
        },
        "controller_policy": dict(POLICY),
        "common_checks": [_check("common", "pass.py")],
        "closure_checks": [_check("closure", "pass.py")],
        "evaluator_guard_checks": [_check("guard", "pass.py")],
        "objectives": objectives,
    }


def _receipt(*args) -> MigrationReceipt:
    return MigrationReceipt(
        source_state_path="source.json",
        source_state_sha256="a" * 64,
        source_control_sha256="b" * 64,
        source_kernel_sha256="c" * 64,
        source_evaluator_sha256="d" * 64,
        source_last_event_hash="e" * 64,
        evidence=({"scale": 50, "admission_sha256": "f" * 64}, {"scale": 200, "admission_sha256": "0" * 64}),
    )


def _controller(tmp_path: Path, *, first_script: str = "pass.py", second: bool = True) -> tuple[GoalController, Path]:
    project = tmp_path / "project"
    workspace = tmp_path
    _write(project / "pass.py", "raise SystemExit(0)\n")
    _write(project / "fail.py", "raise SystemExit(1)\n")
    _write(project / "evaluator.py", "VERSION = 1\n")
    _write(project / "kernel.py", "VERSION = 1\n")
    _write(project / "kernel.json", json.dumps({"schema_version": "meta-loop-v7-kernel-manifest-v1", "files": ["kernel.py"]}))
    control_path = project / "control.json"
    _write(control_path, json.dumps(_control(first_script=first_script, second=second)))
    controller = GoalController(
        project_root=project,
        workspace_root=workspace,
        control_path=control_path,
        state_root=tmp_path / "state-root",
        schema_version="v7",
        migration_verifier=_receipt,
    )
    controller.migrate_v6(tmp_path / "source.json")
    return controller, project


def test_typed_contract_rejects_cycles_and_preserves_frozen_scale() -> None:
    raw = _control()
    raw["objectives"][0]["depends_on"] = ["O2"]
    with pytest.raises(ContractError, match="cycle"):
        parse_goal_definition(raw, expected_version="v7")
    raw = _control()
    raw["scope_freeze"]["required_real_scales"] = [50]
    with pytest.raises(ContractError, match=r"\[50, 200\]"):
        parse_goal_definition(raw, expected_version="v7")


def test_migration_starts_fresh_dag_and_next_is_idempotent(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path)
    state = controller.store.load()
    assert state["cache"] == {}
    assert {key: value["status"] for key, value in state["objectives"].items()} == {"O1": "PENDING", "O2": "PENDING"}
    first = controller.next_work_item()
    assert first == controller.next_work_item()
    assert first["objective_id"] == "O1"


def test_state_seal_rejects_direct_mutation(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path)
    state = controller.store.load()
    state["iteration"] = 99
    controller.store.state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(GoalServiceError, match="state integrity"):
        controller.status()


@pytest.mark.parametrize("target, expected", [("control.json", "control block"), ("kernel.py", "controller kernel")])
def test_control_and_kernel_mutation_are_rejected(tmp_path: Path, target: str, expected: str) -> None:
    controller, project = _controller(tmp_path)
    path = project / target
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(GoalServiceError, match=expected):
        controller.status()


def test_pass_requires_review_then_unlocks_dependency(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path)
    controller.next_work_item()
    assert controller.evaluate_active()["status"] == "PASS"
    review = controller.next_work_item()
    assert review["type"] == "REVIEW_ACCEPTANCE"
    controller.submit_review({"work_item_id": review["work_item_id"], "decision": "NO_GAP"})
    assert controller.next_work_item()["objective_id"] == "O2"


def test_unchanged_failure_is_cached_across_attempts(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path, first_script="fail.py", second=False)
    controller.next_work_item()
    first = controller.evaluate_active()["failed_check"]
    controller.next_work_item()
    second = controller.evaluate_active()["failed_check"]
    assert first["cached"] is False
    assert second["cached"] is True
    assert controller.next_work_item()["type"] == "REVIEW_REPLAN"


def test_reviewer_check_content_is_anchored(tmp_path: Path) -> None:
    controller, project = _controller(tmp_path, second=False)
    _write(project / "tests/review_gap_test.py", "def test_gap():\n    assert False\n")
    controller.next_work_item()
    assert controller.evaluate_active()["status"] == "PASS"
    review = controller.next_work_item()
    controller.submit_review(
        {
            "work_item_id": review["work_item_id"],
            "decision": "GAP",
            "gap_kind": "PRODUCT_GAP",
            "contract_clause": "first clause",
            "program_check": {
                "id": "review-gap",
                "level": 1,
                "command": ["python3", "-m", "pytest", "-q", "tests/review_gap_test.py"],
                "timeout_seconds": 30,
                "inputs": ["tests/review_gap_test.py"],
            },
        }
    )
    _write(project / "tests/review_gap_test.py", "def test_gap():\n    assert True\n")
    with pytest.raises(GoalServiceError, match="reviewer test content changed"):
        controller.status()


def test_runner_overrides_host_pycache_with_controller_owned_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    _write(project / "pass.py", "raise SystemExit(0)\n")
    logs = tmp_path / "controller-state/logs"
    runner = ProgramRunner(project, tmp_path, logs, 200)
    check = parse_check(_check("owned-pycache", "pass.py"))
    observed: dict = {}

    def run(command, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="PASS\n")

    monkeypatch.setenv("PYTHONPYCACHEPREFIX", "/Users/example/Library/Caches/python")
    monkeypatch.setattr("valkey_scale_lab.goal.runner.subprocess.run", run)
    assert runner.run(check, {})["status"] == "PASS"
    assert observed["env"]["PYTHONPYCACHEPREFIX"] == str((tmp_path / "controller-state/pycache").resolve())


def test_failed_evaluator_repairs_consume_fresh_attempts_and_block_at_cap(tmp_path: Path) -> None:
    controller, project = _controller(tmp_path, second=False)
    _write(project / "tests/evaluator_gap_test.py", "def test_gap():\n    assert False\n")
    controller.next_work_item()
    assert controller.evaluate_active()["status"] == "PASS"
    review = controller.next_work_item()
    controller.submit_review(
        {
            "work_item_id": review["work_item_id"],
            "decision": "GAP",
            "gap_kind": "EVALUATOR_GAP",
            "contract_clause": "first clause",
            "program_check": {
                "id": "evaluator-gap",
                "level": 1,
                "command": ["python3", "-m", "pytest", "-q", "tests/evaluator_gap_test.py"],
                "timeout_seconds": 30,
                "inputs": ["evaluator.py", "tests/evaluator_gap_test.py"],
            },
        }
    )
    for expected_attempt in (1, 2, 3):
        repair = controller.next_work_item()
        assert repair["type"] == "EVALUATOR_REPAIR"
        assert repair["attempt"] == expected_attempt
        if expected_attempt == 1:
            _write(project / "evaluator.py", "VERSION = 2\n")
        assert controller.accept_evaluator_repair()["status"] == "FAIL"
        assert controller.store.load()["active_work_item"] is None
    blocked = controller.next_work_item()
    assert blocked["type"] == "BLOCKED"
    assert controller.status()["status"] == "BLOCKED"


def test_evaluator_edit_without_sealed_evaluator_gap_is_rejected(tmp_path: Path) -> None:
    controller, project = _controller(tmp_path, second=False)
    _write(project / "evaluator.py", "VERSION = 2\n")
    with pytest.raises(GoalServiceError, match="outside controlled repair"):
        controller.next_work_item()
