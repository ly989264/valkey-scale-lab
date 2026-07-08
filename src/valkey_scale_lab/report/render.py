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
    report_run_id = str(analysis.get("run_id") or RUN_ID)
    report_created_at = str(analysis.get("created_at") or CREATED_AT)

    generated = [
        _write_metrics_csv(report_dir / "metrics.csv", metrics),
        _write_missing_csv(report_dir / "missing_metrics.csv", missing),
        _write_baseline_csv(report_dir / "baseline_comparison.csv", analysis.get("baseline_comparison", {})),
        _write_setup_phase_csv(report_dir / "setup_phase_durations.csv", analysis.get("setup_aggregates", {})),
        _write_setup_nodes_csv(report_dir / "setup_slowest_nodes.csv", analysis.get("setup_aggregates", {})),
        _write_command_rows_csv(report_dir / "command_slowest.csv", analysis.get("command_audit", {}).get("slowest_commands_topN", [])),
        _write_command_rows_csv(report_dir / "command_failures.csv", analysis.get("command_audit", {}).get("failed_commands", [])),
        _write_command_rows_csv(report_dir / "command_retries.csv", analysis.get("command_audit", {}).get("retry_commands", [])),
        _write_chart(report_dir / "metric_chart.svg", metrics),
        _write_setup_waterfall_svg(report_dir / "setup_waterfall.svg", analysis.get("setup_aggregates", {})),
        _write_command_latency_svg(report_dir / "command_latency.svg", analysis.get("command_audit", {})),
        _write_markdown(report_dir / "report.md", analysis),
        _write_html(report_dir / "index.html", analysis),
    ]

    index_path = Path(index_out)
    index = {
        "schema_version": "v1",
        "artifact_type": "report_index",
        "phase_id": PHASE_ID,
        "run_id": report_run_id,
        "created_at": report_created_at,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "analysis_path": _rel(analysis_file),
        "run_manifest_ref": analysis.get("run_manifest_ref")
        or {
            "status": "MISSING",
            "reason": "analysis_summary.json did not include run_manifest_ref.",
            "impact": "Report cannot link back to run manifest.",
        },
        "run_metadata_ref": analysis.get("run_metadata_ref")
        or {
            "status": "MISSING",
            "reason": "analysis_summary.json did not include run_metadata_ref.",
            "impact": "Report cannot link back to run metadata.",
        },
        "reports": [_report_record(path) for path in generated],
        "setup_report_inputs": {
            "setup_telemetry": analysis.get("setup_telemetry", {"status": "SKIPPED_WITH_REASON", "reason": "analysis did not include setup telemetry"}),
            "csv": "setup_phase_durations.csv",
            "svg": "setup_waterfall.svg",
        },
        "command_audit_report_inputs": {
            "command_log": analysis.get("command_audit", {}).get("command_log_ref", {"status": "SKIPPED_WITH_REASON", "reason": "analysis did not include command audit"}),
            "command_audit_summary": analysis.get("command_audit", {}).get("summary_artifact", {"status": "SKIPPED_WITH_REASON", "reason": "analysis did not include command_audit_summary.json"}),
            "csv": ["command_slowest.csv", "command_failures.csv", "command_retries.csv"],
            "svg": "command_latency.svg",
        },
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


def _write_setup_phase_csv(path: Path, setup: dict[str, Any]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "value_ms", "status", "reason"])
        writer.writeheader()
        for item in setup.get("phase_duration_ranking", []):
            writer.writerow({"metric": item.get("metric", "MISSING"), "value_ms": item.get("value_ms", ""), "status": "PASS", "reason": ""})
        if not setup.get("phase_duration_ranking"):
            writer.writerow({"metric": "setup_telemetry", "value_ms": "", "status": setup.get("status", "SKIPPED_WITH_REASON"), "reason": setup.get("reason", "")})
    return path


def _write_setup_nodes_csv(path: Path, setup: dict[str, Any]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["logical_id", "nodehost_id", "node_ready_ms", "node_role", "node_cluster_state", "node_cluster_known_nodes"])
        writer.writeheader()
        for item in setup.get("slowest_nodes_topN", []):
            if not isinstance(item, dict) or item.get("status") == "SKIPPED_WITH_REASON":
                continue
            writer.writerow(
                {
                    "logical_id": item.get("logical_id", "MISSING"),
                    "nodehost_id": item.get("nodehost_id", "MISSING"),
                    "node_ready_ms": item.get("node_ready_ms", ""),
                    "node_role": item.get("node_role", "MISSING"),
                    "node_cluster_state": item.get("node_cluster_state", "MISSING"),
                    "node_cluster_known_nodes": item.get("node_cluster_known_nodes", "MISSING"),
                }
            )
    return path


