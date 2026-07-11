from __future__ import annotations

import importlib.util
import csv
import json
from pathlib import Path
from types import ModuleType

from valkey_scale_lab.cli import main
from valkey_scale_lab.report.final import build_final_goal_loop_report


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, Path("scripts") / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_minimal_runtime_artifacts(out_dir: Path) -> None:
    (out_dir / "cleanup_report.json").write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "artifact_type": "cleanup_report",
                "phase_id": "P26_FINAL_REPORT_REGRESSION",
                "run_id": "run",
                "created_at": "2026-07-03T00:00:00Z",
                "producer": {"name": "test", "version": "test"},
                "status": "PASS",
                "resources_remaining": [],
                "cleanup_actions": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "valkey_e2e_evidence.json").write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "artifact_type": "valkey_e2e_evidence",
                "phase_id": "P26_FINAL_REPORT_REGRESSION",
                "run_id": "run",
                "created_at": "2026-07-03T00:00:00Z",
                "producer": {"name": "test", "version": "test"},
                "status": "PASS",
                "real_valkey": True,
                "valkey_version_prefix_required": "9.1.",
                "probe_result": "PASS",
                "nodes_observed": 6,
                "cluster_state_observed": "ok",
                "data_path_result": "PASS",
                "valkey_versions": ["9.1.0"],
                "probes": [{"logical_id": "node-0", "host": "127.0.0.1", "port": 7000, "status": "PASS"}],
                "cleanup": {"status": "PASS"},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_final_report_builder_writes_required_outputs(tmp_path: Path) -> None:
    out_dir = tmp_path / "P26_FINAL_REPORT_REGRESSION"

    index = build_final_goal_loop_report("artifacts/phases", out_dir)

    assert index["derivation_policy"]["artifact_only"] is True
    assert index["derivation_policy"]["log_parsing"] is False
    assert (out_dir / "final_report_index.json").exists()
    assert (out_dir / "report_index.json").exists()
    assert (out_dir / "reports" / "final_goal_loop_report.md").exists()
    assert (out_dir / "exports" / "management_ops_matrix.csv").exists()
    assert (out_dir / "regression" / "coverage_golden_summary.json").exists()
    source_paths = [record["path"] for record in index["source_artifacts"]]
    assert source_paths
    assert all(path.endswith((".json", ".jsonl")) for path in source_paths)
    assert not any(path.endswith((".md", ".csv", ".html", ".log")) for path in source_paths)


def test_final_report_cli_mode_preserves_legacy_report_contract(tmp_path: Path) -> None:
    final_out = tmp_path / "final"

    assert main(["report", "--kind", "final-goal-loop", "--input", "artifacts/phases", "--out-dir", str(final_out)]) == 0
    assert (final_out / "final_report_index.json").exists()

    summary_out = tmp_path / "summary"
    assert main(["report", "--out-dir", str(summary_out)]) == 2


def test_final_report_assertion_rejects_missing_required_management_row(tmp_path: Path) -> None:
    out_dir = tmp_path / "P26_FINAL_REPORT_REGRESSION"
    build_final_goal_loop_report("artifacts/phases", out_dir)
    final_index = json.loads((out_dir / "final_report_index.json").read_text(encoding="utf-8"))
    write_minimal_runtime_artifacts(out_dir)
    csv_path = out_dir / "exports" / "management_ops_matrix.csv"
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = [row for row in csv.DictReader(f) if row["operation_name"] != "rolling_restart_primary_safe"]
        fieldnames = list(rows[0].keys())
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    # Keep index hash mismatch out of the assertion target so the row loss is directly observable.
    for record in final_index["exports"]:
        if record["path"].endswith("management_ops_matrix.csv"):
            record["sha256"] = load_script("assert_final_report_regression").sha256_file(csv_path)
    (out_dir / "final_report_index.json").write_text(json.dumps(final_index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "report_index.json").write_text(json.dumps(final_index, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    assertion = load_script("assert_final_report_regression")
    errors = assertion.assert_final_report(out_dir)

    assert any("management report missing rows" in error for error in errors)


def test_final_report_assertion_rejects_two_sample_200_rung(tmp_path: Path) -> None:
    out_dir = tmp_path / "P26_FINAL_REPORT_REGRESSION"
    build_final_goal_loop_report("artifacts/phases", out_dir)
    write_minimal_runtime_artifacts(out_dir)
    csv_path = out_dir / "exports" / "failover_latency_curve.csv"
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())
    for row in rows:
        if row["rung"] == "200" and row["metric"] == "cluster_recovery_latency_ms":
            row["sample_count"] = "2"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    final_index = json.loads((out_dir / "final_report_index.json").read_text(encoding="utf-8"))
    for record in final_index["exports"]:
        if record["path"].endswith("failover_latency_curve.csv"):
            record["sha256"] = load_script("assert_final_report_regression").sha256_file(csv_path)
    (out_dir / "final_report_index.json").write_text(json.dumps(final_index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "report_index.json").write_text(json.dumps(final_index, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    assertion = load_script("assert_final_report_regression")
    errors = assertion.assert_final_report(out_dir)

    assert any("failover rung 200 requires at least 3 samples" in error for error in errors)
