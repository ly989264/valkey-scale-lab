from __future__ import annotations

import pytest

from valkey_scale_lab.runtime import docker_runtime


def test_p36_rejects_partition_without_client_availability_measurement() -> None:
    with pytest.raises(docker_runtime.DockerRuntimeError, match="client|availability|workload"):
        docker_runtime._p36_execute_fault_probe(
            run_id="review-o4-round-2",
            scale=50,
            scenario_id="network_partition",
            action=lambda: {
                "actions": [
                    "docker network disconnect owned-network owned-container",
                    "docker network connect owned-network owned-container",
                ],
                "disconnect_verified": True,
                "majority_cluster_state_ok": True,
                "isolated_cluster_state_ok": False,
                "majority_cluster_info": "cluster_state:ok",
                "isolated_cluster_info": "cluster_state:fail",
            },
            command_log=[],
            events=[],
            metrics=[],
            windows=[],
        )
