from __future__ import annotations

import inspect
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
                "cluster_link_observer_count": 1,
                "missing_live_nodes": [],
                "errors": [],
            },
            "boundaries": {
                "end": {
                    "expected_live_nodes": ["node-a"],
                    "node_metrics": [
                        {
                            "logical_id": "node-a",
                            "valkey_node_id": "id-node-a",
                        }
                    ],
                    "cluster_link_observers": [
                        {
                            "logical_id": "node-a",
                            "valkey_node_id": "id-node-a",
                            "monotonic": 1.0,
                            "status": "OK",
                            "link_rows": [],
                            "expected_links": [],
                            "missing_links": [],
                            "cluster_link_count": 0,
                            "cluster_link_errors": 0,
                            "errors": [],
                        }
                    ],
                }
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
        values: list[Any] = []
        for command in commands:
            if tuple(command) == ("INFO", "clients"):
                values.append("connected_clients:2\n")
            elif tuple(command) == ("CLUSTER", "INFO"):
                values.append(
                    "cluster_stats_bytes_sent:%d\ncluster_stats_bytes_received:%d\n"
                    "total_cluster_links_buffer_limit_exceeded:0\n" % (bus, bus)
                )
            elif tuple(command) == ("CLUSTER", "MYID"):
                values.append(f"id-{port}")
            elif tuple(command) == ("CLUSTER", "LINKS"):
                values.append(
                    [
                        {
                            b"direction": b"to",
                            b"node": f"peer-{port}".encode(),
                            b"create-time": 1,
                            b"events": b"r",
                            b"send-buffer-allocated": 48,
                            b"send-buffer-used": 1,
                        }
                    ]
                )
            else:
                raise AssertionError(f"unexpected command {command}")
        return values

    def execute(self, *command: str) -> str:
        port = int(self.endpoint.port)
        if port in self.failures:
            raise OSError("connection refused")
        self.calls.append((port, tuple(command)))
        if tuple(command) == ("CLUSTER", "LINKS"):
            return []  # type: ignore[return-value]
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


def _link_observer(logical_id: str, node_id: str, peers: list[str] | None = None) -> dict[str, Any]:
    peer_ids = peers or []
    expected_links = [
        {"peer_node_id": peer_id, "direction": direction}
        for peer_id in peer_ids
        for direction in ("from", "to")
    ]
    link_rows = [
        {
            "peer_node_id": row["peer_node_id"],
            "direction": row["direction"],
            "events": "r",
            "create_time": 1,
            "send_buffer_allocated": 48,
            "send_buffer_used": 1,
            "read_event_registered": True,
            "write_event_registered": False,
            "status": "OK",
        }
        for row in expected_links
    ]
    return {
        "logical_id": logical_id,
        "valkey_node_id": node_id,
        "monotonic": 1.0,
        "status": "OK",
        "link_rows": link_rows,
        "expected_links": expected_links,
        "missing_links": [],
        "cluster_link_count": len(link_rows),
        "cluster_link_errors": 0,
        "errors": [],
    }


def _protocol_boundary(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    expected_live = [str(node["logical_id"]) for node in nodes]
    node_metrics = [
        {
            "logical_id": str(node["logical_id"]),
            "valkey_node_id": str(node["valkey_node_id"]),
            "connection_count": node.get("connection_count", 1),
            "cluster_bus_bytes": node.get("cluster_bus_bytes", 200),
            "buffer_overflows": node.get("buffer_overflows", 0),
            "cluster_stats_bytes_sent": node.get("cluster_stats_bytes_sent", 100),
            "cluster_stats_bytes_received": node.get("cluster_stats_bytes_received", 100),
            "total_cluster_links_buffer_limit_exceeded": node.get("total_cluster_links_buffer_limit_exceeded", 0),
        }
        for node in nodes
    ]
    node_ids = [str(node["valkey_node_id"]) for node in nodes]
    observers = [
        _link_observer(
            str(node["logical_id"]),
            str(node["valkey_node_id"]),
            [peer_id for peer_id in node_ids if peer_id != str(node["valkey_node_id"])],
        )
        for node in nodes[: min(capture.M2_PROTOCOL_OBSERVER_COUNT, len(nodes))]
    ]
    return {
        "status": "PASS",
        "expected_live_nodes": expected_live,
        "node_metrics": node_metrics,
        "cluster_link_observers": observers,
        "errors": [],
    }


def test_m2_normal_observation_entries_use_scalable_observability_sources() -> None:
    sources = {
        "topology": inspect.getsource(capture._capture_topology),
        "stability": inspect.getsource(capture._capture_stability_observation),
        "fault": inspect.getsource(capture._capture_fault_window),
    }

    for source in sources.values():
        assert "_probe_endpoint" not in source
        assert '"CLUSTER", "NODES"' not in source
        assert "CLUSTER NODES" not in source
    assert "FullClusterValidator" in sources["topology"]
    assert "LightClusterProbe" in sources["stability"]
    assert "SentinelLane" in sources["stability"]
    assert "_capture_data_path" not in sources["stability"]
    assert "_capture_resource_observation" not in sources["stability"]
    assert "AffectedShardObserver" in sources["fault"]
    assert sources["fault"].count("FullClusterValidator(") == 1


def test_fault_topology_facts_require_affected_shard_stability_before_full_validation() -> None:
    logical_to_node_id = {"primary-0": "id-primary-0", "replica-0": "id-replica-0"}
    replacement_by_shard = {"shard-0": "replica-0"}
    target_node_ids = {"id-primary-0"}
    unstable = [
        {
            "shard_id": "shard-0",
            "observation": {
                "monotonic": 10.0,
                "rows": [
                    {
                        "logical_id": "replica-0",
                        "status": "OK",
                        "cluster_state": "ok",
                        "failure_reports": {"id-primary-0": 0, "id-replica-0": 0},
                    }
                ],
                "candidate": None,
            },
        }
    ]
    stable = [
        {
            "shard_id": "shard-0",
            "observation": {
                "monotonic": 10.5,
                "rows": [
                    {
                        "logical_id": "replica-0",
                        "status": "OK",
                        "cluster_state": "ok",
                        "failure_reports": {"id-primary-0": 0, "id-replica-0": 0},
                    }
                ],
                "candidate": {"primary": "replica-0"},
            },
        }
    ]

    assert not capture._affected_shard_topology_facts(
        unstable,
        target_node_ids=target_node_ids,
        replacement_by_shard=replacement_by_shard,
        logical_to_node_id=logical_to_node_id,
        expected_nodes=2,
    )["cluster_ok_all_slots"]
    stable_without_full = capture._affected_shard_topology_facts(
        stable,
        target_node_ids=target_node_ids,
        replacement_by_shard=replacement_by_shard,
        logical_to_node_id=logical_to_node_id,
        expected_nodes=2,
    )
    stable_with_full = capture._affected_shard_topology_facts(
        stable,
        target_node_ids=target_node_ids,
        replacement_by_shard=replacement_by_shard,
        logical_to_node_id=logical_to_node_id,
        expected_nodes=2,
        full_validation_passed=True,
    )

    assert stable_without_full["cluster_ok_all_slots"] is True
    assert stable_without_full["converged"] is False
    assert stable_with_full["converged"] is True


def _affected_round(*, at: float = 10.0, stable: bool = True) -> list[dict[str, Any]]:
    return [
        {
            "shard_id": "shard-0",
            "observation": {
                "monotonic": at,
                "rows": [
                    {
                        "logical_id": "replica-0",
                        "status": "OK",
                        "cluster_state": "ok",
                        "role": {"role": "primary"},
                    }
                ],
                "candidate": (
                    {"primary": "replica-0", "relationships": {"replica-0": "primary"}}
                    if stable
                    else None
                ),
            },
        }
    ]


def _failure_observation(
    *,
    at: float,
    pfail_slots: int = 0,
    fail_slots: int = 0,
    target_health: str = "online",
    non_target_health: str = "online",
) -> dict[str, Any]:
    return {
        "observer_count": 1,
        "rows": [
            {
                "logical_id": "observer-0",
                "observer_node_id": "id-primary-1",
                "monotonic": at,
                "status": "OK",
                "cluster_info": {
                    "cluster_slots_pfail": pfail_slots,
                    "cluster_slots_fail": fail_slots,
                },
                "topology": {
                    "shards": [
                        {
                            "primary_id": "id-replica-0",
                            "slots": [[0, 8191]],
                            "nodes": [
                                {"node_id": "id-primary-0", "role": "primary", "health": target_health},
                                {"node_id": "id-replica-0", "role": "primary", "health": "online"},
                            ],
                        },
                        {
                            "primary_id": "id-primary-1",
                            "slots": [[8192, 16383]],
                            "nodes": [
                                {"node_id": "id-primary-1", "role": "primary", "health": non_target_health},
                            ],
                        },
                    ]
                },
            }
        ],
    }


def _combined_fault_facts(
    failure_observation: dict[str, Any],
    *,
    affected: list[dict[str, Any]] | None = None,
    full: bool = False,
) -> dict[str, Any]:
    common = {
        "target_node_ids": {"id-primary-0"},
        "replacement_by_shard": {"shard-0": "replica-0"},
        "logical_to_node_id": {
            "primary-0": "id-primary-0",
            "replica-0": "id-replica-0",
            "primary-1": "id-primary-1",
        },
        "expected_nodes": 3,
    }
    affected_facts = capture._affected_shard_topology_facts(
        affected or _affected_round(at=float(failure_observation["rows"][0]["monotonic"])),
        **common,
        full_validation_passed=full,
    )
    return capture._fault_round_facts(
        affected_facts,
        failure_observation,
        target_node_ids={"id-primary-0"},
        target_slot_count=8192,
        replacement_node_ids={"id-replica-0"},
        expected_roles_by_node_id={
            "id-primary-0": "primary",
            "id-replica-0": "replica",
            "id-primary-1": "primary",
        },
    )


def test_fault_markers_require_raw_global_failure_observation() -> None:
    none = _combined_fault_facts(_failure_observation(at=10.0))
    pfail_only = _combined_fault_facts(_failure_observation(at=10.5, pfail_slots=8192))
    failed = _combined_fault_facts(_failure_observation(at=11.0, fail_slots=8192, target_health="fail"))

    assert none["target_pfail_observed"] is False
    assert none["first_target_pfail_at_monotonic"] == "MISSING"
    assert pfail_only["target_pfail_observed"] is True
    assert pfail_only["target_fail_node_ids"] == []
    assert pfail_only["first_target_pfail_at_monotonic"] == 10.5
    assert pfail_only["first_target_fail_at_monotonic"] == "MISSING"
    assert failed["target_fail_node_ids"] == ["id-primary-0"]
    assert failed["first_target_fail_at_monotonic"] == 11.0


def test_fault_global_observer_command_budget_is_not_per_affected_shard(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[int, tuple[str, ...]]] = []

    class Observer:
        def __init__(self, index: int) -> None:
            self.logical_id = f"observer-{index}"
            self.host = "127.0.0.1"
            self.port = 7600 + index

    class RecordingRespConnection:
        def __init__(self, endpoint: Any, *, timeout: float) -> None:
            self.endpoint = endpoint

        def __enter__(self) -> "RecordingRespConnection":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def execute_many(self, commands: list[tuple[str, ...]]) -> list[Any]:
            calls.extend((int(self.endpoint.port), tuple(command)) for command in commands)
            assert commands == [("CLUSTER", "INFO"), ("CLUSTER", "SHARDS")]
            return [
                "cluster_slots_pfail:0\r\ncluster_slots_fail:0\r\n",
                {"observer_port": int(self.endpoint.port)},
            ]

    monkeypatch.setattr(capture, "RespConnection", RecordingRespConnection)
    observers = [Observer(index) for index in range(capture.M2_PROTOCOL_OBSERVER_COUNT)]
    observation = capture._collect_fault_global_observation(
        observers,
        node_id_by_logical={observer.logical_id: f"id-{observer.logical_id}" for observer in observers},
        allowed_unhealthy_node_ids=set(),
        normalize_cluster_shards=lambda raw, **_kwargs: {"shards": [], "raw": raw},
    )

    assert observation["observer_count"] == capture.M2_PROTOCOL_OBSERVER_COUNT
    assert len(observation["rows"]) == capture.M2_PROTOCOL_OBSERVER_COUNT
    assert len(calls) == capture.M2_PROTOCOL_OBSERVER_COUNT * 2
    assert all(command in {("CLUSTER", "INFO"), ("CLUSTER", "SHARDS")} for _port, command in calls)
    assert all(command != ("CLUSTER", "COUNT-FAILURE-REPORTS") for _port, command in calls)


def test_fault_facts_detect_non_target_global_failure_observation() -> None:
    facts = _combined_fault_facts(
        _failure_observation(
            at=11.0,
            pfail_slots=16384,
            fail_slots=16384,
            target_health="fail",
            non_target_health="fail",
        )
    )

    assert facts["unexpected_pfail"] == 1
    assert facts["unexpected_fail"] == 2
    assert facts["converged"] is False


def test_exact_200_thirty_three_percent_affected_facts_cover_all_affected_shards() -> None:
    replacement_by_shard = {f"shard-{index:02d}": f"replica-{index:02d}" for index in range(33)}
    logical_to_node_id = {
        **{f"primary-{index:02d}": f"id-primary-{index:02d}" for index in range(33)},
        **{f"replica-{index:02d}": f"id-replica-{index:02d}" for index in range(33)},
    }
    target_ids = {f"id-primary-{index:02d}" for index in range(33)}
    shard_rounds = [
        {
            "shard_id": shard_id,
            "observation": {
                "monotonic": 20.0 + index * 0.001,
                "rows": [
                    {
                        "logical_id": replacement,
                        "status": "OK",
                        "cluster_state": "ok",
                        "role": {"role": "primary"},
                    }
                ],
                "candidate": {"primary": replacement, "relationships": {replacement: "primary"}},
            },
        }
        for index, (shard_id, replacement) in enumerate(replacement_by_shard.items())
    ]

    facts = capture._affected_shard_topology_facts(
        shard_rounds,
        target_node_ids=target_ids,
        replacement_by_shard=replacement_by_shard,
        logical_to_node_id=logical_to_node_id,
        expected_nodes=200,
    )

    assert facts["probe_count"] == 33
    assert facts["replacement_promotions_complete"] is True


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
                "valkey_node_id": "id-7400",
                "connection_count": 1,
                "cluster_bus_bytes": 200,
                "buffer_overflows": 0,
            }
        ],
        "cluster_link_observers": [_link_observer("node-0", "id-7400")],
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
        (7400, ("CLUSTER", "MYID")),
        (7400, ("CLUSTER", "LINKS")),
    ]


