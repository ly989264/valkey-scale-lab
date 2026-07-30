from __future__ import annotations

from pathlib import Path

from scripts.schema_validator import validate_file


ROOT = Path(__file__).resolve().parents[2]


def test_resource_observation_fixture_matches_schema() -> None:
    errors = validate_file(
        ROOT / "tests" / "fixtures" / "resource_observation" / "success.json",
        ROOT / "schemas" / "artifact" / "resource_observation.schema.json",
    )

    assert errors == []
