from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


STAGE_ID = "L99_TEST_STAGE"
ROLES = [
    "requirements_analyst",
    "harness_architect",
    "risk_auditor",
    "implementation_worker",
    "review_agent",
    "validation_agent",
    "anti_regression_guardian",
]


def test_minimal_in_progress_stage_validates(tmp_path: Path) -> None:
    root = _write_loop_root(tmp_path)
    validator = _load_validator()

    assert validator.validate_loop_root(root) == []


def test_previous_harness_stage_can_validate_before_design_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "loop"
    stage = root / "stages" / STAGE_ID
    stage.mkdir(parents=True)
    state = _stage_state()
    state["phase"] = "PREVIOUS_HARNESS"
    (stage / "stage_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    (stage / "commands.jsonl").write_text(json.dumps(_command_entry()) + "\n", encoding="utf-8")
    validator = _load_validator()

    assert validator.validate_loop_root(root) == []


def test_command_log_rejects_string_command(tmp_path: Path) -> None:
    root = _write_loop_root(tmp_path)
    log = root / "stages" / STAGE_ID / "commands.jsonl"
    log.write_text(
        json.dumps(
            {
                "started_at": "2026-06-30T00:00:00Z",
                "finished_at": "2026-06-30T00:00:01Z",
                "cwd": ".",
                "command": "python3 -m pytest",
                "exit_code": 0,
                "stdout_tail": "",
                "stderr_tail": "",
                "status": "PASS",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    validator = _load_validator()

    errors = validator.validate_loop_root(root)

    assert any("expected type 'array'" in error for error in errors)


def test_stage_result_pass_requires_approved_subagents_and_push(tmp_path: Path) -> None:
    root = _write_loop_root(tmp_path, include_stage_result=True)
    result = root / "stages" / STAGE_ID / "stage_result.json"
    data = json.loads(result.read_text(encoding="utf-8"))
    data["pushed"] = False
    data["subagent_verdicts"]["review_agent"] = "CHANGES_REQUESTED"
    result.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    validator = _load_validator()

    errors = validator.validate_loop_root(root)

    assert any("PASS requires pushed true" in error for error in errors)
    assert any("review_agent verdict APPROVED" in error for error in errors)


def test_stage_result_pass_requires_all_subagent_files(tmp_path: Path) -> None:
    root = _write_loop_root(tmp_path, include_stage_result=True)
    (root / "stages" / STAGE_ID / "subagents" / "review_agent.json").unlink()
    validator = _load_validator()

    errors = validator.validate_loop_root(root)

    assert any("PASS requires subagent artifact" in error and "review_agent.json" in error for error in errors)


def test_stage_result_missing_metric_requires_status_and_reason(tmp_path: Path) -> None:
    root = _write_loop_root(tmp_path, include_stage_result=True)
    result = root / "stages" / STAGE_ID / "stage_result.json"
    data = json.loads(result.read_text(encoding="utf-8"))
    data["known_missing_metrics"] = [{"metric": "split_brain_duration"}]
    result.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    validator = _load_validator()

    errors = validator.validate_loop_root(root)

    assert any("missing required key 'status'" in error for error in errors)
    assert any("missing required key 'reason'" in error for error in errors)


def test_subagent_filename_must_match_role(tmp_path: Path) -> None:
    root = _write_loop_root(tmp_path)
    subagents = root / "stages" / STAGE_ID / "subagents"
    bad = subagents / "review_agent.json"
    data = _subagent("requirements_analyst")
    bad.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    validator = _load_validator()

    errors = validator.validate_loop_root(root)

    assert any("filename role 'review_agent' does not match agent_role" in error for error in errors)


def test_anti_regression_detects_manifest_downgrade() -> None:
    validator = _load_validator()
    diff = """diff --git a/codex/phase_manifest.json b/codex/phase_manifest.json
--- a/codex/phase_manifest.json
+++ b/codex/phase_manifest.json
@@
-      "real_valkey_required": true,
+      "real_valkey_required": false,
@@
-      "required": true
+      "required": false
"""

    findings = validator.detect_anti_regression_findings(diff, ["codex/phase_manifest.json"])

    assert any("real_valkey_required downgrade" in finding for finding in findings)
    assert any("required gate or artifact downgraded" in finding for finding in findings)


def test_anti_regression_detects_controlled_ds_store() -> None:
    validator = _load_validator()

    findings = validator.detect_anti_regression_findings("", ["codex/.DS_Store"])

    assert findings == ["codex/.DS_Store: .DS_Store must not be staged or tracked under controlled paths"]


def test_anti_regression_detects_controlled_bytecode() -> None:
    validator = _load_validator()

    findings = validator.detect_anti_regression_findings("", ["scripts/__pycache__/codex_gate.cpython-313.pyc"])

    assert findings == [
        "scripts/__pycache__/codex_gate.cpython-313.pyc: generated Python bytecode must not be staged or tracked under controlled paths"
    ]


def test_anti_regression_status_parser_includes_untracked_files() -> None:
    validator = _load_validator()

    files = validator.changed_files_from_porcelain(
        " M .github/workflows/github-coverage-gates.yml\n"
        "?? schemas/loop_engineering/stage_result.schema.json\n"
        "R  old/path.json -> artifacts/loop_engineering/new/path.json\n"
    )

    assert files == [
        ".github/workflows/github-coverage-gates.yml",
        "schemas/loop_engineering/stage_result.schema.json",
        "artifacts/loop_engineering/new/path.json",
    ]


def _write_loop_root(tmp_path: Path, include_stage_result: bool = False) -> Path:
    root = tmp_path / "loop"
    stage = root / "stages" / STAGE_ID
    subagents = stage / "subagents"
    subagents.mkdir(parents=True)
    (stage / "stage_state.json").write_text(json.dumps(_stage_state(), indent=2) + "\n", encoding="utf-8")
    (stage / "previous_harness_result.json").write_text(
        json.dumps(_previous_harness(), indent=2) + "\n", encoding="utf-8"
    )
    (stage / "current_harness_plan.json").write_text(
        json.dumps(_current_harness_plan(), indent=2) + "\n", encoding="utf-8"
    )
    (stage / "commands.jsonl").write_text(json.dumps(_command_entry()) + "\n", encoding="utf-8")
    for role in ROLES:
        (subagents / f"{role}.json").write_text(json.dumps(_subagent(role), indent=2) + "\n", encoding="utf-8")
    if include_stage_result:
        (stage / "stage_result.json").write_text(json.dumps(_stage_result(), indent=2) + "\n", encoding="utf-8")
    return root


def _stage_state() -> dict:
    return {
        "schema_version": "v1",
        "stage_id": STAGE_ID,
        "status": "IN_PROGRESS",
        "phase": "VALIDATE",
        "started_at": "2026-06-30T00:00:00Z",
        "updated_at": "2026-06-30T00:00:01Z",
        "branch": "codex/valkey-scale-lab-loop",
        "base_head": "abc",
        "current_head": "abc",
        "constraints": [],
        "blockers": [],
        "files_touched": [],
    }


def _previous_harness() -> dict:
    return {
        "schema_version": "v1",
        "stage_id": STAGE_ID,
        "status": "PASS",
        "completed_at": "2026-06-30T00:00:01Z",
        "environment_notes": [],
        "commands_log": "artifacts/loop_engineering/stages/L99_TEST_STAGE/commands.jsonl",
        "commands": [{"name": "baseline", "command": "python3 scripts/codex_gate.py precheck --all", "status": "PASS"}],
        "all_required_baseline_commands_passed": True,
    }


def _current_harness_plan() -> dict:
    return {
        "schema_version": "v1",
        "stage_id": STAGE_ID,
        "new_tests": [],
        "new_schemas": [],
        "new_cli_gates": [],
        "new_artifact_checks": [],
        "expected_initial_failures": [],
        "acceptance_criteria": [],
    }


def _command_entry() -> dict:
    return {
        "started_at": "2026-06-30T00:00:00Z",
        "finished_at": "2026-06-30T00:00:01Z",
        "cwd": ".",
        "command": ["python3", "scripts/codex_gate.py", "precheck", "--all"],
        "exit_code": 0,
        "stdout_tail": "PASS precheck\n",
        "stderr_tail": "",
        "status": "PASS",
    }


def _subagent(role: str) -> dict:
    return {
        "schema_version": "v1",
        "stage_id": STAGE_ID,
        "agent_role": role,
        "created_at": "2026-06-30T00:00:00Z",
        "context_files_read": [{"path": "README.md", "purpose": "context", "key_findings": []}],
        "findings": [],
        "proposed_harness": [],
        "implementation_plan": [],
        "acceptance_criteria": ["validate the contract"],
        "risks": [],
        "forbidden_shortcuts": [],
        "commands_to_run": [],
        "verdict": "APPROVED",
        "notes": "",
    }


def _stage_result() -> dict:
    return {
        "schema_version": "v1",
        "stage_id": STAGE_ID,
        "status": "PASS",
        "completed_at": "2026-06-30T00:00:02Z",
        "commit_sha": "abc",
        "pushed": True,
        "previous_harness_passed": True,
        "current_harness_passed": True,
        "subagent_verdicts": {role: "APPROVED" for role in ROLES},
        "commands_log": "artifacts/loop_engineering/stages/L00_LOOP_ENGINE_HARNESS_BOOTSTRAP/commands.jsonl",
        "artifacts": [],
        "metrics_added": [],
        "visualizations_added": [],
        "real_valkey_gates": [],
        "fake_gates": [],
        "known_missing_metrics": [],
        "risks_remaining": [],
    }


def _load_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("loop_engineering_validate", Path("scripts/loop_engineering_validate.py"))
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
