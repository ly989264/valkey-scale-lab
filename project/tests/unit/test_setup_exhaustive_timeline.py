from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from valkey_scale_lab.runtime.setup_timeline import (
    REQUIRED_SETUP_SEGMENTS,
    SetupTimeline,
    validate_setup_timeline_artifact,
)


def _load_schema_validator():
    path = Path("scripts/schema_validator.py")
    spec = importlib.util.spec_from_file_location("schema_validator_for_test", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _evidence() -> dict[str, Any]:
    return {
        "status": "PASS",
        "real_valkey": True,
        "nodes_observed": 100,
        "data_path_result": "PASS",
        "role_counts": {"primary": 50, "replica": 50},
        "valkey_versions": ["9.1.0"],
    }


def _complete_timeline_artifact() -> dict[str, Any]:
    now = {"value": 1000.0}
    timeline = SetupTimeline(clock=lambda: now["value"], gap_threshold_seconds=0.01)
    for name in REQUIRED_SETUP_SEGMENTS:
        with timeline.span(name, name.split("_", 1)[0], {"test": True}):
            now["value"] += 0.25
    total = sum(float(segment["duration_seconds"]) for segment in timeline.segments)
    return timeline.to_artifact(
        capability_id="scale_ladder",
        run_id="test-run",
        scenario="scale_ladder",
        profile_id="exact-100",
        node_count=100,
        status="PASS",
        setup_command_wall_seconds=total + 0.5,
        real_valkey_evidence_summary=_evidence(),
    )


def test_setup_timeline_segments_are_ordered_and_gap_is_explicit() -> None:
    now = {"value": 10.0}
    timeline = SetupTimeline(clock=lambda: now["value"], gap_threshold_seconds=0.1)
    with timeline.span("setup_entry", "setup_lifecycle"):
        now["value"] = 11.0
    now["value"] = 13.0
    with timeline.span("config_parse_and_validate", "configuration"):
        now["value"] = 14.0

    segments = timeline.segments
    assert [segment["kind"] for segment in segments] == ["span", "gap", "span"]
    assert segments[0]["end_monotonic"] <= segments[1]["start_monotonic"]
    assert segments[1]["end_monotonic"] <= segments[2]["start_monotonic"]
    assert segments[1]["duration_seconds"] == 2.0


def test_parent_hierarchy_does_not_double_count_children() -> None:
    artifact = _complete_timeline_artifact()

    leaf_total = round(sum(float(segment["duration_seconds"]) for segment in artifact["segments"]), 6)
    assert artifact["setup_timeline_total_seconds"] == leaf_total
    groups = {group["name"]: group for group in artifact["stage_hierarchy"]}
    assert groups["process_config_prepare"]["exclusive_duration_seconds"] == 0.0
    child_sum = sum(child["inclusive_duration_seconds"] for child in groups["process_config_prepare"]["children"])
    assert groups["process_config_prepare"]["inclusive_duration_seconds"] == child_sum


def test_setup_timeline_artifact_conforms_to_schema(tmp_path: Path) -> None:
    artifact = _complete_timeline_artifact()
    path = tmp_path / "setup_timeline.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    validator = _load_schema_validator()
    schema = json.loads(Path("schemas/artifact/setup_timeline.schema.json").read_text(encoding="utf-8"))

    assert validator.validate(artifact, schema) == []
    assert validate_setup_timeline_artifact(artifact) == []


def test_unrecorded_gap_fails_validation() -> None:
    artifact = _complete_timeline_artifact()
    artifact["segments"][1]["start_monotonic"] += 1.5
    artifact["segments"][1]["end_monotonic"] += 1.5

    errors = validate_setup_timeline_artifact(artifact)

    assert any("silent gap" in error for error in errors)


def test_segment_overlap_fails_validation() -> None:
    artifact = _complete_timeline_artifact()
    artifact["segments"][1]["start_monotonic"] = artifact["segments"][0]["end_monotonic"] - 0.5

    errors = validate_setup_timeline_artifact(artifact)

    assert any("overlaps previous segment" in error for error in errors)


def test_missing_required_stage_fails_validation() -> None:
    artifact = _complete_timeline_artifact()
    artifact["segments"] = [segment for segment in artifact["segments"] if segment["name"] != "primary_cluster_create"]

    errors = validate_setup_timeline_artifact(artifact)

    assert any("primary_cluster_create" in error for error in errors)


def test_unexplained_time_above_two_seconds_fails_validation() -> None:
    artifact = _complete_timeline_artifact()
    artifact["setup_timeline_unexplained_seconds"] = 3.0
    artifact["setup_timeline_unexplained_status"] = "FAIL"

    errors = validate_setup_timeline_artifact(artifact)

    assert any("exceeds 2.0" in error for error in errors)