def test_m2_protocol_boundary_uses_fixed_cluster_link_observers_not_all_nodes(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[int, tuple[str, ...]]] = []
    live_ids = {f"id-{7400 + index}" for index in range(10)}

    class RecordingRespConnection:
        def __init__(self, endpoint: Any, *, timeout: float) -> None:
            self.endpoint = endpoint

        def __enter__(self) -> "RecordingRespConnection":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def execute_many(self, commands: list[tuple[str, ...]]) -> list[Any]:
            port = int(self.endpoint.port)
            calls.extend((port, tuple(command)) for command in commands)
            assert commands == [
                ("INFO", "clients"),
                ("CLUSTER", "INFO"),
                ("CLUSTER", "MYID"),
            ]
            return [
                "connected_clients:2\r\n",
                (
                    "cluster_stats_bytes_sent:10\r\n"
                    "cluster_stats_bytes_received:20\r\n"
                    "total_cluster_links_buffer_limit_exceeded:0\r\n"
                ),
                f"id-{port}",
            ]

        def execute(self, *command: str) -> list[dict[bytes, Any]]:
            port = int(self.endpoint.port)
            calls.append((port, tuple(command)))
            assert command == ("CLUSTER", "LINKS")
            observer_id = f"id-{port}"
            return [
                {
                    b"direction": direction.encode(),
                    b"node": peer_id.encode(),
                    b"create-time": 1,
                    b"events": b"rw",
                    b"send-buffer-allocated": 64,
                    b"send-buffer-used": 0,
                }
                for peer_id in sorted(live_ids)
                if peer_id != observer_id
                for direction in ("from", "to")
            ]

    monkeypatch.setattr(capture, "RespConnection", RecordingRespConnection)
    boundary = capture._collect_m2_protocol_boundary(
        _state(10),
        expected_gone_processes=None,
        expected_gone_active=False,
    )

    link_calls = [call for call in calls if call[1] == ("CLUSTER", "LINKS")]
    metric_calls = [call for call in calls if call[1] != ("CLUSTER", "LINKS")]
    assert boundary["status"] == "PASS"
    assert len(boundary["node_metrics"]) == 10
    assert len(boundary["cluster_link_observers"]) == capture.M2_PROTOCOL_OBSERVER_COUNT
    assert len(metric_calls) == 10 * 3
    assert len(link_calls) == capture.M2_PROTOCOL_OBSERVER_COUNT
    assert {port for port, _command in link_calls} == {7400, 7401, 7402}
    assert all(command != ("CLUSTER", "NODES") for _port, command in calls)


