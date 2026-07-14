from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from valkey_scale_lab.meta_loop.contracts import ContractError, validate_control_block
from valkey_scale_lab.meta_loop.controller import MetaLoopController, MetaLoopError
from valkey_scale_lab.meta_loop.digests import product_tree_digest
from valkey_scale_lab.meta_loop.runner import ProgramRunner
from valkey_scale_lab.meta_loop.store import StateStore


OBJECTIVE_IDS = [
    "O1_TRIGGER_AND_SAFETY",
    "O2_LIFECYCLE_AND_TELEMETRY",
    "O3_MANAGEMENT_AND_STABILITY",
    "O4_FAULT_FAILOVER_AND_RECOVERY",
    "O5_EVIDENCE_REPORT_AND_SCALE_50",
    "O6_SCALE_200_AND_FINAL",
]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check(check_id: str, path: str, level: int = 1) -> dict:
    return {"id": check_id, "level": level, "command": ["python3", path], "timeout_seconds": 20, "inputs": [path]}


def reviewer_check(check_id: str, path: str, inputs: list[str] | None = None) -> dict:
    return {
        "id": check_id,
        "level": 1,
        "command": ["python3", "-m", "pytest", "-q", path],
        "timeout_seconds": 20,
        "inputs": inputs or [path],
    }


