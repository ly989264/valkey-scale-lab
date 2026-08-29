#!/usr/bin/env python3
"""Assert `.agent-loop/backlog.yaml` still says what CLAUDE.md says.

The backlog is data derived from CLAUDE.md "Where the work stands" > "What is
still open": one item per bullet, `statement` being the bullet verbatim. CLAUDE.md
hard-wraps its bullets, so a bullet is read as every line from its `- ` to the
next bullet, group heading or blank line, joined with single spaces. That join
is the only normalisation; after it every `statement` must be byte-identical to
one bullet, every bullet must be claimed by exactly one item, and the section's
bullet count must equal both `source.item_count` and the number of items.

Exit 0 when they agree, 1 with one line per disagreement when they do not.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SECTION_HEADING = "### What is still open"


def read_open_bullets(claude_md: Path) -> list[str]:
    """The section's bullets, hard wraps joined by single spaces."""
    lines = claude_md.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index(SECTION_HEADING) + 1
    except ValueError as error:
        raise SystemExit(f"{claude_md}: no heading {SECTION_HEADING!r}") from error
    bullets: list[str] = []
    current: list[str] | None = None
    for line in lines[start:]:
        if line.startswith("## ") or line.startswith("### "):
            break
        if line.startswith("- "):
            if current:
                bullets.append(" ".join(current))
            current = [line[2:].strip()]
        elif line.startswith("  ") and current is not None:
            current.append(line.strip())
        else:
            if current:
                bullets.append(" ".join(current))
            current = None
    if current:
        bullets.append(" ".join(current))
    return bullets


def compare(claude_md: Path, backlog_path: Path) -> list[str]:
    bullets = read_open_bullets(claude_md)
    backlog = yaml.safe_load(backlog_path.read_text(encoding="utf-8"))
    items = backlog.get("items") or []
    declared = (backlog.get("source") or {}).get("item_count")

    problems: list[str] = []
    if declared != len(bullets):
        problems.append(
            f"source.item_count is {declared!r} but CLAUDE.md lists {len(bullets)} open bullets"
        )
    if len(items) != len(bullets):
        problems.append(f"backlog has {len(items)} items but CLAUDE.md lists {len(bullets)} open bullets")

    bullet_set = set(bullets)
    claimed = Counter(str(item.get("statement")) for item in items)
    for item in items:
        statement = str(item.get("statement"))
        if statement not in bullet_set:
            problems.append(f"item {item.get('id')!r}: statement is not byte-identical to any CLAUDE.md bullet")
    for bullet in bullets:
        if claimed[bullet] != 1:
            problems.append(
                f"CLAUDE.md bullet claimed by {claimed[bullet]} items, expected 1: {bullet[:72]!r}"
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude-md", type=Path, default=REPO_ROOT / "CLAUDE.md")
    parser.add_argument("--backlog", type=Path, default=REPO_ROOT / ".agent-loop" / "backlog.yaml")
    args = parser.parse_args()
    problems = compare(args.claude_md, args.backlog)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(f"backlog matches CLAUDE.md: {len(read_open_bullets(args.claude_md))} open items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
