#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup-report", required=True)
    args = parser.parse_args()
    path = Path(args.cleanup_report)
    if not path.exists():
        print(f"cleanup report missing: {path}", file=sys.stderr)
        return 1
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"cleanup report invalid JSON: {exc}", file=sys.stderr)
        return 1
    errors: list[str] = []
    if report.get("status") != "PASS":
        errors.append(f"cleanup status must be PASS, got {report.get('status')!r}")
    remaining = report.get("resources_remaining", [])
    if remaining:
        errors.append(f"resources_remaining must be empty, got {remaining!r}")
    if not isinstance(report.get("cleanup_actions", []), list):
        errors.append("cleanup_actions must be a list")
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS cleanup {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
