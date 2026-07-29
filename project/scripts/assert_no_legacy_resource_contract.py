#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = {
    Path("docs/scalable_cluster_observability_design.md"),
    Path("scripts/assert_no_legacy_resource_contract.py"),
}
FORBIDDEN = (
    "m2_resource",
    "collect_m2_resource_window",
    "validate_and_aggregate_m2_resource_samples",
    "validate_equal_m2_resource_windows",
    "resource_window.json",
    "system_metrics_report",
    "system_metrics_timeseries",
    "directional_cluster_links",
    "cluster_link_errors",
    "buffer_overflows",
    "m2_resource_window",
    "CLUSTER LINKS",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=ROOT,
        help="Project root to scan; defaults to this repository's project/ directory.",
    )
    args = parser.parse_args(argv)
    failures = scan(args.project_root.resolve())
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print("legacy resource contract scan PASS")
    return 0


def scan(root: Path) -> list[str]:
    failures: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root)
        if rel in ALLOWLIST or _ignored_path(rel):
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in payload[:4096]:
            continue
        text = payload.decode("utf-8", errors="replace")
        for token in FORBIDDEN:
            if token in text:
                failures.append(f"{rel}: contains legacy token {token!r}")
    return failures


def _ignored_path(path: Path) -> bool:
    if any(part in {".pytest_cache", "__pycache__", ".DS_Store"} for part in path.parts):
        return True
    return bool(path.parts and path.parts[0] == "artifacts")


if __name__ == "__main__":
    raise SystemExit(main())
