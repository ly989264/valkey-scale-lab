from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from valkey_scale_lab.observability import resource_agent
from valkey_scale_lab.observability.resources import (
    HOST_INTERVAL_SECONDS,
    PROCESS_INTERVAL_SECONDS,
)
from valkey_scale_lab.runtime import docker_runtime


SPEC = {
    "sampler_id": "nodehost-az-a-00",
    "processes": [
        {"logical_id": "shard-0000-primary", "pid": 29},
        {"logical_id": "shard-0000-replica-00", "pid": 41},
    ],
    "expected_gone_processes": [{"logical_id": "shard-0001-primary", "pid": 57}],
}


def test_agent_samples_the_nodehost_it_runs_on() -> None:
    runner = resource_agent.build_runner(SPEC)

    # The whole point of the agent: the sampler reads its own procfs, not
    # another machine's through a host kernel.
    assert runner.sampler.proc_root == Path("/proc")
    assert runner.sampler.cgroup_root == Path("/sys/fs/cgroup")

    # Intervals come from the sampler, unchanged.
    assert runner.host_interval == HOST_INTERVAL_SECONDS == 5.0
    assert runner.process_interval == PROCESS_INTERVAL_SECONDS == 60.0

    assert [p.logical_id for p in runner.sampler.processes] == [
        "shard-0000-primary",
        "shard-0000-replica-00",
    ]
    assert [p.pid for p in runner.sampler.processes] == [29, 41]


def test_agent_learns_about_an_expected_gone_window_from_a_marker(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "expected_gone_active"
    runner = resource_agent.build_runner(SPEC, expected_gone_active_file=marker)

    assert runner.sampler._expected_gone_active() is False
    marker.touch()
    # No new session was needed to learn this.
    assert runner.sampler._expected_gone_active() is True


def test_agent_without_a_marker_reports_no_expected_gone_window() -> None:
    runner = resource_agent.build_runner(SPEC)

    assert runner.sampler._expected_gone_active() is False


def _agent_with_recorder(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[list[str]]]:
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run_docker(args: list[str], **_kwargs: Any) -> Any:
        calls.append(list(args))
        return Result()

    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    agent = docker_runtime.NodehostResourceAgent(
        container="vslab-run-nodehost-az-a-00",
        sampler_id="nodehost-az-a-00",
        processes=[docker_runtime.ProcessSpec("shard-0000-primary", 29)],
    )
    return agent, calls


def test_agent_start_launches_one_long_lived_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, calls = _agent_with_recorder(monkeypatch)

    agent.start()

    execs = [c for c in calls if c[0] == "exec"]
    # A fixed two sessions to set up and launch, then none: sampling happens
    # inside the launched process, so the number of container sessions does not
    # grow with the length of the window.
    assert len(execs) == 2
    assert execs[0][2:4] == ["mkdir", "-p"]
    launch = execs[1][-1]
    assert "valkey_scale_lab.observability.resource_agent" in launch
    assert "nohup" in launch
    assert launch.rstrip().endswith("agent.pid")

    # The package is copied in once, not per sample.
    copies = [c for c in calls if c[0] == "cp"]
    assert len(copies) == 2
    assert any(c[-1].endswith("valkey_scale_lab") for c in copies)
    assert any(c[-1].endswith("spec.json") for c in copies)


def test_agent_start_twice_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    agent, _calls = _agent_with_recorder(monkeypatch)
    agent.start()

    with pytest.raises(docker_runtime.DockerRuntimeError, match="already running"):
        agent.start()


def test_agent_stop_before_start_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, _calls = _agent_with_recorder(monkeypatch)

    with pytest.raises(docker_runtime.DockerRuntimeError, match="never started"):
        agent.stop()


def test_agent_stop_signals_then_collects_one_batch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    document = {"static": {"sampler_id": "nodehost-az-a-00"}, "samples": [], "errors": []}
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run_docker(args: list[str], **_kwargs: Any) -> Any:
        calls.append(list(args))
        if args[0] == "cp" and args[1].startswith("vslab-"):
            Path(args[2]).write_text(__import__("json").dumps(document), encoding="utf-8")
        return Result()

    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    agent = docker_runtime.NodehostResourceAgent(
        container="vslab-run-nodehost-az-a-00",
        sampler_id="nodehost-az-a-00",
        processes=[docker_runtime.ProcessSpec("shard-0000-primary", 29)],
    )
    agent.start()
    calls.clear()

    assert agent.stop() == document

    execs = [c for c in calls if c[0] == "exec"]
    copies = [c for c in calls if c[0] == "cp"]
    # Stopping is one session, and the samples come back as a single batch.
    assert len(execs) == 1
    assert "kill -TERM" in execs[0][-1]
    assert len(copies) == 1


def test_agent_stop_reports_a_missing_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        returncode = 1
        stdout = ""
        stderr = "Traceback: agent died"

    monkeypatch.setattr(docker_runtime, "run_docker", lambda *a, **k: Result())
    agent = docker_runtime.NodehostResourceAgent(
        container="vslab-run-nodehost-az-a-00",
        sampler_id="nodehost-az-a-00",
        processes=[docker_runtime.ProcessSpec("shard-0000-primary", 29)],
    )
    agent._started = True

    with pytest.raises(
        docker_runtime.DockerRuntimeError, match="did not write its samples"
    ):
        agent.stop()