def test_m2_bootstrap_protocol_metrics_use_counter_deltas(
    monkeypatch: Any, tmp_path: Path
) -> None:
    def fake_collect(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return _protocol_boundary(
            [
                {
                    "logical_id": "node-0",
                    "valkey_node_id": "id-node-0",
                    "connection_count": 2,
                    "cluster_bus_bytes": 420,
                    "buffer_overflows": 5,
                }
            ]
        )

    monkeypatch.setattr(capture, "_collect_m2_protocol_boundary", fake_collect)
    report = _observation()

    capture._attach_m2_protocol_metrics(
        report,
        tmp_path / "resource_observation.json",
        _state(),
        start_boundary=None,
        counter_start_boundary={
            "status": "PASS",
            "expected_live_nodes": ["node-0"],
            "node_metrics": [
                {
                    "logical_id": "node-0",
                    "cluster_stats_bytes_sent": 100,
                    "cluster_stats_bytes_received": 200,
                    "total_cluster_links_buffer_limit_exceeded": 3,
                }
            ],
            "errors": [],
        },
        counter_end_boundary={
            "status": "PASS",
            "expected_live_nodes": ["node-0"],
            "node_metrics": [
                {
                    "logical_id": "node-0",
                    "cluster_stats_bytes_sent": 160,
                    "cluster_stats_bytes_received": 260,
                    "total_cluster_links_buffer_limit_exceeded": 5,
                }
            ],
            "errors": [],
        },
    )
    validated = capture._validate_resource_report(report)

    assert validated["resource_summary"]["cluster_bus_bytes"] == 120
    assert validated["resource_summary"]["buffer_overflows"] == 2


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


def test_m2_cluster_links_raw_evidence_fails_closed_when_missing_or_abnormal() -> None:
    missing = capture._m2_cluster_link_counts_from_links("MISSING")
    abnormal = capture._m2_cluster_link_counts_from_links(
        [
            {
                b"direction": b"to",
                b"node": b"id-peer",
                b"create-time": 1,
                b"events": b"",
                b"send-buffer-allocated": 1,
                b"send-buffer-used": 2,
            }
        ]
    )

    assert missing["cluster_link_errors"] == 1
    assert abnormal["cluster_link_errors"] == 1


def test_m2_setup_resource_observation_requires_start_boundary(
    monkeypatch: Any, tmp_path: Path
) -> None:
    def fake_collect(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return _protocol_boundary(
            [
                {
                    "logical_id": "node-0",
                    "valkey_node_id": "id-node-0",
                    "connection_count": 2,
                    "cluster_bus_bytes": 420,
                    "buffer_overflows": 5,
                }
            ]
        )

    monkeypatch.setattr(capture, "_collect_m2_protocol_boundary", fake_collect)
    report = _observation()
    report.pop("m2_protocol_metrics")
    report["m2_bootstrap_protocol_boundaries"] = {
        "end": {
            "status": "PASS",
            "expected_live_nodes": ["node-0"],
            "node_metrics": [
                {
                    "logical_id": "node-0",
                    "cluster_stats_bytes_sent": 160,
                    "cluster_stats_bytes_received": 260,
                    "total_cluster_links_buffer_limit_exceeded": 5,
                }
            ],
            "errors": [],
        }
    }
    path = tmp_path / "resource_observation.json"
    capture._write_json(path, report)

    try:
        capture._load_resource_observation(path, state=_state())
    except capture.CaptureError as exc:
        assert "protocol resource metrics" in str(exc)
    else:
        raise AssertionError("setup resource observation without start boundary must fail")


def test_m2_bootstrap_protocol_counter_boundary_requires_full_node_coverage(
    monkeypatch: Any, tmp_path: Path
) -> None:
    def fake_collect(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return _protocol_boundary(
            [
                {"logical_id": "node-0", "valkey_node_id": "id-node-0", "connection_count": 2, "cluster_bus_bytes": 300},
                {"logical_id": "node-1", "valkey_node_id": "id-node-1", "connection_count": 2, "cluster_bus_bytes": 300},
            ]
        )

    monkeypatch.setattr(capture, "_collect_m2_protocol_boundary", fake_collect)
    complete = {
        "status": "PASS",
        "expected_live_nodes": ["node-0", "node-1"],
        "node_metrics": [
            {
                "logical_id": "node-0",
                "cluster_stats_bytes_sent": 100,
                "cluster_stats_bytes_received": 100,
                "total_cluster_links_buffer_limit_exceeded": 0,
            },
            {
                "logical_id": "node-1",
                "cluster_stats_bytes_sent": 100,
                "cluster_stats_bytes_received": 100,
                "total_cluster_links_buffer_limit_exceeded": 0,
            },
        ],
        "errors": [],
    }
    missing_node = {
        **complete,
        "node_metrics": [complete["node_metrics"][0]],
    }

    for start_boundary, end_boundary in (
        (missing_node, complete),
        (complete, missing_node),
    ):
        report = _observation()
        capture._attach_m2_protocol_metrics(
            report,
            tmp_path / "resource_observation.json",
            _state(2),
            start_boundary=None,
            counter_start_boundary=start_boundary,
            counter_end_boundary=end_boundary,
        )
        assert report["status"] == "ERROR"


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
            {"logical_id": "node-0", "valkey_node_id": "id-node-0", "connection_count": 1, "cluster_bus_bytes": 200, "buffer_overflows": 0},
            {"logical_id": "node-1", "valkey_node_id": "id-node-1", "connection_count": 1, "cluster_bus_bytes": 200, "buffer_overflows": 0},
        ],
        "cluster_link_observers": [
            _link_observer("node-0", "id-node-0", ["id-node-1"]),
            _link_observer("node-1", "id-node-1", ["id-node-0"]),
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
        lambda *_args, **_kwargs: _protocol_boundary(
            [{"logical_id": "node-0", "valkey_node_id": "id-node-0", "connection_count": 1, "cluster_bus_bytes": 2}]
        ),
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
