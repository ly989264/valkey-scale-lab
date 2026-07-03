from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, Path("scripts") / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def fixture_artifacts(tmp_path: Path) -> tuple[Path, Path, Path, dict]:
    builder = load_script("build_strict_coverage_registry")
    registry = builder.build_registry()
    scenario_plan = builder.build_scenario_plan()
    registry_path = tmp_path / "strict_coverage_registry.json"
    scenario_path = tmp_path / "strict_scenario_plan.json"
    csv_path = tmp_path / "strict_required_matrix.csv"
    write_json(registry_path, registry)
    write_json(scenario_path, scenario_plan)
    builder.write_csv(csv_path, registry["rows"])
    return registry_path, scenario_path, csv_path, registry


def run_assertion(registry: Path, scenario: Path, matrix: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "python3",
            "scripts/assert_coverage_registry.py",
            "--registry",
            str(registry),
            "--scenario-plan",
            str(scenario),
            "--matrix-csv",
            str(matrix),
            *extra,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )


def test_generator_emits_exact_strict_matrix_and_modes(tmp_path: Path) -> None:
    registry_path, scenario_path, csv_path, registry = fixture_artifacts(tmp_path)

    assert len(registry["rows"]) == 145
    ids = [row["coverage_id"] for row in registry["rows"]]
    assert len(ids) == len(set(ids))
    assert registry["summary"]["expected_counts"] == {
        "lifecycle": 36,
        "management": 33,
        "fault": 36,
        "dry_run": 40,
    }
    assert all(row["status"] == "PENDING" for row in registry["rows"])
    assert all(row["execution_mode"] == "real" for row in registry["rows"] if row["node_count"] <= 200)
    assert all(row["execution_mode"] == "dry_run" for row in registry["rows"] if row["node_count"] > 200)

    csv_lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert len(csv_lines) == 146
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    covered = {cid for item in scenario["scenarios"] for cid in item["coverage_ids"]}
    assert covered == set(ids)
    assert all(item["execution_mode"] == "dry_run" for item in scenario["scenarios"] if item["node_count"] > 200)
    real_scenarios = [item for item in scenario["scenarios"] if item["execution_mode"] == "real"]
    assert real_scenarios
    for item in real_scenarios:
        assert item["telemetry_policy"]["required"] is True
        assert f"artifacts/phases/{item['stage_owner']}/events.jsonl" in item["expected_artifacts"]
        assert f"artifacts/phases/{item['stage_owner']}/metrics_timeseries.jsonl" in item["expected_artifacts"]
        assert f"artifacts/phases/{item['stage_owner']}/workload_windows.json" in item["expected_artifacts"]
    assert all(item["telemetry_policy"]["required"] is False for item in scenario["scenarios"] if item["execution_mode"] == "dry_run")
    assert registry_path.exists()


def test_assertion_accepts_full_generated_registry(tmp_path: Path) -> None:
    registry_path, scenario_path, csv_path, _registry = fixture_artifacts(tmp_path)

    proc = run_assertion(registry_path, scenario_path, csv_path, "--require-all")

    assert proc.returncode == 0, proc.stderr
    assert "PASS coverage registry assertion" in proc.stdout


def test_assertion_rejects_duplicate_and_missing_rows(tmp_path: Path) -> None:
    registry_path, scenario_path, csv_path, registry = fixture_artifacts(tmp_path)
    mutated = copy.deepcopy(registry)
    mutated["rows"][1]["coverage_id"] = mutated["rows"][0]["coverage_id"]
    write_json(registry_path, mutated)

    proc = run_assertion(registry_path, scenario_path, csv_path, "--require-all")

    assert proc.returncode == 1
    assert "duplicate coverage_id" in proc.stderr
    assert "missing required coverage rows" in proc.stderr


