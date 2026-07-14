from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab.runtime import docker_runtime


def test_cleanup_rejects_failed_owned_resource_discovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "cluster_id": "cleanup-discovery-gap",
                "capability_id": "cluster_lifecycle",
                "scenario": "cluster_lifecycle",
                "runtime": {"run_id": "cleanup-discovery-gap"},
                "nodes": [],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        docker_runtime,
        "run_docker",
        lambda *args, **kwargs: docker_runtime.DockerResult(
            "", "docker daemon unavailable", 1
        ),
    )

    report = docker_runtime.cleanup_scenario(
        state_path=state_path,
        artifacts_dir=tmp_path,
        out_path=tmp_path / "cleanup.json",
    )

    assert report["status"] == "FAIL"
