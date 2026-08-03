from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

import valkey_scale_lab.runtime.setup_timeline as setup_timeline_module
from valkey_scale_lab.runtime.setup_timeline import (
    REQUIRED_M2_SETUP_EVENTS,
    REQUIRED_SETUP_SEGMENTS,
    SetupTimeline,
    validate_setup_timeline_artifact,
    validate_setup_timeline_events,
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


def _complete_timeline_artifact(
    *,
    scenario: str = "scale_ladder",
    include_scale_ladder_artifact: bool = True,
) -> dict[str, Any]:
    now = {"value": 1000.0}
    timeline = SetupTimeline(clock=lambda: now["value"], gap_threshold_seconds=0.01)
    names = [
        name
        for name in REQUIRED_SETUP_SEGMENTS
        if include_scale_ladder_artifact or name != "scale_ladder_artifact_write"
    ]
    names.insert(names.index("cluster_snapshot_write"), "cluster_final_full_snapshot")
    for name in names:
        with timeline.span(name, name.split("_", 1)[0], {"test": True}):
            now["value"] += 0.25
    total = sum(float(segment["duration_seconds"]) for segment in timeline.segments)
    return timeline.to_artifact(
        capability_id=scenario,
        run_id="test-run",
        scenario=scenario,
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


def test_shared_monotonic_fails_closed_when_system_clock_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_clock_id: int) -> float:
        raise OSError("CLOCK_MONOTONIC unavailable")

    monkeypatch.setattr(setup_timeline_module.time, "clock_gettime", unavailable)

    with pytest.raises(OSError, match="CLOCK_MONOTONIC unavailable"):
        SetupTimeline()


def test_setup_timeline_records_ordered_m2_monotonic_events_without_changing_spans() -> None:
    now = {"value": 10.0}
    timeline = SetupTimeline(clock=lambda: now["value"])
    with timeline.span("setup_entry", "setup_lifecycle"):
        for name in REQUIRED_M2_SETUP_EVENTS:
            now["value"] += 0.1
            timeline.mark_event(name, "m2_measurement", {"source": "unit"})
        now["value"] += 0.1

    artifact = timeline.to_artifact(
        capability_id="m2_measurement",
        run_id="unit-events",
        scenario="m2",
        profile_id="fake",
        node_count=0,
        status="FAIL",
    )

    assert len(artifact["segments"]) == 1
    assert [event["name"] for event in artifact["events"]] == REQUIRED_M2_SETUP_EVENTS
    assert validate_setup_timeline_events(
        artifact["events"],
        required_names=REQUIRED_M2_SETUP_EVENTS,
    ) == []


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
    assert "events" not in artifact
    assert "event_count" not in artifact["summary"]


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


def test_integrated_replica_pipeline_timeline_allows_missing_replica_meet() -> None:
    artifact = _complete_timeline_artifact()
    segments = [segment for segment in artifact["segments"] if segment["name"] != "replica_meet"]
    cursor = float(segments[0]["start_monotonic"])
    for index, segment in enumerate(segments, start=1):
        duration = float(segment["duration_seconds"])
        segment["id"] = f"segment_{index:03d}"
        segment["start_monotonic"] = round(cursor, 6)
        segment["end_monotonic"] = round(cursor + duration, 6)
        cursor += duration
    for segment in segments:
        if segment["name"] == "replica_replicate":
            segment["details"]["replica_meet_integrated_with_pipeline"] = True
    rebuilt = setup_timeline_module.build_setup_timeline_artifact(
        capability_id=artifact["capability_id"],
        run_id=artifact["run_id"],
        scenario=artifact["scenario"],
        profile_id=artifact["profile_id"],
        node_count=artifact["node_count"],
        status="PASS",
        segments=segments,
        setup_command_wall_seconds=sum(float(segment["duration_seconds"]) for segment in segments),
        real_valkey_evidence_summary=_evidence(),
    )

    assert rebuilt["status"] == "PASS"
    assert rebuilt["required_stage_coverage"]["required_segments"]["replica_meet"] == "PASS"
    cluster_group = next(group for group in rebuilt["stage_hierarchy"] if group["name"] == "cluster_formation")
    replica_meet = next(child for child in cluster_group["children"] if child["name"] == "replica_meet")
    assert replica_meet["status"] == "PASS"
    assert replica_meet["details"]["replica_meet_integrated_with_pipeline"] is True
    assert validate_setup_timeline_artifact(rebuilt) == []


def test_missing_replica_meet_without_integrated_marker_still_fails_validation() -> None:
    artifact = _complete_timeline_artifact()
    artifact["segments"] = [segment for segment in artifact["segments"] if segment["name"] != "replica_meet"]

    errors = validate_setup_timeline_artifact(artifact)

    assert "missing required setup timeline segment: replica_meet" in errors


@pytest.mark.parametrize("scenario", ["cluster_timeout", "failover_timeline"])
def test_non_scale_ladder_timeline_does_not_require_scale_artifact_stage(
    scenario: str,
) -> None:
    artifact = _complete_timeline_artifact(
        scenario=scenario,
        include_scale_ladder_artifact=False,
    )

    assert artifact["status"] == "PASS"
    assert artifact["required_stage_coverage"]["status"] == "PASS"
    assert "scale_ladder_artifact_write" not in artifact["required_stage_coverage"]["required_segments"]
    assert validate_setup_timeline_artifact(artifact) == []


def test_scale_ladder_timeline_requires_scale_artifact_stage() -> None:
    artifact = _complete_timeline_artifact(
        scenario="scale_ladder",
        include_scale_ladder_artifact=False,
    )

    assert artifact["status"] == "FAIL"
    assert artifact["required_stage_coverage"]["required_segments"]["scale_ladder_artifact_write"] == "MISSING"
    assert "missing required setup timeline segment: scale_ladder_artifact_write" in artifact["errors"]


def test_unknown_scenario_cannot_drop_scale_artifact_requirement() -> None:
    artifact = _complete_timeline_artifact(
        scenario="cluster-timeout-typo",
        include_scale_ladder_artifact=False,
    )

    assert artifact["status"] == "FAIL"
    assert "missing required setup timeline segment: scale_ladder_artifact_write" in artifact["errors"]


def test_unexplained_time_above_two_seconds_fails_validation() -> None:
    artifact = _complete_timeline_artifact()
    artifact["setup_timeline_unexplained_seconds"] = 3.0
    artifact["setup_timeline_unexplained_status"] = "FAIL"

    errors = validate_setup_timeline_artifact(artifact)

    assert any("exceeds 2.0" in error for error in errors)