def _write_command_rows_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["command_id", "operation_id", "step_id", "command_kind", "duration_ms", "status", "exit_code", "retry_index", "error_type"])
        writer.writeheader()
        for item in rows:
            writer.writerow(
                {
                    "command_id": item.get("command_id", "MISSING"),
                    "operation_id": item.get("operation_id", "MISSING"),
                    "step_id": item.get("step_id", "MISSING"),
                    "command_kind": item.get("command_kind", "MISSING"),
                    "duration_ms": item.get("duration_ms", ""),
                    "status": item.get("status", "MISSING"),
                    "exit_code": item.get("exit_code", ""),
                    "retry_index": item.get("retry_index", 0),
                    "error_type": item.get("error_type", ""),
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


def _write_setup_waterfall_svg(path: Path, setup: dict[str, Any]) -> Path:
    rows = [item for item in setup.get("phase_duration_ranking", []) if isinstance(item.get("value_ms"), (int, float))]
    max_value = max([float(item["value_ms"]) for item in rows] + [1.0])
    y = 42
    parts: list[str] = []
    for item in rows[:17]:
        name = html.escape(str(item.get("metric", "MISSING")))
        value = float(item["value_ms"])
        width = int(380 * (value / max_value))
        parts.append(f'<text x="12" y="{y + 14}" font-size="12">{name}</text>')
        parts.append(f'<rect x="210" y="{y}" width="{max(width, 2)}" height="18" fill="#326c7a"/>')
        parts.append(f'<text x="{220 + max(width, 2)}" y="{y + 14}" font-size="12">{value:.3f} ms</text>')
        y += 32
    if not rows:
        parts.append('<text x="12" y="56" font-size="13">setup_telemetry.json 未提供可绘制的数值阶段耗时。</text>')
    height = max(y + 20, 100)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="720" height="{height}" viewBox="0 0 720 {height}">\n'
        '<rect width="100%" height="100%" fill="#ffffff"/>\n'
        '<text x="12" y="24" font-size="16" font-weight="700">集群拉起瀑布图</text>\n'
        + "\n".join(parts)
        + "\n</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")
    return path


def _write_command_latency_svg(path: Path, audit: dict[str, Any]) -> Path:
    rows = [item for item in audit.get("slowest_commands_topN", []) if isinstance(item.get("duration_ms"), (int, float))]
    max_value = max([float(item["duration_ms"]) for item in rows] + [1.0])
    y = 42
    parts: list[str] = []
    for item in rows[:10]:
        name = html.escape(f"{item.get('command_kind', 'MISSING')} {item.get('command_id', 'MISSING')}")
        value = float(item["duration_ms"])
        width = int(380 * (value / max_value))
        color = "#7c4d1d" if item.get("status") != "PASS" else "#475f9b"
        parts.append(f'<text x="12" y="{y + 14}" font-size="12">{name}</text>')
        parts.append(f'<rect x="230" y="{y}" width="{max(width, 2)}" height="18" fill="{color}"/>')
        parts.append(f'<text x="{240 + max(width, 2)}" y="{y + 14}" font-size="12">{value:.3f} ms</text>')
        y += 32
    if not rows:
        parts.append('<text x="12" y="56" font-size="13">command_log.jsonl 未提供可绘制的命令耗时。</text>')
    height = max(y + 20, 100)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="760" height="{height}" viewBox="0 0 760 {height}">\n'
        '<rect width="100%" height="100%" fill="#ffffff"/>\n'
        '<text x="12" y="24" font-size="16" font-weight="700">命令耗时分布</text>\n'
        + "\n".join(parts)
        + "\n</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")
    return path


