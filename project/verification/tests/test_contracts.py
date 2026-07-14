from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.schema_validator import validate as validate_schema
from verification import run


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_catalog_and_milestones_match_their_json_schemas() -> None:
    catalog_schema = json.loads(
        (PROJECT_ROOT / "verification/catalog.schema.json").read_text(encoding="utf-8")
    )
    catalog = json.loads(
        (PROJECT_ROOT / "verification/catalog.json").read_text(encoding="utf-8")
    )
    assert validate_schema(catalog, catalog_schema) == []

    milestone_schema = json.loads(
        (PROJECT_ROOT / "milestones/milestone.schema.json").read_text(encoding="utf-8")
    )
    for milestone_id in ("m1", "m2", "m3"):
        milestone = json.loads(
            (PROJECT_ROOT / f"milestones/{milestone_id}/milestone.json").read_text(
                encoding="utf-8"
            )
        )
        assert validate_schema(milestone, milestone_schema) == []

    suite_result_schema = json.loads(
        (PROJECT_ROOT / "verification/suite-result.schema.json").read_text(encoding="utf-8")
    )
    assert validate_schema(
        {
            "schema_version": "verification-suite-result-v1",
            "suite_id": "sample.contract",
            "status": "PASS",
            "exit_code": 0,
            "skipped": 0,
            "started_at_unix": 1,
            "captured_at_unix": 2,
        },
        suite_result_schema,
    ) == []


def test_m1_is_ready_and_future_milestones_are_explicitly_blocked() -> None:
    assert run.validate_milestone("m1")["status"] == "READY"
    for milestone_id in ("m2", "m3"):
        report = run.validate_milestone(milestone_id)
        assert report["status"] == "BLOCKED"
        assert report["planned_suite_ids"]


def test_catalog_rejects_duplicate_suite_ids(tmp_path: Path, monkeypatch) -> None:
    duplicate = {
        "schema_version": "verification-catalog-v1",
        "suites": [
            {
                "id": "sample.suite",
                "title": "sample",
                "kind": "command",
                "status": "READY",
                "argv": ["true"],
                "timeout_seconds": 1,
                "capabilities": [],
                "outputs": [],
                "skip_policy": "FAIL",
            }
        ]
        * 2,
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(duplicate), encoding="utf-8")
    monkeypatch.setattr(run, "CATALOG_PATH", path)

    with pytest.raises(run.VerificationError, match="duplicate suite id"):
        run._catalog()


def test_milestone_rejects_unknown_suite_id(tmp_path: Path, monkeypatch) -> None:
    source = json.loads(
        (PROJECT_ROOT / "milestones/m1/milestone.json").read_text(encoding="utf-8")
    )
    source["success_conditions"][0]["suite_ids"] = ["unknown.suite"]
    root = tmp_path / "milestones"
    path = root / "m1/milestone.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(run, "MILESTONE_ROOT", root)

    report = run.validate_milestone("m1")

    assert report["status"] == "INVALID"
    assert any("unknown suite" in error for error in report["errors"])


def test_milestone_rejects_an_unknown_promotion_source(tmp_path: Path, monkeypatch) -> None:
    source = json.loads(
        (PROJECT_ROOT / "milestones/m1/milestone.json").read_text(encoding="utf-8")
    )
    source["real_evidence_requirements"][1]["promotion_source_id"] = "wrong.requirement"
    root = tmp_path / "milestones"
    path = root / "m1/milestone.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(run, "MILESTONE_ROOT", root)

    report = run.validate_milestone("m1")

    assert report["status"] == "INVALID"
    assert any("promotion_source_id" in error for error in report["errors"])


def test_milestone_rejects_multiple_promotion_terminals(
    tmp_path: Path, monkeypatch
) -> None:
    source = json.loads(
        (PROJECT_ROOT / "milestones/m1/milestone.json").read_text(encoding="utf-8")
    )
    source["real_evidence_requirements"][1]["promotion_source_id"] = None
    root = tmp_path / "milestones"
    path = root / "m1/milestone.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(run, "MILESTONE_ROOT", root)

    report = run.validate_milestone("m1")

    assert report["status"] == "INVALID"
    assert any("terminal requirement" in error for error in report["errors"])


