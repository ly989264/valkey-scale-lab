from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts import m2_performance_capture as capture


def _analysis() -> dict[str, Any]:
    return {
        "cpu": {"throttled_usec_delta": 1},
        "memory": {},
        "network": {
            "eth0": {
                "rx_errors": {"delta": 0},
                "rx_drops": {"delta": 0},
                "tx_errors": {"delta": 0},
                "tx_drops": {"delta": 0},
            }
        },
        "processes": {"node-a": {"cpu_ticks_delta": 3}},
        "process_totals": {
            "rss_bytes_max_sum": 100,
            "fd_count_max_sum": 4,
        },
        "collector": {"overrun_count": 0},
        "expected_gone_processes": [],
        "timestamps": [],
        "timeline_correlation": {},
    }


def _observation() -> dict[str, Any]:
    analysis = _analysis()
    return {
        "artifact_type": "resource_observation",
        "status": "PASS",
        "duration_seconds": 5.0,
        "checks": [
            {
                "name": "resource_analysis:host-a",
                "status": "OK",
                "evidence": analysis,
            }
        ],
        "resource_documents": [
            {
                "static": {"sampler_id": "host-a"},
                "samples": [{"kind": "host"}, {"kind": "process"}],
                "errors": [],
            }
        ],
        "resource_analyses": [{"sampler_id": "host-a", "analysis": analysis}],
        "m2_protocol_metrics": {
            "status": "PASS",
            "metrics": {
                "connection_count": 2,
                "cluster_bus_bytes": 30,
                "cluster_link_errors": 0,
                "buffer_overflows": 0,
            },
            "coverage": {
                "expected_live_node_count": 1,
                "node_metric_count": 1,
                "topology_observer_count": 1,
                "missing_live_nodes": [],
                "errors": [],
            },
        },
    }


def test_validate_resource_report_accepts_new_observation_contract() -> None:
    report = capture._validate_resource_report(_observation())

    assert report["resource_summary"]["process_rss_bytes_max_sum"] == 100
    assert report["resource_summary"]["process_fd_count_max_sum"] == 4
    assert report["resource_summary"]["connection_count"] == 2
    assert report["resource_summary"]["cluster_bus_bytes"] == 30


def test_validate_resource_report_rejects_missing_analyzer() -> None:
    report = _observation()
    report["checks"] = []
    report["resource_analyses"] = []

    try:
        capture._validate_resource_report(report)
    except capture.CaptureError as exc:
        assert "analyzer" in str(exc)
    else:
        raise AssertionError("missing analyzer output must fail")


def test_validate_resource_report_rejects_missing_valkey_cluster_metrics() -> None:
    report = _observation()
    report["m2_protocol_metrics"]["status"] = "ERROR"

    try:
        capture._validate_resource_report(report)
    except capture.CaptureError as exc:
        assert "protocol resource metrics" in str(exc)
    else:
        raise AssertionError("missing Valkey cluster metrics must fail")


class FakeRespConnection:
    calls: list[tuple[int, tuple[Any, ...]]] = []
    failures: set[int] = set()
    bus_by_port: dict[int, int] = {}

    def __init__(self, endpoint: Any, *, timeout: float) -> None:
        self.endpoint = endpoint

    def __enter__(self) -> "FakeRespConnection":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute_many(self, commands: list[tuple[str, ...]]) -> list[str]:
        port = int(self.endpoint.port)
        if port in self.failures:
            raise OSError("connection refused")
        self.calls.extend((port, tuple(command)) for command in commands)
        bus = self.bus_by_port.get(port, 100)
        return [
            "connected_clients:2\n",
            "cluster_stats_bytes_sent:%d\ncluster_stats_bytes_received:%d\n"
            "total_cluster_links_buffer_limit_exceeded:0\n" % (bus, bus),
        ]

    def execute(self, *command: str) -> str:
        port = int(self.endpoint.port)
        if port in self.failures:
            raise OSError("connection refused")
        self.calls.append((port, tuple(command)))
        return (
            f"id-{port} 127.0.0.1:{port}@{port + 10000} myself,master - 0 0 1 connected 0-16383\n"
        )


def _state(node_count: int = 1) -> dict[str, Any]:
    return {
        "nodes": [
            {
                "logical_id": f"node-{idx}",
                "pid": 1000 + idx,
                "host": "127.0.0.1",
                "client_port": 7400 + idx,
            }
            for idx in range(node_count)
        ]
    }


def test_m2_protocol_metrics_complete_path_updates_resource_report(
    monkeypatch: Any, tmp_path: Path
) -> None:
    FakeRespConnection.calls = []
    FakeRespConnection.failures = set()
    FakeRespConnection.bus_by_port = {7400: 150}
    monkeypatch.setattr(capture, "RespConnection", FakeRespConnection)
    report = _observation()
    start = {
        "status": "PASS",
        "expected_live_nodes": ["node-0"],
        "node_metrics": [
            {
                "logical_id": "node-0",
                "connection_count": 1,
                "cluster_bus_bytes": 200,
                "buffer_overflows": 0,
            }
        ],
        "topology_observers": [
            {"logical_id": "node-0", "cluster_link_count": 1, "cluster_link_errors": 0}
        ],
        "errors": [],
    }

    capture._attach_m2_protocol_metrics(
        report,
        tmp_path / "resource_observation.json",
        _state(),
        start_boundary=start,
    )
    validated = capture._validate_resource_report(report)

    assert validated["resource_summary"]["connection_count"] == 2
    assert validated["resource_summary"]["cluster_bus_bytes"] == 100
    assert FakeRespConnection.calls == [
        (7400, ("INFO", "clients")),
        (7400, ("CLUSTER", "INFO")),
        (7400, ("CLUSTER", "NODES")),
    ]


