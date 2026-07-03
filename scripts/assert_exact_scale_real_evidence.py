#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import phase_dir, print_errors, rel, require_json  # noqa: E402


def evidence_path(phase: str, artifact_scope: str | None) -> Path:
    base = phase_dir(phase)
    if artifact_scope:
        return base / artifact_scope / "valkey_e2e_evidence.json"
    return base / "valkey_e2e_evidence.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--nodes", type=int)
    group.add_argument("--min-nodes", type=int)
    parser.add_argument("--artifact-scope")
    args = parser.parse_args()

    errors: list[str] = []
    path = evidence_path(args.phase, args.artifact_scope)
    evidence = require_json(path, errors, "real Valkey evidence")
    cleanup = require_json(phase_dir(args.phase) / "cleanup_report.json", errors, "cleanup report")
    if evidence:
        if evidence.get("real_valkey") is not True:
            errors.append(f"{rel(path)}: real_valkey must be true")
        if evidence.get("probe_result") != "PASS":
            errors.append(f"{rel(path)}: probe_result must be PASS")
        if evidence.get("valkey_version_prefix_required") != "9.1.":
            errors.append(f"{rel(path)}: version prefix requirement must be 9.1.")
        observed = int(evidence.get("nodes_observed", 0))
        requested = int(evidence.get("nodes_requested", evidence.get("min_nodes_requested", 0)) or 0)
        if args.nodes is not None:
            if requested != args.nodes:
                errors.append(f"{rel(path)}: nodes_requested must be exactly {args.nodes}, got {requested}")
            if observed != args.nodes:
                errors.append(f"{rel(path)}: nodes_observed must be exactly {args.nodes}, got {observed}")
        if args.min_nodes is not None:
            if observed < args.min_nodes:
                errors.append(f"{rel(path)}: nodes_observed must be at least {args.min_nodes}, got {observed}")
        versions = evidence.get("valkey_versions") or []
        if not versions:
            errors.append(f"{rel(path)}: valkey_versions must not be empty")
        elif not all(str(version).startswith("9.1.") for version in versions if version):
            errors.append(f"{rel(path)}: all observed Valkey versions must start with 9.1.")
    if cleanup and cleanup.get("status") != "PASS":
        errors.append(f"{rel(phase_dir(args.phase) / 'cleanup_report.json')}: cleanup status must be PASS")
    if errors:
        return print_errors(errors)
    print(f"PASS exact-scale real evidence phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

