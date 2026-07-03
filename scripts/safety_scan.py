#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW_MARKER = "SAFETY-SANDBOX-OK"

BANNED_PATTERNS = [
    (re.compile(r"\bsudo\b"), "sudo is forbidden as a default path"),
    (re.compile(r"\bpfctl\b"), "host PF mutation is forbidden"),
    (re.compile(r"\biptables\b"), "host iptables mutation is forbidden"),
    (re.compile(r"\bnft\b"), "host nftables mutation is forbidden"),
    (re.compile(r"\bip\s+route\b"), "host route mutation is forbidden"),
    (re.compile(r"\broute\s+(add|delete|del)\b"), "host route mutation is forbidden"),
    (re.compile(r"\bifconfig\b"), "host interface mutation is forbidden"),
    (re.compile(r"\bnetworksetup\b"), "macOS global network mutation is forbidden"),
    (re.compile(r"\bkillall\b"), "broad process killing is forbidden"),
    (re.compile(r"\bpkill\s+-f\b"), "broad process killing is forbidden"),
]

SCAN_DIRS = ["src", "tests", "scripts", "docker", ".github"]
SCAN_FILES = ["Makefile", "pyproject.toml", "requirements.txt", "requirements-dev.txt"]
SKIP_FILES = {"scripts/safety_scan.py"}
EXTS = {".py", ".sh", ".bash", ".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ""}


def iter_files(include_docs: bool = False):
    dirs = list(SCAN_DIRS)
    if include_docs:
        dirs.extend(["docs", "templates"])
    for d in dirs:
        base = ROOT / d
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel in SKIP_FILES or "/__pycache__/" in rel:
                continue
            if path.suffix in EXTS or path.name in {"Dockerfile", "Makefile"}:
                yield path
    for f in SCAN_FILES:
        path = ROOT / f
        if path.exists():
            yield path


def scan_text(path: Path) -> list[str]:
    errors: list[str] = []
    rel = path.relative_to(ROOT).as_posix()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        return [f"{rel}: cannot read: {exc}"]
    for lineno, line in enumerate(lines, start=1):
        if ALLOW_MARKER in line:
            continue
        for pattern, reason in BANNED_PATTERNS:
            if pattern.search(line):
                errors.append(f"{rel}:{lineno}: {reason}: {line.strip()}")
    return errors


def scan_default_node_caps() -> list[str]:
    errors: list[str] = []
    for path in (ROOT / "templates" / "configs").glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        if "scale_1000" in path.name:
            if "allow_1000_nodes: true" not in text or "dry_run: true" not in text or "opt_in_1000: true" not in text:
                errors.append(f"{rel}: 1000 profile must be opt-in dry-run")
            continue
        if re.search(r"allow_1000_nodes:\s*true", text):
            errors.append(f"{rel}: non-1000 config may not enable 1000 nodes")
        m_shards = re.search(r"\n\s*shards:\s*(\d+)", text)
        m_rep = re.search(r"\n\s*replicas_per_shard:\s*(\d+)", text)
        if m_shards and m_rep:
            nodes = int(m_shards.group(1)) * (1 + int(m_rep.group(1)))
            if nodes > 100:
                p21_exception = (
                    path.name == "scale_200.yaml"
                    and nodes == 200
                    and "bounded_exception_phase: P21_FAILOVER_LATENCY_CURVE_200" in text
                    and "bounded_exception_nodes: 200" in text
                    and "allow_1000_nodes: false" in text
                    and "default_max_nodes: 100" in text
                )
                if p21_exception:
                    continue
                errors.append(f"{rel}: default config creates {nodes} nodes (>100)")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase")
    parser.add_argument("--include-docs", action="store_true")
    args = parser.parse_args()
    errors: list[str] = []
    for path in iter_files(include_docs=args.include_docs):
        errors.extend(scan_text(path))
    errors.extend(scan_default_node_caps())
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print("PASS safety_scan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
