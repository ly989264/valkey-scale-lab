from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))

from schema_validator import load_json, validate


SCHEMA = Path("schemas/artifact/provenance_graph.schema.json")
WORKFLOW = Path(".github/workflows/github-coverage-gates.yml")


def test_provenance_graph_cli_generates_schema_valid_graph(tmp_path: Path) -> None:
    out = tmp_path / "provenance_graph.json"
    result = subprocess.run(
        [sys.executable, "scripts/build_provenance_graph.py", "--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    graph = json.loads(out.read_text(encoding="utf-8"))
    assert validate(graph, load_json(SCHEMA)) == []
    assert graph["status"] == "PASS"
    assert graph["summary"]["blocking_findings_count"] == 0


def test_provenance_graph_current_repo_invariants(tmp_path: Path) -> None:
    out = tmp_path / "provenance_graph.json"
    subprocess.run([sys.executable, "scripts/build_provenance_graph.py", "--out", str(out)], check=True)
    graph = json.loads(out.read_text(encoding="utf-8"))

    assert graph["scope"]["target_phase_ids"] == [
        "P09_ANALYSIS_REPORTING",
        "P11_STABILITY_SOAK",
        "P12_SCALE_LADDER_10_30",
        "P13_SCALE_LADDER_50_100",
    ]
    assert graph["p14_boundary"]["real_valkey_coverage"] is False
    report_views = [node for node in graph["nodes"] if node["source_of_truth"] is False]
    assert report_views
    assert all(node["artifact_role"] in {"html_report", "markdown_report", "visualization", "csv_view"} for node in report_views)


def test_github_coverage_workflow_runs_static_provenance_gate() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required_commands = [
        "python3 scripts/build_provenance_graph.py --out artifacts/loop_engineering/reports/provenance_graph.json",
        (
            "python3 scripts/validate_json_schema.py --schema schemas/artifact/provenance_graph.schema.json "
            "--instance artifacts/loop_engineering/reports/provenance_graph.json"
        ),
        "python3 -m pytest -q tests/provenance tests/ci/test_provenance_graph_gate.py",
    ]
    for command in required_commands:
        assert command in text
    forbidden_tokens = [
        "P14_SCALE_1000_OPTIN_DRYRUN",
        "VSLAB_ALLOW_1000_DRYRUN",
        "scripts/valkey_e2e_gate.py",
        "scripts/fault_safety_gate.py",
        "scripts/fault_failover_gate.py",
    ]
    for token in forbidden_tokens:
        assert token not in text
