from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_provenance_graph.py"

spec = importlib.util.spec_from_file_location("build_provenance_graph", SCRIPT)
build_provenance_graph = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(build_provenance_graph)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def phase(phase_id: str, artifacts: list[str]) -> dict[str, Any]:
    return {
        "id": phase_id,
        "automatic": True,
        "real_valkey_required": False,
        "required_artifacts": [
            {"path": path, "schema": "schemas/artifact/generic.schema.json", "required": True}
            for path in artifacts
        ],
        "gates": [],
    }


def write_manifest(root: Path, phases: list[dict[str, Any]]) -> None:
    write_json(
        root / "codex" / "phase_manifest.json",
        {
            "version": "v1",
            "project": "valkey-scale-lab",
            "default_max_nodes": 100,
            "automatic_stop_after": phases[-1]["id"],
            "phases": phases + [{"id": "P14_SCALE_1000_OPTIN_DRYRUN", "automatic": False, "gates": [], "required_artifacts": []}],
        },
    )


def minimal_artifact(artifact_type: str, phase_id: str, run_id: str = "run") -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": artifact_type,
        "phase_id": phase_id,
        "run_id": run_id,
        "created_at": "2026-06-30T00:00:00Z",
        "producer": {"name": "fixture", "version": "v1"},
        "status": "PASS",
    }


def findings(report: dict[str, Any], category: str) -> list[dict[str, Any]]:
    return [finding for finding in report["findings"] if finding["category"] == category]


def node(report: dict[str, Any], path: str) -> dict[str, Any]:
    return next(item for item in report["nodes"] if item["path"] == path)


def has_edge(report: dict[str, Any], source: str, target: str, relation: str | None = None) -> bool:
    return any(
        edge["source_path"] == source
        and edge["target_path"] == target
        and (relation is None or edge["relation"] == relation)
        for edge in report["edges"]
    )


def test_current_repo_provenance_covers_p09_p11_p12_p13() -> None:
    report = build_provenance_graph.build_graph(REPO_ROOT)

    assert report["status"] == "PASS"
    assert report["summary"]["blocking_findings_count"] == 0
    assert {entry["phase_id"]: entry["status"] for entry in report["phase_coverage"]} == {
        "P09_ANALYSIS_REPORTING": "PASS",
        "P11_STABILITY_SOAK": "PASS",
        "P12_SCALE_LADDER_10_30": "PASS",
        "P13_SCALE_LADDER_50_100": "PASS",
    }
    assert has_edge(
        report,
        "artifacts/phases/P09_ANALYSIS_REPORTING/analysis_summary.json",
        "artifacts/phases/P09_ANALYSIS_REPORTING/report_index.json",
    )
    assert has_edge(
        report,
        "artifacts/phases/P11_STABILITY_SOAK/stability_metrics.jsonl",
        "artifacts/phases/P11_STABILITY_SOAK/stability_report.json",
    )
    assert has_edge(
        report,
        "artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/scale_ladder_report.json",
    )
    assert has_edge(
        report,
        "artifacts/phases/P13_SCALE_LADDER_50_100/runtime_timing_breakdown_scale_50.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json",
    )
    assert has_edge(
        report,
        "artifacts/phases/P13_SCALE_LADDER_50_100/setup_timeline_scale_50.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json",
        "setup_timeline_source",
    )
    assert not has_edge(
        report,
        "artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/setup_timeline_scale_50.json",
        "source_artifact",
    )
    runtime_node = node(report, "artifacts/phases/P13_SCALE_LADDER_50_100/runtime_timing_breakdown_scale_50.json")
    assert runtime_node["metadata_status"]["schema"]["status"] == "SKIPPED_WITH_REASON"
    assert report["p14_boundary"]["real_valkey_coverage"] is False


