#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import phase_dir, print_errors, require_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--report-index")
    args = parser.parse_args()
    base = phase_dir(args.phase)
    errors: list[str] = []
    provenance = require_json(base / "analysis_provenance.json", errors, "analysis provenance")
    if args.report_index:
        require_json(ROOT / args.report_index, errors, "report index")
    if provenance:
        refs = provenance.get("source_artifacts")
        if not isinstance(refs, list) or not refs:
            errors.append("analysis_provenance source_artifacts must be non-empty")
        for ref in refs or []:
            if isinstance(ref, str) and not (ROOT / ref).exists():
                errors.append(f"analysis source artifact missing: {ref}")
        if provenance.get("invented_values_present") not in {False, 0}:
            errors.append("analysis_provenance must assert invented_values_present=false")
    if errors:
        return print_errors(errors)
    print(f"PASS analysis provenance phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