def test_milestones_use_atomic_required_acceptance_sources() -> None:
    for milestone_id in ("m1", "m2", "m3"):
        milestone = json.loads(
            (PROJECT_ROOT / f"milestones/{milestone_id}/milestone.json").read_text(
                encoding="utf-8"
            )
        )
        sources = []
        for condition in milestone["success_conditions"]:
            assert condition["required"] is True
            assert len(condition["suite_ids"]) + len(
                condition["evidence_requirement_ids"]
            ) == 1
            sources.extend(("suite", value) for value in condition["suite_ids"])
            sources.extend(
                ("real_evidence", value)
                for value in condition["evidence_requirement_ids"]
            )
        assert len(sources) == len(set(sources))


def test_milestone_rejects_shared_acceptance_source(tmp_path: Path, monkeypatch) -> None:
    source = json.loads(
        (PROJECT_ROOT / "milestones/m1/milestone.json").read_text(encoding="utf-8")
    )
    source["success_conditions"][1]["suite_ids"] = source["success_conditions"][0][
        "suite_ids"
    ]
    root = tmp_path / "milestones"
    path = root / "m1/milestone.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(run, "MILESTONE_ROOT", root)

    report = run.validate_milestone("m1")

    assert report["status"] == "INVALID"
    assert any("shared" in error for error in report["errors"])


def test_milestone_rejects_missing_and_cyclic_prerequisites(
    tmp_path: Path, monkeypatch
) -> None:
    source = json.loads(
        (PROJECT_ROOT / "milestones/m1/milestone.json").read_text(encoding="utf-8")
    )
    root = tmp_path / "milestones"
    source["prerequisite_milestone_ids"] = ["m9"]
    path = root / "m1/milestone.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(run, "MILESTONE_ROOT", root)
    report = run.validate_milestone("m1")
    assert report["status"] == "INVALID"
    assert any("unknown prerequisite" in error for error in report["errors"])

    prerequisite = json.loads(json.dumps(source))
    prerequisite["milestone"]["id"] = "m9"
    prerequisite["prerequisite_milestone_ids"] = ["m1"]
    prerequisite_path = root / "m9/milestone.json"
    prerequisite_path.parent.mkdir(parents=True)
    prerequisite_path.write_text(json.dumps(prerequisite), encoding="utf-8")
    report = run.validate_milestone("m1")
    assert report["status"] == "INVALID"
    assert any("cycle" in error for error in report["errors"])


def test_planned_suite_returns_blocked_without_execution(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        run,
        "_catalog",
        lambda: ({}, {"planned.suite": {"status": "PLANNED"}}),
    )

    assert run.run_suite("planned.suite", (), ()) == 2
    assert '"status": "BLOCKED"' in capsys.readouterr().out


def test_real_suite_rejects_fixture_or_dry_run_substitution(monkeypatch) -> None:
    suite = {
        "status": "READY",
        "kind": "real",
        "argv": ["true"],
        "capabilities": [],
        "outputs": [],
        "timeout_seconds": 1,
        "skip_policy": "FAIL",
    }
    monkeypatch.setattr(run, "_catalog", lambda: ({}, {"real.suite": suite}))

    with pytest.raises(run.VerificationError, match="fixtures or dry runs"):
        run.run_suite(
            "real.suite",
            ("artifacts_dir=tests/fixtures/capture", "mode=dry_run"),
            (),
        )


def test_required_pytest_suite_turns_skip_into_failure(tmp_path: Path, monkeypatch) -> None:
    test_path = tmp_path / "test_skip.py"
    test_path.write_text(
        "import pytest\ndef test_required_behavior(): pytest.skip('not executed')\n",
        encoding="utf-8",
    )
    suite = {
        "status": "READY",
        "kind": "pytest",
        "argv": ["python3", "-m", "pytest", "-q", str(test_path)],
        "capabilities": [],
        "outputs": [],
        "timeout_seconds": 60,
        "skip_policy": "FAIL",
    }
    monkeypatch.setattr(run, "_catalog", lambda: ({}, {"required.suite": suite}))

    result_path = tmp_path / "suite-result.json"
    assert run.run_suite("required.suite", (), (), result_path) == 1
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "FAIL"
    assert result["skipped"] == 1