def make_control(project: Path) -> Path:
    objectives = []
    for index, oid in enumerate(OBJECTIVE_IDS):
        objectives.append(
            {
                "id": oid,
                "title": oid,
                "depends_on": [] if index == 0 else [OBJECTIVE_IDS[index - 1]],
                "clauses": [f"clause {oid}"],
                "context_paths": ["src"],
                "checks": [check(f"check-{index}", "scripts/objective.py")],
            }
        )
    control = {
        "schema_version": "v3",
        "goal_id": "milestone1-local-complete-v3",
        "goal": "test",
        "scope_freeze": {
            "source": "test",
            "trigger_nodes": {"min": 30, "max": 2000, "exact": True},
            "required_real_scales": [50, 200],
            "supported_not_gated_scales": [30, 100],
            "above_200": {"automatic": False, "operator_opt_in": True, "resource_preflight": True, "cost_acknowledgement": True, "silent_downscale": False},
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
        "closure_checks": [check("closure", "scripts/closure.py")],
        "evaluator_guard_checks": [check("evaluator-guard", "scripts/pass.py")],
        "objectives": objectives,
    }
    path = project / "codex/meta_m1/control_block.json"
    write_json(path, control)
    return path


def make_controller(tmp_path: Path, objective_exit: int = 0, closure_exit: int = 0) -> tuple[MetaLoopController, Path]:
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    (project / "src").mkdir()
    (scripts / "pass.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (scripts / "objective.py").write_text(f"raise SystemExit({objective_exit})\n", encoding="utf-8")
    (scripts / "closure.py").write_text(f"raise SystemExit({closure_exit})\n", encoding="utf-8")
    (scripts / "meta_m1_evidence_gate.py").write_text("EVALUATOR = 'v1'\n", encoding="utf-8")
    (scripts / "meta_m1_real_gate.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    control = make_control(project)
    return MetaLoopController(project, control, tmp_path / "v3", tmp_path), project


def review_no_gap(controller: MetaLoopController) -> None:
    review = controller.next_work_item()
    assert review["type"] == "REVIEW_ACCEPTANCE"
    controller.submit_review({"work_item_id": review["work_item_id"], "decision": "NO_GAP"})


def test_control_contract_freezes_scale_semantics(tmp_path: Path) -> None:
    _, project = make_controller(tmp_path)
    control = json.loads((project / "codex/meta_m1/control_block.json").read_text())
    control["scope_freeze"]["required_real_scales"] = [30, 50, 100, 200]
    with pytest.raises(ContractError, match="exactly"):
        validate_control_block(control)


def test_next_is_idempotent_and_context_is_bounded(tmp_path: Path) -> None:
    controller, _ = make_controller(tmp_path)
    controller.bootstrap()
    first = controller.next_work_item()
    assert first == controller.next_work_item()
    assert first["type"] == "WORK"
    assert len(json.dumps(first).encode()) < 12000


def test_candidate_pass_runs_closure_floor_before_review(tmp_path: Path) -> None:
    controller, _ = make_controller(tmp_path)
    controller.bootstrap()
    controller.next_work_item()
    result = controller.evaluate_active()
    assert result["status"] == "PASS"
    assert result["checks_total"] == 3
    assert controller.next_work_item()["type"] == "REVIEW_ACCEPTANCE"


def test_program_pass_becomes_stale_when_inputs_change_before_review(tmp_path: Path) -> None:
    controller, project = make_controller(tmp_path)
    controller.bootstrap()
    controller.next_work_item()
    assert controller.evaluate_active()["status"] == "PASS"
    (project / "scripts/objective.py").write_text("raise SystemExit(0)\n# changed\n", encoding="utf-8")
    work = controller.next_work_item()
    assert work["type"] == "WORK"
    assert work["attempt"] == 1


def test_closure_regression_prevents_objective_pass(tmp_path: Path) -> None:
    controller, _ = make_controller(tmp_path, closure_exit=1)
    controller.bootstrap()
    controller.next_work_item()
    result = controller.evaluate_active()
    assert result["status"] == "FAIL"
    assert result["failed_check"]["check_id"] == "closure"


def test_unchanged_cached_failure_routes_to_replan_without_three_more_turns(tmp_path: Path) -> None:
    controller, _ = make_controller(tmp_path, objective_exit=7)
    controller.bootstrap()
    controller.next_work_item()
    assert controller.evaluate_active()["failed_check"]["cached"] is False
    controller.next_work_item()
    assert controller.evaluate_active()["failed_check"]["cached"] is True
    assert controller.next_work_item()["type"] == "REVIEW_REPLAN"


def test_edits_do_not_reset_budget_for_the_same_failing_gate(tmp_path: Path) -> None:
    controller, project = make_controller(tmp_path, objective_exit=7)
    controller.bootstrap()
    for revision in range(3):
        work = controller.next_work_item()
        assert work["type"] == "WORK"
        (project / "scripts/objective.py").write_text(
            f"# revision {revision}\nraise SystemExit(7)\n",
            encoding="utf-8",
        )
        assert controller.evaluate_active()["status"] == "FAIL"
    review = controller.next_work_item()
    assert review["type"] == "REVIEW_REPLAN"


def test_new_reviewer_gap_gets_fresh_gap_budget(tmp_path: Path) -> None:
    controller, project = make_controller(tmp_path)
    controller.bootstrap()
    controller.next_work_item()
    controller.evaluate_active()
    review = controller.next_work_item()
    gap = project / "tests/gap.py"
    gap.parent.mkdir()
    gap.write_text("def test_gap():\n    assert False\n", encoding="utf-8")
    status = controller.submit_review(
        {
            "work_item_id": review["work_item_id"],
            "decision": "GAP",
            "gap_kind": "PRODUCT_GAP",
            "contract_clause": f"clause {OBJECTIVE_IDS[0]}",
            "finding": "product gap",
            "program_check": reviewer_check("new-gap", "tests/gap.py"),
        }
    )
    first = status["objectives"][0]
    assert first["attempts"] == 0
    assert first["replans"] == 0


def test_reviewer_added_test_is_immutable_during_product_repair(tmp_path: Path) -> None:
    controller, project = make_controller(tmp_path)
    controller.bootstrap()
    controller.next_work_item()
    controller.evaluate_active()
    review = controller.next_work_item()
    gap = project / "tests/gap.py"
    gap.parent.mkdir()
    gap.write_text("def test_gap():\n    assert False\n", encoding="utf-8")
    controller.submit_review(
        {
            "work_item_id": review["work_item_id"],
            "decision": "GAP",
            "gap_kind": "PRODUCT_GAP",
            "contract_clause": f"clause {OBJECTIVE_IDS[0]}",
            "finding": "anchored gap",
            "program_check": reviewer_check("anchored-gap", "tests/gap.py"),
        }
    )
    gap.write_text("def test_gap():\n    assert True\n", encoding="utf-8")
    assert controller.doctor()["status"] == "FAIL"
    with pytest.raises(MetaLoopError, match="review check integrity"):
        controller.next_work_item()


def test_evaluator_gap_has_controlled_repair_transition(tmp_path: Path) -> None:
    controller, project = make_controller(tmp_path)
    controller.bootstrap()
    controller.next_work_item()
    controller.evaluate_active()
    review = controller.next_work_item()
    gap_test = project / "tests/evaluator_gap.py"
    gap_test.parent.mkdir()
    gap_test.write_text(
        "from pathlib import Path\ndef test_evaluator_gap():\n    assert 'v2' in Path('scripts/meta_m1_evidence_gate.py').read_text()\n",
        encoding="utf-8",
    )
    controller.submit_review(
        {
            "work_item_id": review["work_item_id"],
            "decision": "GAP",
            "gap_kind": "EVALUATOR_GAP",
            "contract_clause": f"clause {OBJECTIVE_IDS[0]}",
            "finding": "evaluator gap",
            "program_check": reviewer_check("evaluator-gap", "tests/evaluator_gap.py", ["scripts/meta_m1_evidence_gate.py", "tests/evaluator_gap.py"]),
        }
    )
    repair = controller.next_work_item()
    assert repair["type"] == "EVALUATOR_REPAIR"
    (project / "scripts/meta_m1_evidence_gate.py").write_text("EVALUATOR = 'still-old'\n", encoding="utf-8")
    assert controller.accept_evaluator_repair()["status"] == "FAIL"
    (project / "scripts/meta_m1_evidence_gate.py").write_text("EVALUATOR = 'v2'\n", encoding="utf-8")
    (project / "README.md").write_text("out of scope\n", encoding="utf-8")
    with pytest.raises(MetaLoopError, match="outside the evaluator repair allowlist"):
        controller.accept_evaluator_repair()
    (project / "README.md").unlink()
    assert controller.accept_evaluator_repair()["status"] == "PASS"
    assert controller.doctor()["status"] == "PASS"
    assert controller.next_work_item()["type"] == "VERIFY"


def test_evaluator_edit_outside_repair_is_rejected(tmp_path: Path) -> None:
    controller, project = make_controller(tmp_path)
    controller.bootstrap()
    (project / "scripts/meta_m1_evidence_gate.py").write_text("changed = True\n", encoding="utf-8")
    assert controller.doctor()["status"] == "FAIL"
    with pytest.raises(MetaLoopError, match="outside controlled repair"):
        controller.next_work_item()


def test_control_and_kernel_changes_are_rejected_after_bootstrap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller, project = make_controller(tmp_path)
    controller.bootstrap()
    control_path = project / "codex/meta_m1/control_block.json"
    control = json.loads(control_path.read_text(encoding="utf-8"))
    control["goal"] = "mutated"
    write_json(control_path, control)
    assert controller.doctor()["status"] == "FAIL"
    with pytest.raises(MetaLoopError, match="control block changed"):
        controller.next_work_item()

    restored, _ = make_controller(tmp_path / "kernel")
    restored.bootstrap()
    original = restored._kernel_digest()
    monkeypatch.setattr(restored, "_kernel_digest", lambda: "0" * 64 if original != "0" * 64 else "1" * 64)
    assert restored.doctor()["status"] == "FAIL"
    with pytest.raises(MetaLoopError, match="controller kernel changed"):
        restored.next_work_item()


def test_state_payload_tampering_is_rejected_even_when_event_chain_is_unchanged(tmp_path: Path) -> None:
    controller, _ = make_controller(tmp_path)
    controller.bootstrap()
    state = controller.store.load()
    state["objectives"][OBJECTIVE_IDS[0]]["status"] = "COMPLETE"
    controller.store.save(state)
    assert controller.doctor()["status"] == "FAIL"
    with pytest.raises(MetaLoopError, match="state payload integrity"):
        controller.next_work_item()


def test_product_digest_excludes_evaluator_but_includes_product(tmp_path: Path) -> None:
    _, project = make_controller(tmp_path)
    before = product_tree_digest(project)
    (project / "scripts/meta_m1_evidence_gate.py").write_text("changed = True\n", encoding="utf-8")
    assert product_tree_digest(project) == before
    (project / "scripts/objective.py").write_text("changed = True\n", encoding="utf-8")
    assert product_tree_digest(project) != before


def test_real_gate_cache_digest_ignores_evaluator_only_changes(tmp_path: Path) -> None:
    _, project = make_controller(tmp_path)
    runner = ProgramRunner(project, tmp_path, tmp_path / "logs", 200)
    item = {
        **check("real", "scripts/meta_m1_real_gate.py", 3),
        "digest_mode": "product_evidence",
        "inputs": ["src", "scripts", "../evidence/scale-50"],
    }
    before = runner.check_input_digest(item)
    (project / "scripts/meta_m1_evidence_gate.py").write_text("changed = True\n", encoding="utf-8")
    assert runner.check_input_digest(item) == before
    (project / "scripts/objective.py").write_text("changed = True\n", encoding="utf-8")
    assert runner.check_input_digest(item) != before


def test_review_check_cannot_depend_on_current_loop_evidence(tmp_path: Path) -> None:
    controller, project = make_controller(tmp_path)
    controller.bootstrap()
    controller.next_work_item()
    controller.evaluate_active()
    review = controller.next_work_item()
    gap = project / "tests/gap.py"
    gap.parent.mkdir()
    gap.write_text("def test_gap():\n    assert False\n", encoding="utf-8")
    with pytest.raises(MetaLoopError, match="hermetic"):
        controller.submit_review(
            {
                "work_item_id": review["work_item_id"],
                "decision": "GAP",
                "gap_kind": "PRODUCT_GAP",
                "contract_clause": f"clause {OBJECTIVE_IDS[0]}",
                "finding": "non-hermetic",
                "program_check": reviewer_check("bad-gap", "tests/gap.py", ["tests/gap.py", "../loop_evidence/current"]),
            }
        )


def test_review_gap_must_use_focused_pytest_command(tmp_path: Path) -> None:
    controller, project = make_controller(tmp_path)
    controller.bootstrap()
    controller.next_work_item()
    controller.evaluate_active()
    review = controller.next_work_item()
    gap = project / "tests/gap.py"
    gap.parent.mkdir()
    gap.write_text("def test_gap():\n    assert False\n", encoding="utf-8")
    bad = reviewer_check("bad-command", "tests/gap.py")
    bad["command"] = ["python3", "tests/gap.py"]
    with pytest.raises(MetaLoopError, match="focused pytest"):
        controller.submit_review(
            {
                "work_item_id": review["work_item_id"],
                "decision": "GAP",
                "gap_kind": "PRODUCT_GAP",
                "contract_clause": f"clause {OBJECTIVE_IDS[0]}",
                "finding": "command bypass",
                "program_check": bad,
            }
        )


def make_v2_receipt(tmp_path: Path, controller: MetaLoopController) -> Path:
    v2_root = tmp_path / "v2"
    store = StateStore(v2_root)
    state = {
        "schema_version": "v2",
        "goal_id": "milestone1-local-complete-v2",
        "control_digest": "b" * 64,
        "harness_digest": "c" * 64,
        "iteration": 1,
        "last_event_hash": None,
        "events": [],
        "objectives": {
            oid: {"status": "COMPLETE" if index < 4 else "BLOCKED" if index == 4 else "PENDING", "added_checks": [], "review_rounds": 2 if index < 5 else 0}
            for index, oid in enumerate(OBJECTIVE_IDS)
        },
    }
    store.append_event(state, {"schema_version": "v2", "event": "SOURCE", "iteration": 1})
    store.save(state)
    digest = hashlib.sha256(store.state_path.read_bytes()).hexdigest()
    manifest = tmp_path / "scale50-manifest.json"
    write_json(manifest, {"schema_version": "test", "files": []})
    receipt = tmp_path / "receipt.json"
    write_json(
        receipt,
        {
            "schema_version": "meta-m1-v3-migration-receipt-v1",
            "source_run": "milestone1-v2",
            "source_state_path": str(store.state_path),
            "source_state_sha256": digest,
            "source_last_event_hash": state["last_event_hash"],
            "source_control_digest": state["control_digest"],
            "source_harness_digest": state["harness_digest"],
            "source_iteration": state["iteration"],
            "scale50_admission_sha256": "a" * 64,
            "scale50_manifest_path": str(manifest),
            "scale50_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        },
    )
    return receipt


def test_v2_migration_preserves_completed_objectives_and_requires_regression(tmp_path: Path) -> None:
    controller, _ = make_controller(tmp_path)
    receipt = make_v2_receipt(tmp_path, controller)
    status = controller.migrate_v2(receipt)
    assert [item["status"] for item in status["objectives"][:4]] == ["COMPLETE"] * 4
    assert status["objectives"][4]["review_rounds"] == 0
    assert status["migration"]["scale50_admission_status"] == "QUARANTINED_RAW_CAPTURE"
    assert controller.next_work_item()["type"] == "RECOVERY_WORK"
    assert controller.evaluate_active()["status"] == "PASS"
    assert controller.next_work_item()["objective_id"] == OBJECTIVE_IDS[4]


def test_v2_migration_rejects_changed_snapshot_and_wrong_terminal_state(tmp_path: Path) -> None:
    controller, _ = make_controller(tmp_path)
    receipt = make_v2_receipt(tmp_path, controller)
    receipt_value = json.loads(receipt.read_text(encoding="utf-8"))
    source_path = Path(receipt_value["source_state_path"])
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["objectives"][OBJECTIVE_IDS[4]]["status"] = "COMPLETE"
    write_json(source_path, source)
    receipt_value["source_state_sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    write_json(receipt, receipt_value)
    with pytest.raises(MetaLoopError, match="objective statuses"):
        controller.migrate_v2(receipt)


def test_check_that_creates_evidence_caches_post_run_digest(tmp_path: Path) -> None:
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    producer = scripts / "producer.py"
    producer.write_text("from pathlib import Path\nPath('evidence').mkdir(exist_ok=True)\nPath('evidence/result.json').write_text('{}')\n", encoding="utf-8")
    runner = ProgramRunner(project, tmp_path, tmp_path / "logs", 200)
    cache: dict = {}
    item = {"id": "producer", "level": 3, "command": ["python3", "scripts/producer.py"], "timeout_seconds": 20, "inputs": ["scripts/producer.py", "evidence"]}
    assert runner.run(item, cache)["cached"] is False
    assert runner.run(item, cache)["cached"] is True


def test_shared_cache_result_keeps_current_check_identity(tmp_path: Path) -> None:
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "pass.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    runner = ProgramRunner(project, tmp_path, tmp_path / "logs", 200)
    cache: dict = {}
    first = check("first-id", "scripts/pass.py")
    second = check("second-id", "scripts/pass.py")
    assert runner.run(first, cache)["check_id"] == "first-id"
    reused = runner.run(second, cache)
    assert reused["cached"] is True
    assert reused["check_id"] == "second-id"
    assert reused["cached_from_check_id"] == "first-id"
