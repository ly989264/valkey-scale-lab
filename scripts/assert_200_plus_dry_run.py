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
    parser.add_argument("--min-targets", required=True)
    args = parser.parse_args()
    targets = {int(value) for value in split_csv(args.min_targets)}
    base = phase_dir(args.phase)
    errors: list[str] = []
    target_doc = require_json(base / "dry_run_targets.json", errors, "dry-run targets")
    proof = require_json(base / "no_runtime_created_proof.json", errors, "no-runtime proof")
    try:
        rows = load_jsonl(base / "dry_run_results.jsonl")
    except Exception as exc:
        rows = []
        errors.append(f"dry_run_results.jsonl: {exc}")
    if target_doc:
        observed = set(int(value) for value in target_doc.get("targets", []) if int(value) > 200)
        missing = sorted(targets - observed)
        if missing:
            errors.append(f"missing dry-run targets above 200: {missing}")
    if proof:
        if proof.get("runtime_resources_created") not in {False, 0}:
            errors.append("no_runtime_created_proof must show zero runtime resources created")
        if proof.get("status") != "PASS":
            errors.append("no_runtime_created_proof status must be PASS")
    for row in rows:
        if row.get("execution_mode") != "dry_run":
            errors.append(f"{row.get('target_nodes')}: execution_mode must be dry_run")
        if int(row.get("target_nodes", 0)) <= 200:
            errors.append(f"{row.get('target_nodes')}: target must be above 200")
    if errors:
        return print_errors(errors)
    print(f"PASS 200-plus dry-run phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

