from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))
from schema_validator import load_json, validate
from valkey_scale_lab.runtime.command_recorder import CommandRecorder


def test_command_log_fixtures_validate_schema() -> None:
    schema = load_json(Path("schemas/artifact/command_log_entry.schema.json"))
    for path in sorted(Path("tests/fixtures/command_log").glob("*/command_log.jsonl")):
        if path.parent.name == "empty":
            assert path.read_text(encoding="utf-8").strip() == ""
            continue
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert rows, path
        for row in rows:
            assert validate(row, schema) == []


def test_command_recorder_writes_log_and_summary(tmp_path: Path) -> None:
    recorder = CommandRecorder(capability_id="command_audit", run_id="unit-command-recorder", scenario="unit", artifacts_dir=tmp_path / "artifacts", log_dir=tmp_path / "logs")
    recorder.record_result(
        operation_id="cluster_setup",
        step_id="cluster_probe",
        command_kind="cluster_probe",
        argv=["valkey-cli", "-p", "7000", "PING"],
        started_at_unix_ms=1000,
        ended_at_unix_ms=1002,
        exit_code=0,
        stdout="PONG",
        stderr="",
        timeout_ms=5000,
        status="PASS",
        error_type="",
        node={"logical_id": "node-0", "nodehost_id": "nh-0", "client_port": 7000, "host": "127.0.0.1"},
    )
    summary = recorder.close()

    log_path = tmp_path / "artifacts" / "command_log.jsonl"
    assert log_path.exists()
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["command_kind"] == "cluster_probe"
    assert summary["total_commands"] == 1
    assert (tmp_path / "artifacts" / "command_audit_summary.json").exists()


def test_empty_command_log_fixture_is_gate_invalid() -> None:
    assert Path("tests/fixtures/command_log/empty/command_log.jsonl").read_text(encoding="utf-8").strip() == ""