def _write_markdown(path: Path, analysis: dict[str, Any]) -> Path:
    metadata = analysis.get("run_metadata", {})
    setup = analysis.get("setup_aggregates", {})
    command_audit = analysis.get("command_audit", {})
    lines = [
        "# P09 Analysis Report",
        "",
        f"Status: {analysis.get('status', 'MISSING')}",
        f"Source phase: {analysis.get('source', {}).get('phase_id', 'MISSING')}",
        "",
        "## 运行元数据",
        "",
        f"- run_id: {_metadata_value(metadata, 'run_id')}",
        f"- created_at: {_metadata_value(metadata, 'created_at')}",
        f"- git_sha: {_metadata_value(metadata, 'git_sha')}",
        f"- valkey_version: {_metadata_value(metadata, 'valkey_version')}",
        f"- artifact_root: {_metadata_value(metadata, 'artifact_root')}",
        "",
        "## 分析发现",
        "",
    ]
    for finding in analysis.get("findings", []):
        lines.append(f"- {finding.get('name', 'finding')}: {finding.get('status', 'MISSING')}")
    lines.extend(["", "## 集群拉起瀑布图", ""])
    if setup.get("phase_duration_ranking"):
        lines.append("![集群拉起瀑布图](setup_waterfall.svg)")
    else:
        lines.append(f"- {setup.get('status', 'SKIPPED_WITH_REASON')}: {setup.get('reason', '未提供 setup telemetry')}")
    lines.extend(["", "## 阶段耗时排序", ""])
    for item in setup.get("phase_duration_ranking", [])[:10]:
        lines.append(f"- {item.get('metric', 'MISSING')}: {item.get('value_ms', 'MISSING')} ms")
    if not setup.get("phase_duration_ranking"):
        lines.append("- SKIPPED_WITH_REASON: 无可排序的阶段耗时")
    lines.extend(["", "## 慢节点 TopN", ""])
    slow_nodes = setup.get("slowest_nodes_topN", [])
    if slow_nodes:
        for item in slow_nodes[:10]:
            if isinstance(item, dict) and item.get("status") == "SKIPPED_WITH_REASON":
                lines.append(f"- SKIPPED_WITH_REASON: {item.get('reason', '')}")
            elif isinstance(item, dict):
                lines.append(f"- {item.get('logical_id', 'MISSING')}: {item.get('node_ready_ms', 'MISSING')} ms, role={item.get('node_role', 'MISSING')}")
    else:
        lines.append("- SKIPPED_WITH_REASON: 无慢节点样本")
    lines.extend(["", "## 慢命令 TopN", ""])
    if command_audit.get("slowest_commands_topN"):
        lines.append("![命令耗时分布](command_latency.svg)")
        for item in command_audit.get("slowest_commands_topN", [])[:10]:
            lines.append(f"- {item.get('command_id', 'MISSING')} {item.get('command_kind', 'MISSING')}: {item.get('duration_ms', 'MISSING')} ms status={item.get('status', 'MISSING')}")
    else:
        lines.append(f"- {command_audit.get('status', 'SKIPPED_WITH_REASON')}: {command_audit.get('reason', '无 command log 样本')}")
    lines.extend(["", "## 失败命令", ""])
    failures = command_audit.get("failed_commands", [])
    if failures:
        for item in failures[:10]:
            lines.append(f"- {item.get('command_id', 'MISSING')} {item.get('command_kind', 'MISSING')}: {item.get('error_type', '')}")
    else:
        lines.append("- none")
    lines.extend(["", "## 重试命令", ""])
    retries = command_audit.get("retry_commands", [])
    if retries:
        for item in retries[:10]:
            lines.append(f"- {item.get('command_id', 'MISSING')} {item.get('command_kind', 'MISSING')}: retry_index={item.get('retry_index', 0)} status={item.get('status', 'MISSING')}")
    else:
        lines.append("- none")
    lines.extend(["", "## 命令审计覆盖", ""])
    lines.append(f"- total_commands: {command_audit.get('total_commands', 0)}")
    for kind, count in sorted(command_audit.get("by_command_kind", {}).items()):
        lines.append(f"- {kind}: {count}")
    lines.extend(["", "## 缺失指标", ""])
    missing = analysis.get("missing_metrics", [])
    if missing:
        for item in missing:
            lines.append(f"- {item.get('metric', 'MISSING')}: {item.get('status', 'MISSING')} - {item.get('reason', '')}")
    else:
        lines.append("- none")
    lines.extend(["", "## 生成表格", "", "- metrics.csv", "- missing_metrics.csv", "- baseline_comparison.csv", "- setup_phase_durations.csv", "- setup_slowest_nodes.csv", "- command_slowest.csv", "- command_failures.csv", "- command_retries.csv", "- metric_chart.svg", "- setup_waterfall.svg", "- command_latency.svg"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_html(path: Path, analysis: dict[str, Any]) -> Path:
    metadata = analysis.get("run_metadata", {})
    setup = analysis.get("setup_aggregates", {})
    command_audit = analysis.get("command_audit", {})
    metadata_rows = "\n".join(
        "<tr><td>{}</td><td><code>{}</code></td></tr>".format(
            html.escape(key),
            html.escape(_metadata_value(metadata, key)),
        )
        for key in ["run_id", "created_at", "git_sha", "valkey_version", "artifact_root"]
    )
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
    setup_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td></tr>".format(html.escape(str(item.get("metric", "MISSING"))), html.escape(str(item.get("value_ms", "MISSING"))))
        for item in setup.get("phase_duration_ranking", [])[:12]
    ) or '<tr><td colspan="2">SKIPPED_WITH_REASON: 无可排序的阶段耗时</td></tr>'
    slow_node_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(item.get("logical_id", item.get("status", "MISSING")))),
            html.escape(str(item.get("node_ready_ms", ""))),
            html.escape(str(item.get("node_role", ""))),
            html.escape(str(item.get("node_cluster_state", item.get("reason", "")))),
        )
        for item in setup.get("slowest_nodes_topN", [])[:10]
        if isinstance(item, dict)
    ) or '<tr><td colspan="4">SKIPPED_WITH_REASON: 无慢节点样本</td></tr>'
    slow_command_rows = _command_html_rows(command_audit.get("slowest_commands_topN", [])) or '<tr><td colspan="5">SKIPPED_WITH_REASON: 无慢命令样本</td></tr>'
    failed_command_rows = _command_html_rows(command_audit.get("failed_commands", [])) or '<tr><td colspan="5">none</td></tr>'
    retry_command_rows = _command_html_rows(command_audit.get("retry_commands", [])) or '<tr><td colspan="5">none</td></tr>'
    command_coverage_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td></tr>".format(html.escape(str(kind)), html.escape(str(count)))
        for kind, count in sorted(command_audit.get("by_command_kind", {}).items())
    ) or '<tr><td colspan="2">SKIPPED_WITH_REASON: 无 command log 样本</td></tr>'
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
  <h2>运行元数据</h2>
  <table><thead><tr><th>字段</th><th>值</th></tr></thead><tbody>{metadata_rows}</tbody></table>
  <h2>分析发现</h2>
  <table><thead><tr><th>Name</th><th>Status</th></tr></thead><tbody>{finding_rows}</tbody></table>
  <h2>缺失指标</h2>
  <table><thead><tr><th>指标</th><th>状态</th><th>原因</th></tr></thead><tbody>{missing_rows}</tbody></table>
  <h2>集群拉起瀑布图</h2>
  <img src="setup_waterfall.svg" alt="集群拉起瀑布图">
  <h2>阶段耗时排序</h2>
  <table><thead><tr><th>阶段指标</th><th>耗时 ms</th></tr></thead><tbody>{setup_rows}</tbody></table>
  <h2>慢节点 TopN</h2>
  <table><thead><tr><th>节点</th><th>ready ms</th><th>角色</th><th>状态</th></tr></thead><tbody>{slow_node_rows}</tbody></table>
  <h2>慢命令 TopN</h2>
  <img src="command_latency.svg" alt="命令耗时分布">
  <table><thead><tr><th>命令</th><th>操作</th><th>类型</th><th>耗时 ms</th><th>状态</th></tr></thead><tbody>{slow_command_rows}</tbody></table>
  <h2>失败命令</h2>
  <table><thead><tr><th>命令</th><th>操作</th><th>类型</th><th>耗时 ms</th><th>状态</th></tr></thead><tbody>{failed_command_rows}</tbody></table>
  <h2>重试命令</h2>
  <table><thead><tr><th>命令</th><th>操作</th><th>类型</th><th>耗时 ms</th><th>状态</th></tr></thead><tbody>{retry_command_rows}</tbody></table>
  <h2>命令审计覆盖</h2>
  <table><thead><tr><th>命令类型</th><th>数量</th></tr></thead><tbody>{command_coverage_rows}</tbody></table>
  <h2>图表</h2>
  <img src="metric_chart.svg" alt="P09 artifact metrics chart">
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")
    return path


