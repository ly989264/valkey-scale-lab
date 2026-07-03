#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import phase_dir, print_errors, require_json  # noqa: E402

BAD_TEXT = ["NaN", "undefined", "Traceback", "TODO_PLACEHOLDER", "BROKEN_CHART"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase")
    parser.add_argument("--report-index", required=True)
    args = parser.parse_args()
    errors: list[str] = []
    index = require_json(ROOT / args.report_index, errors, "report index")
    if index:
        assets = index.get("assets", [])
        reports = index.get("reports", [])
        for ref in list(assets) + list(reports):
            if not isinstance(ref, str):
                errors.append("report index assets/reports must contain string paths")
                continue
            path = ROOT / ref
            if not path.exists():
                errors.append(f"report asset missing: {ref}")
                continue
            if path.suffix.lower() in {".html", ".md", ".json", ".js"}:
                text = path.read_text(encoding="utf-8", errors="replace")
                for bad in BAD_TEXT:
                    if bad in text:
                        errors.append(f"{ref}: report contains forbidden marker {bad}")
        quality_path = phase_dir(args.phase) / "report_quality_report.json" if args.phase else None
        if quality_path:
            quality = require_json(quality_path, errors, "report quality")
            if quality and quality.get("status") != "PASS":
                errors.append("report_quality_report status must be PASS")
    if errors:
        return print_errors(errors)
    print("PASS report quality")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

