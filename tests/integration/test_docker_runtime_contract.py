from __future__ import annotations

from pathlib import Path

import pytest

from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.runtime.docker_runtime import DockerRuntimeError


def test_p03_node_specs_are_deterministic() -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/single_mac_6node.yaml"))
    nodes = docker_runtime._node_specs(config, "P03_LOCAL_DOCKER_VALKEY", "cluster_smoke")
    assert [node["logical_id"] for node in nodes] == [
        "shard-0000-primary",
        "shard-0001-primary",
        "shard-0002-primary",
        "shard-0000-replica-00",
        "shard-0001-replica-00",
        "shard-0002-replica-00",
    ]
    assert [node["client_port"] for node in nodes] == [7000, 7001, 7002, 7003, 7004, 7005]
    assert len({node["container_name"] for node in nodes}) == 6
    assert "p03-local-docker-valkey-cluster-smoke" in nodes[0]["container_name"]
    assert {node["host_id"] for node in nodes} == {"local"}


def test_p10_node_specs_preserve_multi_host_placement() -> None:
    config = docker_runtime.normalize_config(docker_runtime.parse_config_file("templates/configs/single_mac_6node.yaml"))
    config["hosts"] = [
        {"host_id": "local-a", "ip": "127.0.0.1", "docker_endpoint": "local", "labels": ["worker"]},
        {"host_id": "local-b", "ip": "127.0.0.1", "docker_endpoint": "local", "labels": ["worker"]},
    ]
    nodes = docker_runtime._node_specs(config, "P10_MULTI_HOST_ORCHESTRATION", "orchestrated_localhost")
    assert [node["host_id"] for node in nodes] == ["local-a", "local-b", "local-a", "local-b", "local-a", "local-b"]


def test_slot_ranges_cover_all_slots_for_scale_rungs() -> None:
    ranges = docker_runtime._slot_ranges(15)
    assert ranges[0][0] <= 8014 <= ranges[0][1]
    assert len(ranges) == 15
    assert sum((end - start + 1) for start, end in ranges) == 16384
    assert sorted(ranges)[0][0] == 0
    assert sorted(ranges)[-1][1] == 16383


