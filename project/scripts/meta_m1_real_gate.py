#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from meta_m1_evidence_gate import DEFAULT_EVIDENCE_ROOT, evaluate, source_tree_digest
from valkey_scale_lab.meta_loop.digests import tree_digest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run and independently admit an exact-scale Milestone 1 gate")
    parser.add_argument("--scale", required=True, type=int, choices=(50, 200))
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    return parser


def main() -> int:
    args = _parser().parse_args()
    evidence_dir = (args.evidence_root / f"scale-{args.scale}").resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    protected_root = PROJECT_ROOT.parent / "loop_evidence" / "artifacts"
    protected_before = tree_digest(protected_root)
    command = [
        sys.executable,
        "-m",
        "valkey_scale_lab.cli",
        "milestone1",
        "real-gate",
        "--scale",
        str(args.scale),
        "--evidence-dir",
        str(evidence_dir),
    ]
    env = dict(os.environ)
    env["VSLAB_META_M1_CONTROLLER_OWNED"] = "1"
    product_digest = source_tree_digest()
    env["VSLAB_META_M1_PRODUCT_DIGEST"] = product_digest
    env["VSLAB_META_M1_SOURCE_DIGEST"] = product_digest  # Compatibility until the product gate adopts admission v2.
    process = subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False)
    protected_after = tree_digest(protected_root)
    if protected_after != protected_before:
        print("product real gate modified historical loop_evidence/artifacts; admission is forbidden", file=sys.stderr)
        return 1
    if process.returncode != 0:
        print(f"product real gate failed with exit code {process.returncode}", file=sys.stderr)
        return process.returncode
    errors = evaluate(args.scale, args.evidence_root)
    if errors:
        print("exact-scale evidence admission failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"PASS exact real Milestone 1 gate at {args.scale} nodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
