#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import os
import subprocess
import sys
from pathlib import Path

from meta_m1_evidence_gate_v8 import evaluate
from valkey_scale_lab.goal.digests import tree_digest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DEFAULT_EVIDENCE_ROOT = WORKSPACE_ROOT / "loop_evidence/meta_runs/milestone1-v8/evidence"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture or admit fresh exact-scale Milestone 1 v8 evidence")
    parser.add_argument("--mode", required=True, choices=("capture", "admit"))
    parser.add_argument("--scale", required=True, type=int, choices=(50, 200))
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    return parser


def capture(scale: int, evidence_root: Path) -> int:
    if evidence_root.resolve() != DEFAULT_EVIDENCE_ROOT.resolve():
        print("v8 capture only accepts the canonical milestone1-v8 evidence root", file=sys.stderr)
        return 1
    if os.environ.get("VSLAB_META_M1_CONTROLLER_OWNED") != "1":
        print("v8 capture requires controller-supplied ownership context", file=sys.stderr)
        return 1
    supplied_digest = os.environ.get("VSLAB_META_M1_PRODUCT_DIGEST", "")
    if not re.fullmatch(r"[0-9a-f]{64}", supplied_digest):
        print("v8 capture requires a controller-supplied product digest", file=sys.stderr)
        return 1
    evidence_dir = (DEFAULT_EVIDENCE_ROOT / f"scale-{scale}").resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    protected_roots = _protected_roots()
    protected_before = {path: tree_digest(path) for path in protected_roots}
    env = dict(os.environ)
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "valkey_scale_lab.cli",
            "milestone1",
            "real-gate",
            "--scale",
            str(scale),
            "--evidence-dir",
            str(evidence_dir),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
    )
    changed = [str(path) for path, digest in protected_before.items() if tree_digest(path) != digest]
    if changed:
        print(f"product real gate modified protected historical evidence: {changed}", file=sys.stderr)
        return 1
    if process.returncode != 0:
        print(f"product real gate failed with exit code {process.returncode}", file=sys.stderr)
        return process.returncode
    print(f"PASS captured fresh exact real Milestone 1 evidence at {scale} nodes")
    return 0


def admit(scale: int, evidence_root: Path) -> int:
    if evidence_root.resolve() != DEFAULT_EVIDENCE_ROOT.resolve():
        print("v8 admission only accepts the canonical milestone1-v8 evidence root", file=sys.stderr)
        return 1
    errors = evaluate(scale, evidence_root)
    if errors:
        print("exact-scale evidence admission failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"PASS admitted fresh exact real Milestone 1 evidence at {scale} nodes")
    return 0


def _protected_roots() -> list[Path]:
    evidence = WORKSPACE_ROOT / "loop_evidence"
    roots = [evidence / "artifacts"]
    meta_runs = evidence / "meta_runs"
    if meta_runs.is_dir():
        roots.extend(path for path in meta_runs.iterdir() if path.is_dir() and path.name != "milestone1-v8")
    return roots


def main() -> int:
    args = _parser().parse_args()
    return capture(args.scale, args.evidence_root) if args.mode == "capture" else admit(args.scale, args.evidence_root)


if __name__ == "__main__":
    raise SystemExit(main())
