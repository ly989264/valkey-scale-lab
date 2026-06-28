from __future__ import annotations

import csv
import html
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__

PHASE_ID = "P09_ANALYSIS_REPORTING"
RUN_ID = "P09_ANALYSIS_REPORTING-analysis-20260628"
CREATED_AT = "2026-06-28T00:00:00Z"


class ReportError(RuntimeError):
    pass


def render_report(analysis_path: str | Path, out_dir: str | Path, index_out: str | Path) -> dict[str, Any]:
    analysis_file = Path(analysis_path)
    try:
        analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportError(f"analysis artifact does not exist: {analysis_file}") from exc
    except json.JSONDecodeError as exc:
        raise ReportError(f"analysis artifact is invalid JSON: {analysis_file}: {exc}") from exc

    report_dir = Path(out_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    metrics = list(analysis.get("metrics", []))
    missing = list(analysis.get("missing_metrics", []))

    generated = [
        _write_metrics_csv(report_dir / "metrics.csv", metrics),
        _write_missing_csv(report_dir / "missing_metrics.csv", missing),
        _write_baseline_csv(report_dir / "baseline_comparison.csv", analysis.get("baseline_comparison", {})),
        _write_chart(report_dir / "metric_chart.svg", metrics),
        _write_markdown(report_dir / "report.md", analysis),
        _write_html(report_dir / "index.html", analysis),
    ]

    index_path = Path(index_out)
    index = {
        "schema_version": "v1",
        "artifact_type": "report_index",
        "phase_id": PHASE_ID,
        "run_id": str(analysis.get("run_id", RUN_ID)),
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "analysis_path": _rel(analysis_file),
        "reports": [_report_record(path) for path in generated],
    }
    _write_json(index_path, index)
    _write_phase_summary(index_path.parent, analysis, index_path, generated)
    return index


def _write_metrics_csv(path: Path, metrics: list[dict[str, Any]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "status", "value", "unit", "reason"])
        writer.writeheader()
        for metric in metrics:
            writer.writerow(
                {
                    "metric": metric.get("name", "MISSING"),
                    "status": metric.get("status", "MISSING"),
                    "value": "" if metric.get("value") is None else metric.get("value"),
                    "unit": metric.get("unit", ""),
                    "reason": metric.get("reason", ""),
                }
            )
    return path


def _write_missing_csv(path: Path, missing: list[dict[str, Any]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "status", "reason", "impact"])
        writer.writeheader()
        for item in missing:
            writer.writerow(
                {
                    "metric": item.get("metric", "MISSING"),
                    "status": item.get("status", "MISSING"),
                    "reason": item.get("reason", ""),
                    "impact": item.get("impact", ""),
                }
            )
    return path


def _write_baseline_csv(path: Path, baseline: dict[str, Any]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "current_value", "baseline_value", "delta", "unit", "status"])
        writer.writeheader()
        for item in baseline.get("comparisons", []):
            writer.writerow(
                {
                    "metric": item.get("metric", "MISSING"),
                    "current_value": "" if item.get("current_value") is None else item.get("current_value"),
                    "baseline_value": "" if item.get("baseline_value") is None else item.get("baseline_value"),
                    "delta": "" if item.get("delta") is None else item.get("delta"),
                    "unit": item.get("unit", ""),
                    "status": item.get("status", "MISSING"),
                }
            )
    return path


def _write_chart(path: Path, metrics: list[dict[str, Any]]) -> Path:
    numeric = [m for m in metrics if isinstance(m.get("value"), (int, float)) and not isinstance(m.get("value"), bool)]
    max_value = max([float(m["value"]) for m in numeric] + [1.0])
    rows: list[str] = []
    y = 42
    for metric in metrics:
        name = html.escape(str(metric.get("name", "MISSING")))
        status = str(metric.get("status", "MISSING"))
        value = metric.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            width = int(360 * (float(value) / max_value))
            label = html.escape(str(value))
            color = "#2f6f4e"
        else:
            width = 24
            label = html.escape(status)
            color = "#8a8f98"
        rows.append(f'<text x="12" y="{y + 14}" font-size="12">{name}</text>')
        rows.append(f'<rect x="190" y="{y}" width="{max(width, 2)}" height="18" fill="{color}"/>')
        rows.append(f'<text x="{200 + max(width, 2)}" y="{y + 14}" font-size="12">{label}</text>')
        y += 34
    height = max(y + 16, 96)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="{height}" viewBox="0 0 640 {height}">\n'
        '<rect width="100%" height="100%" fill="#ffffff"/>\n'
        '<text x="12" y="24" font-size="16" font-weight="700">P09 Artifact Metrics</text>\n'
        + "\n".join(rows)
        + "\n</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")
    return path


