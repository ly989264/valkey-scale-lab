#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import exit_code, print_gate_summary, write_gate_result, write_json
from manifest import build_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the M1 hardening evidence manifest.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="H00_BOOTSTRAP_HARD_GATES")
    parser.add_argument("--out", default="runs/m1-hardening/evidence_manifest.json")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest = build_manifest(root)
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    write_json(out, manifest)
    result = write_gate_result(
        root=root,
        stage_id=args.stage,
        gate_name="build_evidence_manifest",
        status="PASS",
        inputs=[str(out)],
        extra={"claim_count": len(manifest["claims"])},
    )
    print(f"PASS: evidence manifest written to {out}")
    print_gate_summary(result)
    return exit_code("PASS")


if __name__ == "__main__":
    raise SystemExit(main())
