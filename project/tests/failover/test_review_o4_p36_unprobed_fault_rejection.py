from __future__ import annotations

import pytest

from valkey_scale_lab.runtime import docker_runtime


def test_p36_rejects_unprobed_partition_as_real_evidence() -> None:
    with pytest.raises(docker_runtime.DockerRuntimeError, match="probe|observ"):
        docker_runtime._p36_execute_fault_probe(
            run_id="review-o4",
            scale=50,
            scenario_id="network_partition",
            action=lambda: {
                "actions": [
                    "docker network disconnect owned-network owned-container",
                    "docker network connect owned-network owned-container",
                ]
            },
            command_log=[],
            events=[],
            metrics=[],
            windows=[],
        )
