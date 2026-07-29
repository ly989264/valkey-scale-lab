#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

EXTERNAL_RE = re.compile(r"https?://(?!www\.w3\.org/2000/svg)|//(?!www\.w3\.org/2000/svg)|cdn\.|unpkg\.com|jsdelivr|googleapis|cloudflare", re.IGNORECASE)
REQUIRED_MD_SECTIONS = [
    "总览页",
    "运行元数据",
    "集群拉起瀑布图",
    "阶段耗时排序",
    "慢节点 TopN",
    "慢命令 TopN",
    "管理操作矩阵",
    "管理 topology diff 摘要",
    "故障 Timeline",
    "Failover 延迟分布",
    "Workload 基准压测",
    "资源观测趋势",
    "资源异常节点 TopN",
    "缺失指标",
    "结论摘要",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert the Chinese offline visual report contract.")
    parser.add_argument("--reports-dir", required=True)
    parser.add_argument("--report-index")
    args = parser.parse_args()
    reports_dir = Path(args.reports_dir)
    report_index = Path(args.report_index) if args.report_index else reports_dir / "report_index.json"
    errors: list[str] = []
    required = [
        reports_dir / "index.html",
        reports_dir / "report.md",
        report_index,
        reports_dir / "exports",
        reports_dir / "assets",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"required report output missing: {path}")
    if errors:
        return _fail(errors)
    index = _load_json(report_index, errors)
    markdown = (reports_dir / "report.md").read_text(encoding="utf-8", errors="replace")
    html = (reports_dir / "index.html").read_text(encoding="utf-8", errors="replace")
    for label, text in [("report.md", markdown), ("index.html", html)]:
        if EXTERNAL_RE.search(text):
            errors.append(f"{label} contains an external URL/CDN dependency")
        if "LLM" in text and "不调用 LLM" not in text:
            errors.append(f"{label} mentions LLM without explicit offline/no-LLM policy")
    for section in REQUIRED_MD_SECTIONS:
        if section not in markdown:
            errors.append(f"report.md missing required Chinese section: {section}")
    if "中文自动化可视化分析报告" not in html:
        errors.append("index.html missing Chinese report title")
    exports = sorted((reports_dir / "exports").glob("*.csv"))
    assets = sorted((reports_dir / "assets").glob("*.svg"))
    if not exports:
        errors.append("exports/*.csv is empty")
    if not assets:
        errors.append("assets/*.svg is empty")
    for path in exports + assets:
        if path.stat().st_size <= 0:
            errors.append(f"generated report file is empty: {path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        if EXTERNAL_RE.search(text):
            errors.append(f"{path.name} contains an external URL/CDN dependency")
    if index:
        policy = index.get("offline_policy", {})
        if policy.get("artifact_only") is not True or policy.get("llm_used") is not False:
            errors.append("report_index offline_policy must assert artifact_only=true and llm_used=false")
        if policy.get("external_urls_allowed") is not False or policy.get("cdn_allowed") is not False:
            errors.append("report_index offline_policy must reject external URLs and CDNs")
        if not isinstance(index.get("exports"), list) or len(index.get("exports", [])) != len(exports):
            errors.append("report_index exports list must match generated CSV exports")
        if not isinstance(index.get("assets"), list) or len(index.get("assets", [])) != len(assets):
            errors.append("report_index assets list must match generated SVG assets")
        if (index.get("conclusion_summary", {}) or {}).get("source") != "artifact_derived":
            errors.append("report_index conclusion_summary must be artifact_derived")
        _assert_refs_exist(index.get("exports", []), errors, "export")
        _assert_refs_exist(index.get("assets", []), errors, "asset")
    if errors:
        return _fail(errors)
    print(f"PASS: Chinese offline report contract satisfied for {reports_dir}")
    return 0


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"could not read report index {path}: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def _assert_refs_exist(items: Any, errors: list[str], label: str) -> None:
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            errors.append(f"{label} ref must be object with path")
            continue
        path = Path(item["path"])
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists() or path.stat().st_size <= 0:
            errors.append(f"{label} ref missing or empty: {item['path']}")


def _fail(errors: list[str]) -> int:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
