#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any


STAGE_ID = "L05_REPORTING_V2_FOR_AUDIT_RESULTS"
RUN_ID = "L05_REPORTING_V2_FOR_AUDIT_RESULTS-report-v1"
CREATED_AT = "2026-06-30T00:00:00Z"
RENDERED_SUFFIXES = {".html", ".csv", ".svg", ".md"}
STATUS_COLORS = {
    "COVERED": "#2f6f4e",
    "PASS": "#2f6f4e",
    "MISSING": "#b54708",
    "SKIPPED_WITH_REASON": "#5f6b7a",
    "NO_BASELINE_YET": "#7a5c00",
    "FAIL": "#b42318",
}


class ReportRenderError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportRenderError(f"source artifact missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReportRenderError(f"source artifact invalid JSON: {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def bool_text(value: Any) -> str:
    return "true" if value is True else "false"


def status_color(status: str, *, dry_run: bool = False) -> str:
    if dry_run:
        return "#7f56d9"
    return STATUS_COLORS.get(status, "#8a8f98")


def rendered_source_path(path_text: str) -> bool:
    return Path(path_text).suffix.lower() in RENDERED_SUFFIXES


def validate_metric_sources(metric_catalog: dict[str, Any]) -> None:
    for metric in metric_catalog.get("metrics", []):
        if not isinstance(metric, dict):
            continue
        status = metric.get("value_status")
        source_artifact = str(metric.get("source_artifact", ""))
        measured = status in {"MEASURED", "PASS"} and metric.get("value") is not None
        if measured and rendered_source_path(source_artifact):
            raise ReportRenderError(
                f"rendered view cannot be a measured metric source: {metric.get('name')} -> {source_artifact}"
            )


def source_record(root: Path, path: Path, payload: Any | None = None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    return {
        "path": rel(root, path),
        "sha256": sha256_file(path),
        "artifact_type": str(data.get("artifact_type", path.suffix.lstrip(".") or "artifact")),
        "status": str(data.get("status", "PRESENT")),
        "source_of_truth": True,
    }


def report_record(root: Path, path: Path, role: str, sources: list[str]) -> dict[str, Any]:
    return {
        "path": rel(root, path),
        "sha256": sha256_file(path),
        "role": role,
        "source_of_truth": False,
        "source_artifacts": sources,
    }


def write_coverage_csv(path: Path, coverage: dict[str, Any]) -> Path:
    entries = sorted(
        coverage.get("entries", []),
        key=lambda item: (
            coverage.get("layers", []).index(item.get("layer")) if item.get("layer") in coverage.get("layers", []) else 999,
            coverage.get("surfaces", []).index(item.get("surface")) if item.get("surface") in coverage.get("surfaces", []) else 999,
        ),
    )
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "layer",
                "surface",
                "status",
                "evidence_class",
                "metric_count",
                "real_valkey_coverage",
                "dry_run_only",
                "reason",
                "source_artifacts",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        for entry in entries:
            writer.writerow(
                {
                    "layer": entry.get("layer", ""),
                    "surface": entry.get("surface", ""),
                    "status": entry.get("status", ""),
                    "evidence_class": entry.get("evidence_class", ""),
                    "metric_count": entry.get("metric_count", 0),
                    "real_valkey_coverage": bool_text(entry.get("real_valkey_coverage")),
                    "dry_run_only": bool_text(entry.get("dry_run_only")),
                    "reason": entry.get("reason", ""),
                    "source_artifacts": ";".join(entry.get("source_artifacts", []) or []),
                }
            )
    return path


def missing_reason(metric: dict[str, Any]) -> str:
    semantics = metric.get("missing_semantics")
    if isinstance(semantics, dict) and semantics.get("reason"):
        return str(semantics["reason"])
    return str(metric.get("reason") or metric.get("status_reason") or "explicit missing/skipped metric")


def write_missing_metrics_csv(path: Path, catalog: dict[str, Any]) -> Path:
    rows = [
        metric
        for metric in catalog.get("metrics", [])
        if isinstance(metric, dict) and metric.get("value_status") in {"MISSING", "SKIPPED_WITH_REASON", "NO_BASELINE_YET"}
    ]
    rows.sort(key=lambda item: (str(item.get("value_status")), str(item.get("name"))))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "metric",
                "status",
                "reason",
                "impact",
                "source_artifact",
                "source_pointer",
                "evidence_layer",
                "dry_run_only",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        for metric in rows:
            writer.writerow(
                {
                    "metric": metric.get("name", "MISSING"),
                    "status": metric.get("value_status", "MISSING"),
                    "reason": missing_reason(metric),
                    "impact": metric.get("impact") or metric.get("missing_semantics", {}).get("impact", ""),
                    "source_artifact": metric.get("source_artifact", ""),
                    "source_pointer": metric.get("source_pointer", ""),
                    "evidence_layer": metric.get("evidence_layer", ""),
                    "dry_run_only": bool_text(metric.get("dry_run_only")),
                }
            )
    return path


def write_coverage_heatmap(path: Path, coverage: dict[str, Any]) -> Path:
    layers = list(coverage.get("layers", []))
    surfaces = list(coverage.get("surfaces", []))
    entries = {(entry.get("layer"), entry.get("surface")): entry for entry in coverage.get("entries", [])}
    cell_w = 92
    cell_h = 34
    left = 150
    top = 82
    width = left + cell_w * len(surfaces) + 24
    height = top + cell_h * len(layers) + 86
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="16" y="30" font-size="18" font-weight="700">Coverage Matrix</text>',
        '<text x="16" y="54" font-size="12">Cells are rendered from coverage_matrix.json</text>',
    ]
    for col, surface in enumerate(surfaces):
        x = left + col * cell_w + 5
        parts.append(f'<text x="{x}" y="74" font-size="10">{escape(surface)}</text>')
    for row, layer in enumerate(layers):
        y = top + row * cell_h
        parts.append(f'<text x="16" y="{y + 22}" font-size="12">{escape(layer)}</text>')
        for col, surface in enumerate(surfaces):
            entry = entries.get((layer, surface), {})
            status = str(entry.get("status", "MISSING"))
            dry_run = entry.get("dry_run_only") is True
            x = left + col * cell_w
            color = status_color(status, dry_run=dry_run)
            parts.append(
                '<rect class="coverage-cell" '
                f'x="{x}" y="{y}" width="{cell_w - 6}" height="{cell_h - 6}" rx="3" '
                f'fill="{color}" data-layer="{escape(layer)}" data-surface="{escape(surface)}" '
                f'data-status="{escape(status)}" data-evidence-class="{escape(entry.get("evidence_class", ""))}" '
                f'data-real-valkey-coverage="{bool_text(entry.get("real_valkey_coverage"))}" '
                f'data-dry-run-only="{bool_text(entry.get("dry_run_only"))}"/>'
            )
            parts.append(f'<text x="{x + 6}" y="{y + 19}" font-size="10" fill="#ffffff">{escape(status[:8])}</text>')
    legend_y = height - 52
    for idx, (status, color) in enumerate([("COVERED", "#2f6f4e"), ("MISSING", "#b54708"), ("SKIPPED_WITH_REASON", "#5f6b7a"), ("dry-run", "#7f56d9")]):
        x = 16 + idx * 180
        parts.append(f'<rect x="{x}" y="{legend_y}" width="14" height="14" fill="{color}"/>')
        parts.append(f'<text x="{x + 20}" y="{legend_y + 12}" font-size="12">{escape(status)}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def write_scale_ladder_svg(path: Path, scale_report: dict[str, Any], p13_audit: dict[str, Any]) -> Path:
    rungs = sorted(scale_report.get("rungs", []), key=lambda item: item.get("node_count", 0))
    width = 720
    height = 260
    max_nodes = max([rung.get("node_count", 0) for rung in rungs] + [1000])
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="20" y="30" font-size="18" font-weight="700">Scale Ladder</text>',
        '<text x="20" y="54" font-size="12">P13 real rungs and P14 opt-in boundary from JSON artifacts</text>',
    ]
    y = 92
    for rung in rungs:
        nodes = int(rung.get("node_count", 0))
        bar_w = max(8, int(420 * nodes / max_nodes))
        status = str(rung.get("status", "MISSING"))
        parts.append(f'<text x="20" y="{y + 18}" font-size="13">{nodes} nodes</text>')
        parts.append(
            f'<rect class="scale-rung" x="120" y="{y}" width="{bar_w}" height="24" '
            f'fill="#2f6f4e" data-node-count="{nodes}" data-status="{escape(status)}" data-real-valkey="true"/>'
        )
        parts.append(f'<text x="{130 + bar_w}" y="{y + 18}" font-size="12">PASS real Valkey</text>')
        y += 48
    p14 = p13_audit.get("p14_boundary", {})
    parts.append('<text x="20" y="214" font-size="13">1000 planned nodes</text>')
    parts.append(
        '<rect class="scale-rung" x="120" y="196" width="420" height="24" fill="#7f56d9" '
        f'data-node-count="1000" data-status="{escape(p14.get("status", "SKIPPED_WITH_REASON"))}" '
        'data-real-valkey="false" data-dry-run-only="true"/>'
    )
    parts.append('<text x="550" y="214" font-size="12">P14 opt-in dry-run only</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def timing_components(summary: dict[str, Any]) -> list[tuple[str, Any]]:
    return [
        ("setup_command_wall_seconds", summary.get("setup_command_wall_seconds")),
        ("cluster_create_duration_seconds", summary.get("cluster_create_duration_seconds")),
        ("replica_config_duration_seconds", summary.get("replica_config_duration_seconds")),
        ("wrapper_probe_duration_seconds", summary.get("wrapper_probe_duration_seconds")),
        ("final_full_probe_duration_seconds", summary.get("final_full_probe_duration_seconds")),
        ("cleanup_command_wall_seconds", summary.get("cleanup_command_wall_seconds")),
        ("artifact_write_seconds", summary.get("artifact_write_seconds")),
    ]


def write_timing_waterfall_svg(path: Path, timings: list[dict[str, Any]]) -> Path:
    numeric_values = [
        float(value)
        for timing in timings
        for _, value in timing_components(timing.get("summary", {}))
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    max_value = max(numeric_values + [1.0])
    row_h = 30
    width = 760
    height = 92 + row_h * sum(len(timing_components(t.get("summary", {}))) + 2 for t in timings)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="20" y="30" font-size="18" font-weight="700">P13 Timing Waterfall</text>',
        '<text x="20" y="54" font-size="12">Timing values rendered from p13_timing_breakdown JSON artifacts</text>',
    ]
    y = 88
    for timing in sorted(timings, key=lambda item: item.get("node_count", 0)):
        node_count = int(timing.get("node_count", 0))
        parts.append(f'<text x="20" y="{y}" font-size="14" font-weight="700">{node_count} nodes</text>')
        y += 20
        for name, value in timing_components(timing.get("summary", {})):
            parts.append(f'<text x="40" y="{y + 16}" font-size="11">{escape(name)}</text>')
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                bar_w = max(2, int(460 * float(value) / max_value))
                parts.append(
                    f'<rect class="timing-bar" x="260" y="{y}" width="{bar_w}" height="18" fill="#2f6f4e" '
                    f'data-node-count="{node_count}" data-component="{escape(name)}" data-value-seconds="{value}"/>'
                )
                parts.append(f'<text x="{270 + bar_w}" y="{y + 14}" font-size="11">{value:.6g}s</text>')
            else:
                parts.append(
                    f'<text x="260" y="{y + 14}" font-size="11" data-node-count="{node_count}" data-component="{escape(name)}" data-status="MISSING">MISSING</text>'
                )
            y += row_h
        diagnostic = timing.get("summary", {}).get("diagnostic_full_probe_duration_seconds")
        if diagnostic == "MISSING":
            parts.append(
                f'<text x="40" y="{y + 16}" font-size="11" data-node-count="{node_count}" data-component="diagnostic_full_probe_duration_seconds" data-status="MISSING">diagnostic_full_probe_duration_seconds MISSING</text>'
            )
            y += row_h
        y += 8
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def write_index_html(path: Path, sources: dict[str, dict[str, Any]], reports: list[Path]) -> Path:
    audit = sources["audit_report"]
    catalog = sources["metric_catalog"]
    coverage = sources["coverage_matrix"]
    p13 = sources["p13_p14_scale_audit"]
    small_real = sources.get("small_real_parity_audit", {})
    scale_build = sources.get("scale_build_metrics", {})
    fault_failover = sources.get("fault_failover_scale", {})
    stability_soak = sources.get("stability_soak_metrics", {})
    provenance = sources.get("provenance_graph", {})
    root_commit_sha = str(provenance.get("root_commit_sha", "MISSING"))
    source_rows = "\n".join(
        f"<tr><td><code>{escape(record['path'])}</code></td><td>{escape(record['artifact_type'])}</td><td>{escape(record['status'])}</td><td><code>{escape(record['sha256'][:12])}</code></td></tr>"
        for record in sources["source_records"]
    )
    report_links = "\n".join(f'<li><a href="{escape(report.name)}">{escape(report.name)}</a></li>' for report in reports)
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Valkey Scale Lab Audit Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 28px; color: #202124; }}
    table {{ border-collapse: collapse; width: 100%; margin: 14px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 7px; text-align: left; vertical-align: top; }}
    th {{ background: #f6f8fa; }}
    code {{ background: #f6f8fa; padding: 1px 3px; }}
  </style>
</head>
<body>
  <h1>Valkey Scale Lab Audit Report</h1>
  <p>Root commit SHA: <code>{escape(root_commit_sha)}</code></p>
  <p>Status: <code>{escape(audit.get("status"))}</code>. Metrics: <code>{escape(catalog.get("summary", {}).get("metric_count"))}</code>. Coverage cells: <code>{escape(coverage.get("summary", {}).get("entry_count"))}</code>.</p>
  <p>P13 real rungs: <code>{escape(p13.get("summary", {}).get("p13_real_evidence_count"))}</code>. P14 opt-in dry-run: <code>{escape(p13.get("summary", {}).get("p14_dry_run_only"))}</code>.</p>
  <p>Small-real parity surfaces: <code>{escape(small_real.get("summary", {}).get("surface_count", "MISSING"))}</code>. Missing metrics: <code>{escape(small_real.get("summary", {}).get("missing_count", "MISSING"))}</code>. Skipped metrics: <code>{escape(small_real.get("summary", {}).get("skipped_count", "MISSING"))}</code>.</p>
  <p>Scale build rungs: <code>{escape(scale_build.get("summary", {}).get("canonical_node_counts", "MISSING"))}</code>. Measured build metrics: <code>{escape(scale_build.get("summary", {}).get("measured_metric_count", "MISSING"))}</code>. Missing build metrics: <code>{escape(scale_build.get("summary", {}).get("missing_metric_count", "MISSING"))}</code>.</p>
  <p>Fault/failover rungs: <code>{escape(fault_failover.get("summary", {}).get("canonical_node_counts", "MISSING"))}</code>. Real rungs: <code>{escape(fault_failover.get("summary", {}).get("real_valkey_rung_count", "MISSING"))}</code>. Missing metrics: <code>{escape(fault_failover.get("summary", {}).get("missing_metric_count", "MISSING"))}</code>.</p>
  <p>Stability soak profiles: <code>{escape(stability_soak.get("summary", {}).get("required_node_counts", "MISSING"))}</code>. Measured profiles: <code>{escape(stability_soak.get("summary", {}).get("measured_profile_count", "MISSING"))}</code>. Resource-aware profiles: <code>{escape(stability_soak.get("summary", {}).get("resource_aware_profile_count", "MISSING"))}</code>.</p>
  <h2>Rendered Views</h2>
  <ul>{report_links}</ul>
  <h2>Source Artifacts</h2>
  <table><thead><tr><th>Path</th><th>Type</th><th>Status</th><th>SHA256</th></tr></thead><tbody>{source_rows}</tbody></table>
  <h2>Visualizations</h2>
  <img src="coverage_heatmap.svg" alt="Coverage heatmap">
  <img src="scale_ladder.svg" alt="Scale ladder">
  <img src="p13_timing_waterfall.svg" alt="P13 timing waterfall">
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")
    return path


def build_report(root: Path, input_dir: Path, out_dir: Path) -> dict[str, Any]:
    input_dir = input_dir if input_dir.is_absolute() else root / input_dir
    out_dir = out_dir if out_dir.is_absolute() else root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    source_paths = {
        "audit_report": input_dir / "audit_report.json",
        "provenance_graph": input_dir / "provenance_graph.json",
        "metric_catalog": input_dir / "metric_catalog.json",
        "coverage_matrix": input_dir / "coverage_matrix.json",
        "p13_p14_scale_audit": input_dir / "p13_p14_scale_audit.json",
        "small_real_parity_audit": input_dir / "small_real_parity_audit.json",
        "scale_build_metrics": input_dir / "scale_build_metrics.json",
        "fault_failover_scale": input_dir / "fault_failover_scale.json",
        "stability_soak_metrics": input_dir / "stability_soak_metrics.json",
        "scale_ladder_report": root / "artifacts/phases/P13_SCALE_LADDER_50_100/scale_ladder_report.json",
        "p13_timing_50": root / "artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json",
        "p13_timing_100": root / "artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_100.json",
    }
    payloads = {name: load_json(path) for name, path in source_paths.items()}
    validate_metric_sources(payloads["metric_catalog"])

    provenance_out = out_dir / "provenance_graph.json"
    if source_paths["provenance_graph"].resolve() != provenance_out.resolve():
        shutil.copy2(source_paths["provenance_graph"], provenance_out)

    reports = [
        write_coverage_csv(out_dir / "coverage_matrix.csv", payloads["coverage_matrix"]),
        write_missing_metrics_csv(out_dir / "missing_metrics.csv", payloads["metric_catalog"]),
        write_coverage_heatmap(out_dir / "coverage_heatmap.svg", payloads["coverage_matrix"]),
        write_scale_ladder_svg(out_dir / "scale_ladder.svg", payloads["scale_ladder_report"], payloads["p13_p14_scale_audit"]),
        write_timing_waterfall_svg(out_dir / "p13_timing_waterfall.svg", [payloads["p13_timing_50"], payloads["p13_timing_100"]]),
    ]
    reports.append(write_index_html(out_dir / "index.html", {**payloads, "source_records": []}, reports))

    source_records = [source_record(root, path, payloads[name]) for name, path in source_paths.items()]
    payloads["source_records"] = source_records
    write_index_html(out_dir / "index.html", {**payloads, "source_records": source_records}, reports[:-1] + [out_dir / "index.html"])
    report_paths = reports[:-1] + [out_dir / "index.html"]
    report_sources = [record["path"] for record in source_records]
    report_roles = {
        ".html": "html_report",
        ".csv": "csv_view",
        ".svg": "visualization",
        ".json": "json_source",
    }
    index = {
        "schema_version": "v1",
        "artifact_type": "loop_report_index",
        "stage_id": STAGE_ID,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": {"name": "scripts/render_audit_report.py", "version": "v1"},
        "status": "PASS",
        "source_of_truth": False,
        "source_artifacts": source_records,
        "reports": [
            report_record(root, path, report_roles.get(path.suffix, "json_index"), report_sources)
            for path in report_paths
        ],
    }
    index_path = out_dir / "report_index.json"
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description="Render loop-engineering audit report views")
    parser.add_argument("--root", default=".")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        index = build_report(root, Path(args.input_dir), Path(args.out_dir))
    except ReportRenderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"PASS loop_report {len(index['reports'])} reports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