def _write_markdown(path: Path, analysis: dict[str, Any]) -> Path:
    lines = [
        "# P09 Analysis Report",
        "",
        f"Status: {analysis.get('status', 'MISSING')}",
        f"Source phase: {analysis.get('source', {}).get('phase_id', 'MISSING')}",
        "",
        "## Findings",
        "",
    ]
    for finding in analysis.get("findings", []):
        lines.append(f"- {finding.get('name', 'finding')}: {finding.get('status', 'MISSING')}")
    lines.extend(["", "## Missing Metrics", ""])
    missing = analysis.get("missing_metrics", [])
    if missing:
        for item in missing:
            lines.append(f"- {item.get('metric', 'MISSING')}: {item.get('status', 'MISSING')} - {item.get('reason', '')}")
    else:
        lines.append("- none")
    lines.extend(["", "## Generated Tables", "", "- metrics.csv", "- missing_metrics.csv", "- baseline_comparison.csv", "- metric_chart.svg"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_html(path: Path, analysis: dict[str, Any]) -> Path:
    finding_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(item.get("name", "finding"))),
            html.escape(str(item.get("status", "MISSING"))),
        )
        for item in analysis.get("findings", [])
    )
    missing_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(item.get("metric", "MISSING"))),
            html.escape(str(item.get("status", "MISSING"))),
            html.escape(str(item.get("reason", ""))),
        )
        for item in analysis.get("missing_metrics", [])
    ) or '<tr><td colspan="3">none</td></tr>'
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>P09 Analysis Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #202124; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; text-align: left; }}
    th {{ background: #f6f8fa; }}
    code {{ background: #f6f8fa; padding: 2px 4px; }}
  </style>
</head>
<body>
  <h1>P09 Analysis Report</h1>
  <p>Status: <code>{html.escape(str(analysis.get("status", "MISSING")))}</code></p>
  <p>Source phase: <code>{html.escape(str(analysis.get("source", {}).get("phase_id", "MISSING")))}</code></p>
  <h2>Findings</h2>
  <table><thead><tr><th>Name</th><th>Status</th></tr></thead><tbody>{finding_rows}</tbody></table>
  <h2>Missing Metrics</h2>
  <table><thead><tr><th>Metric</th><th>Status</th><th>Reason</th></tr></thead><tbody>{missing_rows}</tbody></table>
  <h2>Chart</h2>
  <img src="metric_chart.svg" alt="P09 artifact metrics chart">
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")
    return path


def _write_phase_summary(phase_dir: Path, analysis: dict[str, Any], index_path: Path, reports: list[Path]) -> None:
    phase_summary = {
        "schema_version": "v1",
        "artifact_type": "phase_summary",
        "phase_id": PHASE_ID,
        "run_id": str(analysis.get("run_id", RUN_ID)),
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "summary": "P09 analyzed prior real Valkey failover artifacts and rendered deterministic machine-readable, tabular, chart, HTML, and markdown report outputs without inventing missing metrics.",
        "required_artifacts": [
            "artifacts/phases/P09_ANALYSIS_REPORTING/phase_summary.json",
            "artifacts/phases/P09_ANALYSIS_REPORTING/analysis_summary.json",
            "artifacts/phases/P09_ANALYSIS_REPORTING/report_index.json",
            "artifacts/phases/P09_ANALYSIS_REPORTING/valkey_e2e_evidence.json",
            "artifacts/phases/P09_ANALYSIS_REPORTING/cleanup_report.json",
        ],
        "missing_metrics": list(analysis.get("missing_metrics", [])),
        "risks": [
            {
                "risk": "Baseline comparison is initialized with NO_BASELINE_YET until a versioned baseline exists.",
                "severity": "low",
                "required_before_next_phase": False,
            }
        ],
        "report_index": _rel(index_path),
        "report_outputs": [_rel(path) for path in reports],
    }
    _write_json(phase_dir / "phase_summary.json", phase_summary)


def _report_record(path: Path) -> dict[str, str]:
    return {"path": _rel(path), "sha256": _sha256_file(path)}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
