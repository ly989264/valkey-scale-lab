#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from codex_gate import validate_artifact  # noqa: E402
from schema_validator import load_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    if args.phase != "P24_PARTITION_SPLIT_BRAIN_MATRIX":
        print(f"PASS split-brain report not required for phase={args.phase}")
        return 0

    path = ROOT / "artifacts" / "phases" / args.phase / "split_brain_report.json"
    errors = validate_artifact(path, ROOT / "schemas/artifact/split_brain_report.schema.json")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    report = load_json(path)
    detectors = report.get("detectors_run", [])
    window = report.get("split_brain_window_ms")
    if window == 0 and not detectors:
        errors.append("split_brain_window_ms=0 requires at least one detector to have run")
    if window == "MISSING" and not report.get("missing_detectors_with_reason"):
        errors.append("MISSING split_brain_window_ms requires missing_detectors_with_reason")
    for idx, missing in enumerate(report.get("missing_detectors_with_reason", [])):
        if not isinstance(missing, dict) or not missing.get("detector") or not missing.get("reason"):
            errors.append(f"missing_detectors_with_reason[{idx}] must include detector and reason")
    if report.get("indicator_observed") is True:
        if not (report.get("conflicting_slots") or report.get("conflicting_nodes") or report.get("conflicting_write_keys")):
            errors.append("observed split-brain indicator requires conflicting slots, nodes, or write keys")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS split-brain report phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