def test_port_collision_check_rejects_bound_port(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSocket:
        def __enter__(self) -> "FakeSocket":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def setsockopt(self, *args: object) -> None:
            return None

        def bind(self, *args: object) -> None:
            raise OSError("already bound")

    monkeypatch.setattr(docker_runtime.socket, "socket", lambda *args, **kwargs: FakeSocket())
    with pytest.raises(DockerRuntimeError, match="not available"):
        docker_runtime._check_ports_free([7000])


def test_cleanup_report_shape_without_owned_resources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "schema_version": "v1",
        "cluster_id": "test",
        "phase_id": "P03_LOCAL_DOCKER_VALKEY",
        "runtime": {"run_id": "test-run"},
        "nodes": [],
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(docker_runtime.json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(docker_runtime, "cleanup_by_label", lambda *, phase, run_id: [])
    monkeypatch.setattr(docker_runtime, "owned_resources", lambda *, phase, run_id: [])
    report = docker_runtime.cleanup_scenario(state_path=state_path, artifacts_dir=tmp_path, out_path=tmp_path / "cleanup.json")
    assert report["status"] == "PASS"
    assert report["resources_remaining"] == []


def test_cleanup_removes_fault_state_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "schema_version": "v1",
        "cluster_id": "test",
        "phase_id": "P08_FAILOVER_SPLIT_BRAIN",
        "runtime": {"run_id": "test-run"},
        "nodes": [],
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(docker_runtime.json.dumps(state), encoding="utf-8")
    fault_state = tmp_path / "fault_state_fault-primary-stop.json"
    fault_state.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(docker_runtime, "cleanup_by_label", lambda *, phase, run_id: [])
    monkeypatch.setattr(docker_runtime, "owned_resources", lambda *, phase, run_id: [])
    report = docker_runtime.cleanup_scenario(state_path=state_path, artifacts_dir=tmp_path, out_path=tmp_path / "cleanup.json")
    assert report["status"] == "PASS"
    assert not fault_state.exists()
    assert any(action["type"] == "fault_state" for action in report["cleanup_actions"])


def test_p10_cleanup_appends_orchestrator_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "schema_version": "v1",
        "cluster_id": "test",
        "phase_id": "P10_MULTI_HOST_ORCHESTRATION",
        "runtime": {"run_id": "test-run"},
        "nodes": [],
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(docker_runtime.json.dumps(state), encoding="utf-8")
    orch_report = {
        "schema_version": "v1",
        "artifact_type": "orchestration_report",
        "phase_id": "P10_MULTI_HOST_ORCHESTRATION",
        "run_id": "test-run",
        "status": "PASS",
        "operations": [{"operation": "prepare", "status": "PASS"}],
    }
    (tmp_path / "orchestration_report.json").write_text(docker_runtime.json.dumps(orch_report), encoding="utf-8")
    monkeypatch.setattr(docker_runtime, "cleanup_by_label", lambda *, phase, run_id: [])
    monkeypatch.setattr(docker_runtime, "owned_resources", lambda *, phase, run_id: [])

    report = docker_runtime.cleanup_scenario(state_path=state_path, artifacts_dir=tmp_path, out_path=tmp_path / "cleanup.json")
    updated = docker_runtime.json.loads((tmp_path / "orchestration_report.json").read_text(encoding="utf-8"))

    assert report["status"] == "PASS"
    assert updated["operations"][-1]["operation"] == "stop"
    assert updated["operations"][-1]["details"]["idempotent"] is True


def test_management_ops_report_taxonomy(tmp_path: Path) -> None:
    operations = [
        {"operation": "meet", "status": "PASS", "duration_seconds": 0.1},
        {
            "operation": "remove_node",
            "status": "SKIPPED_WITH_REASON",
            "duration_seconds": 0.0,
            "reason": "not destructive in smoke",
        },
    ]
    out = tmp_path / "management_ops_report.json"
    docker_runtime.write_management_ops_report(out, "P04_CLUSTER_MANAGEMENT_OPS", "management_ops", "run", operations)
    report = docker_runtime.json.loads(out.read_text(encoding="utf-8"))
    assert report["artifact_type"] == "management_ops_report"
    assert report["status"] == "PASS"
    assert report["summary"]["passed"] == 1
    assert report["summary"]["skipped_with_reason"] == 1


def test_latency_summary_has_required_percentiles() -> None:
    summary = docker_runtime._latency_summary([1.0, 2.0, 3.0, 4.0])
    assert summary["p50"] == 2.5
    assert summary["p95"] > summary["p50"]
    assert summary["p99"] >= summary["p95"]
    assert summary["sample_count"] == 4


def test_empty_latency_summary_marks_missing() -> None:
    summary = docker_runtime._latency_summary([])
    assert summary["p50"]["status"] == "MISSING"
    assert summary["p95"]["status"] == "MISSING"
    assert summary["p99"]["status"] == "MISSING"


def test_parse_info_and_missing_integer_encoding() -> None:
    parsed = docker_runtime._parse_info("# Server\nuptime_in_seconds:12\nused_memory:not-an-int\n")
    assert parsed["uptime_in_seconds"] == "12"
    assert docker_runtime._int_or_missing(parsed["uptime_in_seconds"]) == 12
    assert docker_runtime._int_or_missing(parsed["used_memory"]) == "MISSING"
    assert docker_runtime._int_or_missing(None) == "MISSING"


def test_event_shape() -> None:
    event = docker_runtime._event("P06_OBSERVABILITY_METRICS", "run", "sampled", "info", {"node": "n1"})
    assert event["artifact_type"] == "event"
    assert event["severity"] == "info"
    assert event["details"]["node"] == "n1"
