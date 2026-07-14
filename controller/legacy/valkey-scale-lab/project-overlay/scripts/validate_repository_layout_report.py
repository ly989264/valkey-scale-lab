#!/usr/bin/env python3
"""Independent semantic validation for a repository layout report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from validate_repository_layout import validate_report_semantics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", required=True)
    args = parser.parse_args()
    try:
        report = json.loads(Path(args.instance).read_text(encoding="utf-8"))
        errors = validate_report_semantics(report)
    except Exception as exc:
        errors = [f"layout report unreadable: {exc}"]
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print(f"PASS repository layout semantics instance={args.instance}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
