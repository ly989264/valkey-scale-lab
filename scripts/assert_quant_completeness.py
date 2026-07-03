#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import phase_dir, print_errors, rel, require_file, require_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--category")
    parser.add_argument("--scale")
    args = parser.parse_args()
    base = phase_dir(args.phase)
    errors: list[str] = []
    summary = require_json(base / "quant_summary.json", errors, "quant summary")
    require_file(base / "events.jsonl", errors, "events")
    require_file(base / "metrics_timeseries.jsonl", errors, "metrics timeseries")
    require_json(base / "workload_windows.json", errors, "workload windows")
    if summary:
        claims = summary.get("runtime_claims", {})
        if args.category in {"management", "fault", "full_flow"} and claims.get("real_valkey_claimed") is not True:
            errors.append(f"{rel(base / 'quant_summary.json')}: real_valkey_claimed must be true for {args.category}")
        if args.category == "management" and claims.get("management_runtime_claimed") is not True:
            errors.append("management_runtime_claimed must be true")
        if args.category == "fault" and claims.get("fault_runtime_claimed") is not True:
            errors.append("fault_runtime_claimed must be true")
    if errors:
        return print_errors(errors)
    print(f"PASS quant completeness phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

