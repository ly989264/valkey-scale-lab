#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from valkey_scale_lab.report.messages import (  # noqa: E402
    DEFAULT_LANGUAGE,
    LANGUAGES,
    messages,
)

EXTERNAL_RE = re.compile(r"https?://(?!www\.w3\.org/2000/svg)|//(?!www\.w3\.org/2000/svg)|cdn\.|unpkg\.com|jsdelivr|googleapis|cloudflare", re.IGNORECASE)

#: The sections a report must carry, named by catalog key rather than by their
#: text. The list used to be a second copy of the renderer's own headings, which
#: is a second thing that can disagree with the first - and it disagreed the
#: moment the report gained a second language.
#:
#: What this trades, stated rather than glossed: a checker that reads the same
#: catalog the renderer reads cannot catch a heading being **renamed** in the
#: catalog, because both sides move together. It still catches the failure this
#: check exists for - a section that stops being rendered at all, whatever the
#: catalog says - and it now catches that in every language rather than one.
REQUIRED_SECTION_KEYS = [
    "sec.overview",
    "sec.run_metadata",
    "sec.setup_waterfall",
    "sec.stage_durations",
    "sec.slow_nodes",
    "sec.slow_commands",
    "sec.management_matrix",
    "sec.topology_diff",
    "sec.fault_timeline",
    "sec.failover_distribution",
    "sec.workload",
    "sec.resource_trends",
    "sec.resource_nodes",
    "sec.missing_metrics",
    "sec.conclusions",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert the offline visual report contract.")
    parser.add_argument("--reports-dir", required=True)
    parser.add_argument("--report-index")
    parser.add_argument(
        "--lang",
        choices=list(LANGUAGES),
        default=DEFAULT_LANGUAGE,
        help="Which language's report this directory holds. Sections and title are checked in it.",
    )
    args = parser.parse_args()
    msg = messages(args.lang)
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
        if "LLM" in text and msg["doc.eyebrow_no_llm"] not in text and msg["doc.standfirst"] not in text:
            errors.append(f"{label} mentions LLM without explicit offline/no-LLM policy")
    for key in REQUIRED_SECTION_KEYS:
        if msg[key] not in markdown:
            errors.append(f"report.md missing required {args.lang} section: {msg[key]}")
    if msg["doc.title"] not in html:
        errors.append(f"index.html missing the {args.lang} report title")
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
    print(f"PASS: offline report contract satisfied for {reports_dir} ({args.lang})")
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
