from __future__ import annotations

import json
from pathlib import Path

import pytest

from valkey_scale_lab.runtime import docker_runtime


def test_process_cleanup_rejects_unverified_nodehost_before_signalling_pids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "capability_id": "local_full_flow",
                "scenario": "local_full_flow",
                "runtime": {"type": "docker_process", "run_id": "claimed-run"},
                "nodehosts": [
                    {
                        "nodehost_id": "nodehost-az-a-00",
                        "container_name": "unowned-container",
                    }
                ],
                "nodes": [
                    {
                        "ordinal": 0,
                        "nodehost_id": "nodehost-az-a-00",
                        "nodehost_container_name": "unowned-container",
                        "pid": 4242,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def fake_run_docker(args: list[str], **_kwargs: object) -> docker_runtime.DockerResult:
        commands.append(args)
        if args[:2] == ["inspect", "-f"]:
            return docker_runtime.DockerResult(stdout="{}", stderr="", returncode=0)
        return docker_runtime.DockerResult(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)

    with pytest.raises(docker_runtime.DockerRuntimeError, match="owned runtime resource"):
        docker_runtime.cleanup_scenario(
            state_path=state_path,
            artifacts_dir=tmp_path,
            out_path=tmp_path / "cleanup.json",
        )

    assert not any(args[:2] == ["exec", "unowned-container"] for args in commands)