def test_current_repo_provenance_covers_l08_fault_failover_sources() -> None:
    report = build_provenance_graph.build_graph(REPO_ROOT)
    rollup = "artifacts/loop_engineering/reports/fault_failover_scale.json"

    assert report["status"] == "PASS"
    assert node(report, rollup)["artifact_type"] == "fault_failover_scale"
    for source in [
        "artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_fault_30.json",
        "artifacts/phases/P12_SCALE_LADDER_10_30/workload_window_report_30.json",
        "artifacts/phases/P12_SCALE_LADDER_10_30/fault_report_30.json",
        "artifacts/phases/P12_SCALE_LADDER_10_30/failover_report_30.json",
        "artifacts/phases/P12_SCALE_LADDER_10_30/cleanup_report_fault_30.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_fault_50.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/workload_window_report_50.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/fault_report_50.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/failover_report_50.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report_fault_50.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_fault_100.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/workload_window_report_100.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/fault_report_100.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/failover_report_100.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report_fault_100.json",
    ]:
        assert has_edge(report, source, rollup, "fault_failover_source")


def test_current_repo_provenance_edges_are_unique() -> None:
    report = build_provenance_graph.build_graph(REPO_ROOT)

    edge_keys = [
        (
            edge["source_path"],
            edge["target_path"],
            edge["relation"],
            edge["discovered_by"],
            edge["evidence_pointer"],
            edge.get("declared_source_sha256"),
            edge.get("declared_target_sha256"),
        )
        for edge in report["edges"]
    ]
    assert len(edge_keys) == len(set(edge_keys))


def test_current_repo_report_views_are_not_source_of_truth() -> None:
    report = build_provenance_graph.build_graph(REPO_ROOT)
    view_paths = [
        "artifacts/phases/P09_ANALYSIS_REPORTING/report/metrics.csv",
        "artifacts/phases/P09_ANALYSIS_REPORTING/report/missing_metrics.csv",
        "artifacts/phases/P09_ANALYSIS_REPORTING/report/baseline_comparison.csv",
        "artifacts/phases/P09_ANALYSIS_REPORTING/report/metric_chart.svg",
        "artifacts/phases/P09_ANALYSIS_REPORTING/report/report.md",
        "artifacts/phases/P09_ANALYSIS_REPORTING/report/index.html",
    ]
    for path in view_paths:
        view = node(report, path)
        assert view["source_of_truth"] is False
        assert not any(edge["source_path"] == path for edge in report["edges"])


def test_missing_source_artifact_is_blocking(tmp_path: Path) -> None:
    analysis_path = "artifacts/phases/P09_ANALYSIS_REPORTING/analysis_summary.json"
    analysis = minimal_artifact("analysis_summary", "P09_ANALYSIS_REPORTING")
    analysis["findings"] = []
    analysis["missing_metrics"] = []
    analysis["source_artifacts"] = [{"path": "artifacts/phases/P08/missing.json", "sha256": "0" * 64}]
    write_json(tmp_path / analysis_path, analysis)
    write_manifest(tmp_path, [phase("P09_ANALYSIS_REPORTING", [analysis_path])])

    report = build_provenance_graph.build_graph(tmp_path)

    assert report["status"] == "FAIL"
    missing = findings(report, "missing_source_artifact")
    assert missing
    assert missing[0]["blocking"] is True


def test_source_hash_mismatch_is_blocking(tmp_path: Path) -> None:
    source_path = "artifacts/phases/P08/source.json"
    analysis_path = "artifacts/phases/P09_ANALYSIS_REPORTING/analysis_summary.json"
    write_json(tmp_path / source_path, minimal_artifact("phase_summary", "P08_FAILOVER_SPLIT_BRAIN"))
    analysis = minimal_artifact("analysis_summary", "P09_ANALYSIS_REPORTING")
    analysis["findings"] = []
    analysis["missing_metrics"] = []
    analysis["source_artifacts"] = [{"path": source_path, "sha256": "0" * 64}]
    write_json(tmp_path / analysis_path, analysis)
    write_manifest(tmp_path, [phase("P09_ANALYSIS_REPORTING", [analysis_path])])

    report = build_provenance_graph.build_graph(tmp_path)

    assert report["status"] == "FAIL"
    mismatch = findings(report, "source_hash_mismatch")
    assert mismatch
    assert mismatch[0]["blocking"] is True


