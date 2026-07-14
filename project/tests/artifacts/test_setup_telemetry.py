from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab.analysis import create_analysis_summary
from valkey_scale_lab.report import render_report
from valkey_scale_lab.runtime.setup_timeline import (
    SetupTimeline,
    build_setup_telemetry_artifact,
    validate_setup_telemetry_artifact,
    write_setup_telemetry_artifact,
)


def test_setup_telemetry_schema_writer_and_gate_shape(tmp_path: Path) -> None:
    timeline = SetupTimeline(clock=_clock([0, 0.001, 0.003, 0.004, 0.007, 0.008]), gap_threshold_seconds=10)
    with timeline.span("config_parse_and_validate", "configuration", {"config_parse_ms": 1.0, "config_validate_ms": 2.0}):
        pass
    with timeline.span("port_preflight_check", "preflight"):
        pass
    telemetry = build_setup_telemetry_artifact(
        capability_id="scale_ladder",
        run_id="test-run",
        scenario="scale_ladder",
        profile_id="exact-50",
        status="PASS",
        node_count=2,
        segments=timeline.segments,
        runtime_timings=[
            {"name": "nodehost_start", "duration_seconds": 0.01, "details": {}},
            {"name": "process_ready_wait", "duration_seconds": 0.02, "details": {}},
            {"name": "replica_replicate", "duration_seconds": 0.03, "details": {}},
        ],
        nodes=[
            {"logical_id": "shard-0000-primary", "role": "primary", "pid": 101, "nodehost_id": "nh-1", "cluster_state": "ok", "cluster_known_nodes": 2},
            {"logical_id": "shard-0000-replica-00", "role": "replica", "pid": 102, "nodehost_id": "nh-1", "cluster_state": "ok", "cluster_known_nodes": 2},
        ],
        nodehosts=[{"nodehost_id": "nh-1", "logical_node_count": 2, "az_id": "az-a", "host_id": "local"}],
        cleanup_report={"status": "PASS", "resources_remaining": [], "cleanup_timing": {"cleanup_remove_containers_seconds": 0.01}},
    )
    path = tmp_path / "setup_telemetry.json"
    write_setup_telemetry_artifact(path, telemetry)
    schema = json.loads(Path("schemas/artifact/setup_telemetry.schema.json").read_text(encoding="utf-8"))
    assert telemetry["artifact_type"] == schema["properties"]["artifact_type"]["const"]
    assert validate_setup_telemetry_artifact(telemetry) == []
    assert telemetry["metrics"]["cleanup_ms"] == 10.0
    assert telemetry["slowest_nodes_topN"]


def test_setup_telemetry_propagates_to_analysis_and_chinese_report(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write(source / "run_summary.json", {"capability_id": "cluster_lifecycle", "run_id": "run", "status": "PASS", "missing_metrics": []})
    _write(source / "valkey_e2e_evidence.json", {"status": "PASS", "real_valkey": True, "valkey_versions": ["9.1.0"], "nodes_observed": 2, "cluster_state_observed": "ok"})
    _write(source / "failover_report.json", {"status": "PASS", "failovers": [], "summary": {}})
    _write(source / "cleanup_report.json", {"status": "PASS", "resources_remaining": []})
    fixture = json.loads(Path("tests/fixtures/setup_telemetry/success/setup_telemetry.json").read_text(encoding="utf-8"))
    _write(source / "setup_telemetry.json", fixture)

    analysis = create_analysis_summary(source, tmp_path / "analysis_summary.json")
    index = render_report(tmp_path / "analysis_summary.json", tmp_path / "report", tmp_path / "report_index.json")

    assert analysis["setup_aggregates"]["stage_duration_ranking"]
    assert analysis["setup_telemetry"]["metrics"]["config_parse_ms"] == 1.0
    report_names = {Path(item["path"]).name for item in index["reports"]}
    assert {"setup_lifecycle_durations.csv", "setup_slowest_nodes.csv", "setup_waterfall.svg"}.issubset(report_names)
    assert "集群拉起瀑布图" in (tmp_path / "report" / "report.md").read_text(encoding="utf-8")


def _clock(values: list[float]):
    items = iter(values)
    return lambda: next(items)


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
