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


def _sample_row(index: int) -> dict:
    return dict(
        operation_id="cluster_setup",
        step_id="cluster_probe",
        command_kind="cluster_probe",
        argv=["valkey-cli", "-h", "127.0.0.1", "-p", str(7000 + index), "CLUSTER", "INFO"],
        started_at_unix_ms=0,
        ended_at_unix_ms=1,
        exit_code=0,
        stdout=f"cluster_state:ok {index}",
        stderr="",
        timeout_ms=5000,
        status="PASS",
        error_type="",
    )


def test_the_closed_log_is_sorted_by_sequence_whatever_order_rows_arrived(tmp_path: Path) -> None:
    """Recording appends; `close` writes the file sorted by sequence.

    Recording used to rewrite the whole log per row, which made the cost of one
    command grow with the number already recorded - measured 1.96 ms/row at 250
    and 47.39 at 4000, enough to time out a real exact-200. Appending is flat,
    and this pins the part that must not change with it: the artifact `close`
    leaves behind is still in sequence order, even when concurrent threads
    appended out of order.
    """
    from concurrent.futures import ThreadPoolExecutor

    recorder = CommandRecorder(
        capability_id="command_audit",
        run_id="unit-append",
        scenario="unit",
        artifacts_dir=tmp_path / "artifacts",
        log_dir=tmp_path / "logs",
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda i: recorder.record_result(**_sample_row(i)), range(64)))

    on_disk_before_close = [
        json.loads(line)["sequence"]
        for line in recorder.command_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = recorder.close()
    rows = [
        json.loads(line)
        for line in recorder.command_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert summary["total_commands"] == 64
    assert len(rows) == 64
    # Every row exactly once, and the closed artifact in sequence order.
    assert [row["sequence"] for row in rows] == list(range(1, 65))
    assert sorted(on_disk_before_close) == list(range(1, 65))