def test_m2_protocol_metric_failure_marks_observation_error(
    monkeypatch: Any, tmp_path: Path
) -> None:
    FakeRespConnection.calls = []
    FakeRespConnection.failures = {7401}
    FakeRespConnection.bus_by_port = {7400: 150, 7401: 150}
    monkeypatch.setattr(capture, "RespConnection", FakeRespConnection)
    report = _observation()

    capture._attach_m2_protocol_metrics(
        report,
        tmp_path / "resource_observation.json",
        _state(2),
        start_boundary=None,
    )

    assert report["status"] == "ERROR"
    try:
        capture._validate_resource_report(report)
    except capture.CaptureError as exc:
        assert "protocol resource metrics" in str(exc)
    else:
        raise AssertionError("live-node M2 protocol failure must fail collection")


def test_m2_protocol_expected_gone_node_is_excluded(
    monkeypatch: Any, tmp_path: Path
) -> None:
    FakeRespConnection.calls = []
    FakeRespConnection.failures = {7401}
    FakeRespConnection.bus_by_port = {7400: 150, 7401: 150}
    monkeypatch.setattr(capture, "RespConnection", FakeRespConnection)
    report = _observation()
    start = {
        "status": "PASS",
        "expected_live_nodes": ["node-0", "node-1"],
        "node_metrics": [
            {"logical_id": "node-0", "connection_count": 1, "cluster_bus_bytes": 200, "buffer_overflows": 0},
            {"logical_id": "node-1", "connection_count": 1, "cluster_bus_bytes": 200, "buffer_overflows": 0},
        ],
        "topology_observers": [
            {"logical_id": "node-0", "cluster_link_count": 2, "cluster_link_errors": 0}
        ],
        "errors": [],
    }

    capture._attach_m2_protocol_metrics(
        report,
        tmp_path / "resource_observation.json",
        _state(2),
        expected_gone_processes=[
            {"logical_id": "node-1", "pid": 1001, "client_port": 7401}
        ],
        expected_gone_active=True,
        start_boundary=start,
    )
    validated = capture._validate_resource_report(report)

    assert validated["resource_summary"]["connection_count"] == 2
    assert {port for port, _command in FakeRespConnection.calls} == {7400}


def test_m2_capture_uses_plain_resource_runners(
    monkeypatch: Any, tmp_path: Path
) -> None:
    from valkey_scale_lab.observability import resource_observation
    from valkey_scale_lab.runtime import docker_runtime

    runner_kwargs: list[dict[str, Any]] = []

    def fake_runners(*_args: Any, **kwargs: Any) -> list[str]:
        runner_kwargs.append(kwargs)
        return ["runner"]

    def fake_write(path: Path, **_kwargs: Any) -> dict[str, Any]:
        report = _observation()
        path.write_text("{}", encoding="utf-8")
        return report

    monkeypatch.setattr(docker_runtime, "_resource_runners_for_nodes", fake_runners)
    monkeypatch.setattr(resource_observation, "write_resource_observation", fake_write)
    monkeypatch.setattr(
        capture,
        "_collect_m2_protocol_boundary",
        lambda *_args, **_kwargs: {
            "status": "PASS",
            "expected_live_nodes": ["node-0"],
            "node_metrics": [
                {"logical_id": "node-0", "connection_count": 1, "cluster_bus_bytes": 2, "buffer_overflows": 0}
            ],
            "topology_observers": [
                {"logical_id": "node-0", "cluster_link_count": 1, "cluster_link_errors": 0}
            ],
            "errors": [],
        },
    )

    capture._capture_resource_observation(
        tmp_path,
        _state(),
        1.0,
    )

    assert runner_kwargs == [{"expected_gone_processes": None, "expected_gone_active": None}]


def test_discovery_safety_uses_correctness_not_resource_values() -> None:
    trial = {
        "correctness": {
            "clean_topology": True,
            "split_brain": False,
            "slot_loss": False,
            "unexpected_pfail": 0,
            "unexpected_fail": 0,
            "unexpected_promotions": 0,
        },
        "resource_observation": {
            metric: 0.0 for metric in capture.RESOURCE_METRICS
        },
    }
    trial["resource_observation"]["process_rss_bytes_max_sum"] = 999999999
    trial["resource_observation"]["process_fd_count_max_sum"] = 999999

    assert capture._discovery_safety_clean(trial)


def test_discovery_resource_check_treats_high_values_as_diagnostics() -> None:
    baseline = {
        "resource_observation": {
            metric: 1.0 for metric in capture.RESOURCE_METRICS
        }
    }
    candidate = deepcopy(baseline)
    candidate["resource_observation"]["process_rss_bytes_max_sum"] = 1000000.0

    assert capture._discovery_resource_clean(baseline, candidate)
