from __future__ import annotations

from pathlib import Path

from scripts import assert_no_legacy_resource_contract as legacy


def test_project_has_no_legacy_resource_contract_consumers() -> None:
    assert legacy.scan(legacy.ROOT) == []


def test_legacy_resource_contract_scan_fails_closed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = project / "src" / "consumer.py"
    source.parent.mkdir(parents=True)
    source.write_text("name = '" + "m2" + "_resource'\n", encoding="utf-8")

    failures = legacy.scan(project)

    assert failures
    assert str(source.relative_to(project)) in failures[0]