def test_assertion_rejects_wrong_mode_status_owner_and_node_count(tmp_path: Path) -> None:
    registry_path, scenario_path, csv_path, registry = fixture_artifacts(tmp_path)
    mutated = copy.deepcopy(registry)
    mutated["rows"][0]["status"] = "PASS"
    mutated["rows"][0]["source_artifacts"] = ["artifacts/phases/P36/source.json"]
    mutated["rows"][0]["validation_artifacts"] = ["artifacts/phases/P36/validation.json"]
    mutated["rows"][0]["stage_owner"] = "P30_MANAGEMENT_MATRIX_50_REAL"
    mutated["rows"][0]["node_count"] = 51
    dry_row = next(row for row in mutated["rows"] if row["node_count"] == 201)
    dry_row["execution_mode"] = "real"
    write_json(registry_path, mutated)

    proc = run_assertion(registry_path, scenario_path, csv_path, "--require-all")

    assert proc.returncode == 1
    assert "wrong stage_owner" in proc.stderr
    assert "node_count must equal scale" in proc.stderr
    assert ">200 rows must be dry_run" in proc.stderr
    assert "P28 real rows must start PENDING" in proc.stderr


def test_assertion_rejects_scenario_plan_omission(tmp_path: Path) -> None:
    registry_path, scenario_path, csv_path, _registry = fixture_artifacts(tmp_path)
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario["scenarios"][0]["coverage_ids"] = scenario["scenarios"][0]["coverage_ids"][1:]
    write_json(scenario_path, scenario)

    proc = run_assertion(registry_path, scenario_path, csv_path, "--require-all")

    assert proc.returncode == 1
    assert "scenario plan omits coverage IDs" in proc.stderr


def test_assertion_rejects_missing_telemetry_policy_artifacts(tmp_path: Path) -> None:
    registry_path, scenario_path, csv_path, _registry = fixture_artifacts(tmp_path)
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    real = next(item for item in scenario["scenarios"] if item["execution_mode"] == "real")
    real.pop("telemetry_policy")
    write_json(scenario_path, scenario)

    proc = run_assertion(registry_path, scenario_path, csv_path, "--require-all")

    assert proc.returncode == 1
    assert "missing scenario field telemetry_policy" in proc.stderr

    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    real = next(item for item in scenario["scenarios"] if item["execution_mode"] == "real")
    real["telemetry_policy"] = {
        "required": True,
        "events_jsonl_required": True,
        "metrics_timeseries_jsonl_required": True,
        "workload_windows_required": True,
        "missing_values_policy": "MISSING_or_SKIPPED_WITH_REASON_with_reason",
        "dry_run_policy": "",
    }
    real["expected_artifacts"] = [
        artifact for artifact in real["expected_artifacts"] if not artifact.endswith("metrics_timeseries.jsonl")
    ]
    write_json(scenario_path, scenario)

    proc = run_assertion(registry_path, scenario_path, csv_path, "--require-all")

    assert proc.returncode == 1
    assert "metrics_timeseries.jsonl" in proc.stderr


def test_transition_validation_rejects_real_dry_run_pass(tmp_path: Path) -> None:
    registry_path, _scenario_path, _csv_path, registry = fixture_artifacts(tmp_path)
    updated = copy.deepcopy(registry)
    updated["rows"][0]["status"] = "DRY_RUN_PASS"
    updated["rows"][0]["validation_artifacts"] = ["artifacts/phases/P36/validation.json"]
    updated["rows"][0]["review_ref"] = "artifacts/goal_loop_strict/P36_FULL_FLOW_E2E_50_100_200_REAL/REVIEW.md"
    updated_path = tmp_path / "updated.json"
    write_json(updated_path, updated)

    proc = subprocess.run(
        [
            "python3",
            "scripts/assert_coverage_registry.py",
            "--previous",
            str(registry_path),
            "--updated",
            str(updated_path),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )

    assert proc.returncode == 1
    assert "real row cannot transition to DRY_RUN_PASS" in proc.stderr
