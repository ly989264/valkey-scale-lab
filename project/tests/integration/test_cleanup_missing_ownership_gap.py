from __future__ import annotations

import json
from pathlib import Path

import pytest

from valkey_scale_lab.runtime import docker_runtime, teardown


def test_cleanup_rejects_state_missing_runtime_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "capability_id": "cluster_lifecycle",
                "scenario": "cluster_lifecycle",
                "nodes": [],
            }
        ),
        encoding="utf-8",
    )

    cleanup_calls: list[tuple[str, str]] = []

    def fake_cleanup(*, capability_id: str, run_id: str):
        cleanup_calls.append((capability_id, run_id))
        return [], {
            "cleanup_remove_containers_seconds": 0.0,
            "cleanup_remove_networks_seconds": 0.0,
        }

    monkeypatch.setattr(docker_runtime, "_cleanup_resources_by_label", fake_cleanup)
    monkeypatch.setattr(docker_runtime, "owned_resources", lambda **kwargs: [])

    # The refusal is the lifecycle's, not Docker's: cleanup declines state that
    # does not say which run it owns before it resolves a backend at all.
    with pytest.raises(teardown.TeardownError, match="ownership|run_id"):
        teardown.cleanup_scenario(
            state_path=state_path,
            artifacts_dir=tmp_path,
            out_path=tmp_path / "cleanup.json",
        )

    assert cleanup_calls == []
