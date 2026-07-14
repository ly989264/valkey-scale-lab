from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from valkey_scale_lab.meta_loop_v5.runner import ProgramRunner


def test_docker_access_failure_is_retried_but_success_is_cached(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    probe = project / "probe.py"
    probe.write_text("raise SystemExit(0)\n", encoding="utf-8")
    runner = ProgramRunner(project, tmp_path, tmp_path / "logs", 2400)
    check = {
        "id": "real-capture",
        "level": 3,
        "command": ["python3", "probe.py"],
        "timeout_seconds": 30,
        "inputs": ["probe.py"],
    }
    outcomes = iter(
        [
            SimpleNamespace(
                returncode=1,
                stdout="real gate requires an available Docker daemon: permission denied while trying to connect to the docker API",
            ),
            SimpleNamespace(returncode=0, stdout="PASS\n"),
        ]
    )
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        return next(outcomes)

    monkeypatch.setattr("valkey_scale_lab.meta_loop_v5.runner.subprocess.run", run)
    cache: dict = {}

    first = runner.run(check, cache)
    second = runner.run(check, cache)
    third = runner.run(check, cache)

    assert first["status"] == "FAIL"
    assert first["cache_key"] not in cache or cache[first["cache_key"]]["status"] == "PASS"
    assert second["status"] == "PASS" and second["cached"] is False
    assert third["status"] == "PASS" and third["cached"] is True
    assert len(calls) == 2
