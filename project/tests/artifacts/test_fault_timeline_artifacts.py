from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_fault_timeline_fixtures_pass_contract_gate() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/assert_fault_timeline_contract.py", "--fixtures", "tests/fixtures/fault_timeline"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "PASS" in proc.stdout


def test_fault_timeline_fixture_jsonl_is_nonempty() -> None:
    for path in Path("tests/fixtures/fault_timeline").glob("*/fault_timeline_events.jsonl"):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert rows, path
        assert all(row["artifact_type"] == "fault_timeline_event" for row in rows)
