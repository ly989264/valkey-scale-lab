#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import load_jsonl, phase_dir, print_errors, require_json, split_csv  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--scales", required=True)
    args = parser.parse_args()
    scales = [int(value) for value in split_csv(args.scales)]
    base = phase_dir(args.phase)
    errors: list[str] = []
    matrix = require_json(base / "full_flow_matrix.json", errors, "full-flow matrix")
    try:
        results = load_jsonl(base / "full_flow_results.jsonl")
    except Exception as exc:
        results = []
        errors.append(f"full_flow_results.jsonl: {exc}")
    if matrix:
        matrix_scales = {int(row.get("scale", 0)) for row in matrix.get("scales", []) if isinstance(row, dict)}
        missing = sorted(set(scales) - matrix_scales)
        if missing:
            errors.append(f"full_flow_matrix missing scales {missing}")
    result_scales = {int(row.get("scale", 0)) for row in results if isinstance(row, dict)}
    for scale in scales:
        if scale not in result_scales:
            errors.append(f"full_flow_results missing scale {scale}")
    for row in results:
        if row.get("status") != "PASS":
            errors.append(f"scale {row.get('scale')}: full-flow status must be PASS")
    if errors:
        return print_errors(errors)
    print(f"PASS full-flow e2e phase={args.phase} scales={args.scales}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

