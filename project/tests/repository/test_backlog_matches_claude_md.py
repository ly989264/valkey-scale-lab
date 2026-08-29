from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
SCRIPT = ROOT / "scripts" / "assert_backlog_matches_claude_md.py"


def _run(claude_md: Path, backlog: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--claude-md", str(claude_md), "--backlog", str(backlog)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_checked_in_backlog_matches_claude_md() -> None:
    result = _run(REPO / "CLAUDE.md", REPO / ".agent-loop" / "backlog.yaml")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "backlog matches CLAUDE.md: 21 open items"


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "## Where the work stands\n\n### What is still open\n\n"
        "**Group A**\n"
        "- First bullet, hard-wrapped\n  across two lines.\n"
        "- Second bullet on one line.\n\n"
        "**Group B**\n"
        "- Third bullet.\n\n"
        "## Working rules\n\n- Not an open item.\n",
        encoding="utf-8",
    )
    backlog = tmp_path / "backlog.yaml"
    backlog.write_text(
        yaml.safe_dump(
            {
                "source": {"item_count": 3},
                "items": [
                    {"id": "a", "statement": "First bullet, hard-wrapped across two lines."},
                    {"id": "b", "statement": "Second bullet on one line."},
                    {"id": "c", "statement": "Third bullet."},
                ],
            }
        ),
        encoding="utf-8",
    )
    return claude_md, backlog


def test_joins_hard_wraps_and_stops_at_the_next_heading(tmp_path: Path) -> None:
    claude_md, backlog = _fixture(tmp_path)
    assert _run(claude_md, backlog).returncode == 0


def test_rejects_a_statement_that_drifted_by_one_byte(tmp_path: Path) -> None:
    claude_md, backlog = _fixture(tmp_path)
    document = yaml.safe_load(backlog.read_text(encoding="utf-8"))
    document["items"][1]["statement"] = "Second bullet on one line"
    backlog.write_text(yaml.safe_dump(document), encoding="utf-8")
    result = _run(claude_md, backlog)
    assert result.returncode == 1
    assert "item 'b': statement is not byte-identical" in result.stderr
    assert "claimed by 0 items" in result.stderr


def test_rejects_a_count_that_does_not_match(tmp_path: Path) -> None:
    claude_md, backlog = _fixture(tmp_path)
    document = yaml.safe_load(backlog.read_text(encoding="utf-8"))
    document["items"].pop()
    backlog.write_text(yaml.safe_dump(document), encoding="utf-8")
    result = _run(claude_md, backlog)
    assert result.returncode == 1
    assert "source.item_count is 3 but CLAUDE.md lists 3" not in result.stderr
    assert "backlog has 2 items but CLAUDE.md lists 3 open bullets" in result.stderr
