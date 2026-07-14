#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from meta_m1_evidence_gate import evaluate
from valkey_scale_lab.meta_loop_v6.digests import product_tree_digest, tree_digest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DEFAULT_EVIDENCE_ROOT = WORKSPACE_ROOT / "loop_evidence" / "meta_runs" / "milestone1-v6" / "evidence"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture or admit exact-scale Milestone 1 v6 evidence")
    parser.add_argument("--mode", required=True, choices=("capture", "admit"))
    parser.add_argument("--scale", required=True, type=int, choices=(50, 200))
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    return parser


def capture(scale: int, evidence_root: Path) -> int:
    evidence_dir = (evidence_root / f"scale-{scale}").resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    protected_root = WORKSPACE_ROOT / "loop_evidence" / "artifacts"
    protected_before = tree_digest(protected_root)
    command = [
        sys.executable,
        "-m",
        "valkey_scale_lab.cli",
        "milestone1",
        "real-gate",
        "--scale",
        str(scale),
        "--evidence-dir",
        str(evidence_dir),
    ]
    env = dict(os.environ)
    env["VSLAB_META_M1_CONTROLLER_OWNED"] = "1"
    digest = product_tree_digest(PROJECT_ROOT)
    env["VSLAB_META_M1_PRODUCT_DIGEST"] = digest
    env["VSLAB_META_M1_SOURCE_DIGEST"] = digest
    process = subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False)
    if tree_digest(protected_root) != protected_before:
        print("product real gate modified historical loop_evidence/artifacts", file=sys.stderr)
        return 1
    if process.returncode != 0:
        print(f"product real gate failed with exit code {process.returncode}", file=sys.stderr)
        return process.returncode
    print(f"PASS captured exact real Milestone 1 evidence at {scale} nodes")
    return 0


def admit(scale: int, evidence_root: Path) -> int:
    errors = evaluate(scale, evidence_root)
    if errors:
        print("exact-scale evidence admission failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"PASS admitted exact real Milestone 1 evidence at {scale} nodes")
    return 0


def main() -> int:
    args = _parser().parse_args()
    if args.mode == "capture":
        return capture(args.scale, args.evidence_root)
    return admit(args.scale, args.evidence_root)


if __name__ == "__main__":
    raise SystemExit(main())
