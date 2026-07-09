#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from capability_gate import evaluate_capability
from common import exit_code, print_gate_summary, write_gate_result


def run(gate_name: str, capability: str, scales: set[int]) -> int:
    parser = argparse.ArgumentParser(description=f"Run {gate_name}.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="H00_BOOTSTRAP_HARD_GATES")
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    parser.add_argument("--allow-blocked", action="store_true")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    status, violations, blocked, extra = evaluate_capability(root, manifest_path, capability, scales)
    result = write_gate_result(
        root=root,
        stage_id=args.stage,
        gate_name=gate_name,
        status=status,
        inputs=[str(manifest_path)],
        violations=violations,
        blocked_reasons=blocked,
        extra=extra,
    )
    print_gate_summary(result)
    return exit_code(status, allow_blocked=args.allow_blocked)