def _command_html_rows(rows: list[dict[str, Any]]) -> str:
    return "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(item.get("command_id", "MISSING"))),
            html.escape(str(item.get("operation_id", "MISSING"))),
            html.escape(str(item.get("command_kind", "MISSING"))),
            html.escape(str(item.get("duration_ms", "MISSING"))),
            html.escape(str(item.get("status", "MISSING"))),
        )
        for item in rows
        if isinstance(item, dict)
    )


def _write_phase_summary(phase_dir: Path, analysis: dict[str, Any], index_path: Path, reports: list[Path]) -> None:
    phase_summary = {
        "schema_version": "v1",
        "artifact_type": "phase_summary",
        "phase_id": PHASE_ID,
        "run_id": str(analysis.get("run_id") or RUN_ID),
        "created_at": str(analysis.get("created_at") or CREATED_AT),
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
        "run_manifest_ref": analysis.get("run_manifest_ref"),
        "run_metadata_ref": analysis.get("run_metadata_ref"),
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


def _metadata_value(metadata: Any, key: str) -> str:
    if not isinstance(metadata, dict):
        return "SKIPPED_WITH_REASON: no run metadata attached"
    value = metadata.get(key, {"status": "MISSING", "reason": f"{key} absent from run metadata"})
    if isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON"}:
        return f"{value.get('status')}: {value.get('reason', '')}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


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
