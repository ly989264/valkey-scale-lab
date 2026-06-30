from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SVG_NS = "{http://www.w3.org/2000/svg}"


def render(out_dir: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/render_audit_report.py",
            "--input-dir",
            "artifacts/loop_engineering/reports",
            "--out-dir",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def svg_text(path: Path) -> str:
    root = ET.parse(path).getroot()
    return " ".join((node.text or "") for node in root.iter(f"{SVG_NS}text"))


def test_coverage_heatmap_svg_has_one_semantic_cell_per_matrix_entry(tmp_path: Path) -> None:
    render(tmp_path)
    source = json.loads((REPO_ROOT / "artifacts/loop_engineering/reports/coverage_matrix.json").read_text(encoding="utf-8"))
    root = ET.parse(tmp_path / "coverage_heatmap.svg").getroot()
    cells = [node for node in root.iter(f"{SVG_NS}rect") if node.attrib.get("class") == "coverage-cell"]

    assert len(cells) == len(source["entries"])
    assert {cell.attrib["data-layer"] for cell in cells} == set(source["layers"])
    assert {cell.attrib["data-surface"] for cell in cells} == set(source["surfaces"])
    assert {cell.attrib["data-status"] for cell in cells} == {entry["status"] for entry in source["entries"]}
    dry_cells = [cell for cell in cells if cell.attrib["data-layer"] == "1000-dry-run"]
    assert dry_cells
    assert all(cell.attrib["data-real-valkey-coverage"] == "false" for cell in dry_cells)
    assert all(cell.attrib["data-dry-run-only"] == "true" for cell in dry_cells)


def test_scale_ladder_svg_renders_p13_real_rungs_and_p14_dry_run_boundary(tmp_path: Path) -> None:
    render(tmp_path)
    text = svg_text(tmp_path / "scale_ladder.svg")

    assert "50 nodes" in text
    assert "100 nodes" in text
    assert "real Valkey" in text
    assert "P14 opt-in dry-run only" in text
    assert "1000 real nodes" not in text


def test_p13_timing_waterfall_svg_renders_required_components_and_missing_diagnostic(tmp_path: Path) -> None:
    render(tmp_path)
    root = ET.parse(tmp_path / "p13_timing_waterfall.svg").getroot()
    bars = [node for node in root.iter(f"{SVG_NS}rect") if node.attrib.get("class") == "timing-bar"]
    components = {bar.attrib["data-component"] for bar in bars}

    assert {
        "setup_command_wall_seconds",
        "cluster_create_duration_seconds",
        "replica_config_duration_seconds",
        "wrapper_probe_duration_seconds",
        "final_full_probe_duration_seconds",
        "cleanup_command_wall_seconds",
        "artifact_write_seconds",
    } <= components
    assert {bar.attrib["data-node-count"] for bar in bars} == {"50", "100"}
    assert "diagnostic_full_probe_duration_seconds MISSING" in svg_text(tmp_path / "p13_timing_waterfall.svg")
