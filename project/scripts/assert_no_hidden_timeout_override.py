#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ["src", "scripts", "templates", "config", "codex/phase_manifest.json"]
FORBIDDEN = [
    re.compile(r"cluster_node_timeout[\"']?\]\s*=\s*[\"']?(?:5000|60000|600000|15000)[\"']?"),
    re.compile(r"cluster_node_timeout[\"']?\s*:\s*[\"']?(?:5000|60000|600000|15000)[\"']?"),
    re.compile(r"cluster-node-timeout\s+\{?node\.get\([^)]*[\"'](?:5000|60000|600000|15000)[\"']"),
    re.compile(r"failover-node-timeout-ms\".*default=15000"),
]
ALLOWLIST = {
    "src/valkey_scale_lab/cluster_timeout.py",
    "config/valkey_scale_lab_global.yaml",
    "scripts/assert_no_hidden_timeout_override.py",
    "scripts/assert_timeout_matrix_artifacts.py",
    "scripts/failover_rto_timeout_matrix.py",
    "docs/codex/goal-loop/stages/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE.md",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    errors: list[str] = []
    for path in _files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for idx, line in enumerate(text.splitlines(), start=1):
            for pattern in FORBIDDEN:
                if pattern.search(line):
                    errors.append(f"{rel}:{idx}: hidden cluster-node-timeout override: {line.strip()}")
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS no hidden timeout override phase={args.phase}")
    return 0


def _files() -> list[Path]:
    files: list[Path] = []
    for entry in SCAN_DIRS:
        path = ROOT / entry
        if path.is_file():
            files.append(path)
            continue
        for candidate in path.rglob("*"):
            if candidate.is_file() and candidate.suffix in {".py", ".yaml", ".yml", ".json"}:
                files.append(candidate)
    return files


if __name__ == "__main__":
    raise SystemExit(main())