def test_report_view_used_as_source_is_blocking(tmp_path: Path) -> None:
    view_path = "artifacts/phases/P09_ANALYSIS_REPORTING/report/index.html"
    analysis_path = "artifacts/phases/P09_ANALYSIS_REPORTING/analysis_summary.json"
    write_text(tmp_path / view_path, "<html></html>\n")
    analysis = minimal_artifact("analysis_summary", "P09_ANALYSIS_REPORTING")
    analysis["findings"] = []
    analysis["missing_metrics"] = []
    analysis["source_artifacts"] = [{"path": view_path, "sha256": sha256_file(tmp_path / view_path)}]
    write_json(tmp_path / analysis_path, analysis)
    write_manifest(tmp_path, [phase("P09_ANALYSIS_REPORTING", [analysis_path])])
    graph = build_provenance_graph.ProvenanceGraph(tmp_path)
    graph.report_view_paths.add(view_path)
    report = graph.build()

    assert report["status"] == "FAIL"
    assert findings(report, "report_view_used_as_source")


def test_invalid_required_source_schema_is_blocking(tmp_path: Path) -> None:
    source_path = "artifacts/phases/P08/source.json"
    analysis_path = "artifacts/phases/P09_ANALYSIS_REPORTING/analysis_summary.json"
    report_index_path = "artifacts/phases/P09_ANALYSIS_REPORTING/report_index.json"
    write_json(tmp_path / "schemas/artifact/custom_source.schema.json", {"type": "object", "required": ["required_field"]})
    source = minimal_artifact("custom_source", "P08_FAILOVER_SPLIT_BRAIN")
    write_json(tmp_path / source_path, source)
    analysis = minimal_artifact("analysis_summary", "P09_ANALYSIS_REPORTING")
    analysis["findings"] = []
    analysis["missing_metrics"] = []
    analysis["source_artifacts"] = [{"path": source_path, "sha256": sha256_file(tmp_path / source_path)}]
    write_json(tmp_path / analysis_path, analysis)
    report_index = minimal_artifact("report_index", "P09_ANALYSIS_REPORTING")
    report_index["analysis_path"] = analysis_path
    report_index["reports"] = []
    write_json(tmp_path / report_index_path, report_index)
    write_manifest(tmp_path, [phase("P09_ANALYSIS_REPORTING", [analysis_path, report_index_path])])

    report = build_provenance_graph.build_graph(tmp_path)

    invalid_schema = findings(report, "invalid_source_schema")
    assert report["status"] == "FAIL"
    assert invalid_schema
    assert invalid_schema[0]["blocking"] is True
    assert node(report, source_path)["metadata_status"]["schema"]["status"] == "INVALID"


def test_missing_source_metadata_is_explicit(tmp_path: Path) -> None:
    source_path = "artifacts/phases/P08/source.json"
    analysis_path = "artifacts/phases/P09_ANALYSIS_REPORTING/analysis_summary.json"
    write_json(
        tmp_path / source_path,
        {
            "schema_version": "v1",
            "artifact_type": "source_without_metadata",
            "phase_id": "P08_FAILOVER_SPLIT_BRAIN",
            "run_id": "run",
        },
    )
    analysis = minimal_artifact("analysis_summary", "P09_ANALYSIS_REPORTING")
    analysis["findings"] = []
    analysis["missing_metrics"] = []
    analysis["source_artifacts"] = [{"path": source_path, "sha256": sha256_file(tmp_path / source_path)}]
    write_json(tmp_path / analysis_path, analysis)
    write_manifest(tmp_path, [phase("P09_ANALYSIS_REPORTING", [analysis_path])])

    report = build_provenance_graph.build_graph(tmp_path)

    source_node = node(report, source_path)
    assert source_node["metadata_status"]["producer"]["status"] == "MISSING"
    assert source_node["metadata_status"]["status"]["status"] == "MISSING"
    missing_metadata = findings(report, "missing_metadata")
    assert missing_metadata
    assert all(finding["blocking"] is False for finding in missing_metadata)


def test_cycle_detection_is_blocking(tmp_path: Path) -> None:
    report_index = "artifacts/phases/P09_ANALYSIS_REPORTING/report_index.json"
    write_json(
        tmp_path / report_index,
        {
            **minimal_artifact("report_index", "P09_ANALYSIS_REPORTING"),
            "analysis_path": report_index,
            "reports": [],
        },
    )
    write_manifest(tmp_path, [phase("P09_ANALYSIS_REPORTING", [report_index])])

    report = build_provenance_graph.build_graph(tmp_path)

    assert report["status"] == "FAIL"
    assert findings(report, "graph_cycle")
