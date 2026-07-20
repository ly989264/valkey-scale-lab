from __future__ import annotations

import json
import subprocess
from pathlib import Path

from valkey_scale_lab.runtime.command_recorder import CommandRecorder, command_recorder_context
from valkey_scale_lab.runtime.docker_runtime import run_docker


def test_run_docker_records_command_with_context(monkeypatch, tmp_path: Path) -> None:
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "ok\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    recorder = CommandRecorder(capability_id="command_audit", run_id="unit-runtime", scenario="unit", artifacts_dir=tmp_path / "artifacts", log_dir=tmp_path / "logs")
    with command_recorder_context(recorder):
        result = run_docker(["ps"], timeout=5, check=True)
    summary = recorder.close()

    assert result.stdout == "ok\n"
    assert summary["total_commands"] == 1
    assert "runtime_command" in summary["by_command_kind"]
    row = json.loads(recorder.command_log_path.read_text(encoding="utf-8"))
    assert isinstance(row["started_at_monotonic_ms"], (int, float))
    assert row["ended_at_monotonic_ms"] >= row["started_at_monotonic_ms"]
    assert row["monotonic_duration_ms"] == round(
        row["ended_at_monotonic_ms"] - row["started_at_monotonic_ms"],
        3,
    )
