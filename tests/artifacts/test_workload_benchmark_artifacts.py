from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from schema_validator import load_json, validate  # noqa: E402


def test_workload_benchmark_fixtures_validate_schema() -> None:
    schema = load_json(ROOT / "schemas/artifact/workload_windows.schema.json")
    for path in sorted((ROOT / "tests/fixtures/workload_benchmark").glob("*/workload_windows.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert validate(payload, schema) == []


def test_workload_benchmark_gate_accepts_fixtures() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/assert_workload_benchmark_contract.py"), "--fixtures", str(ROOT / "tests/fixtures/workload_benchmark")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
