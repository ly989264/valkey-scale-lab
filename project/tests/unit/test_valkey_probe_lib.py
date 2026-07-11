from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import valkey_probe_lib  # noqa: E402


def test_probe_endpoint_uses_single_pipelined_connection(monkeypatch) -> None:
    calls: list[list[tuple[object, ...]]] = []

    class FakeConnection:
        def __init__(self, host: str, port: int, password: str | None = None, timeout: float = 2.0) -> None:
            self.host = host
            self.port = port
            self.password = password
            self.timeout = timeout

        def execute_pipeline(self, commands: list[tuple[object, ...]]) -> list[object]:
            calls.append(commands)
            return [
                "PONG",
                "valkey_version:9.1.0\n",
                "cluster_state:ok\ncluster_known_nodes:1\n",
                "node-1 127.0.0.1:7000@17000 myself,master - 0 0 1 connected 0-16383\n",
            ]

    monkeypatch.setattr(valkey_probe_lib, "RespConnection", FakeConnection)

    probe = valkey_probe_lib.probe_endpoint(valkey_probe_lib.Endpoint("p0", "127.0.0.1", 7000))

    assert probe["status"] == "PASS"
    assert probe["version"] == "9.1.0"
    assert calls == [[("PING",), ("INFO", "server"), ("CLUSTER", "INFO"), ("CLUSTER", "NODES")]]


@pytest.mark.slow
def test_wait_for_cluster_ok_rejects_fragmented_membership(monkeypatch) -> None:
    probe = {
        "status": "PASS",
        "cluster_state": "ok",
        "cluster_known_nodes": 6,
        "cluster_nodes": _cluster_nodes(6),
    }

    monkeypatch.setattr(valkey_probe_lib, "probe_endpoint", lambda endpoint: dict(probe))
    monkeypatch.setattr(valkey_probe_lib.time, "sleep", lambda _: None)

    ok, observed = valkey_probe_lib.wait_for_cluster_ok([object()] * 100, min_nodes=100, timeout_seconds=0.01)

    assert ok is False
    assert len(observed) == 100


@pytest.mark.slow
def test_wait_for_cluster_ok_accepts_full_membership(monkeypatch) -> None:
    probes = [
        {
            "status": "PASS",
            "cluster_state": "ok",
            "cluster_known_nodes": 100,
            "cluster_nodes": _cluster_nodes(100),
        }
        for _ in range(101)
    ]
    timing: dict[str, object] = {}

    monkeypatch.setattr(valkey_probe_lib, "probe_endpoint", lambda endpoint: probes.pop(0))

    ok, observed = valkey_probe_lib.wait_for_cluster_ok([object()] * 100, min_nodes=100, timeout_seconds=1, timing=timing)

    assert ok is True
    assert len(observed) == 100
    assert timing["representative_probe"]["count"] == 1
    assert timing["final_full_probe"]["count"] == 1


@pytest.mark.slow
def test_wait_for_cluster_ok_rejects_master_only_when_replicas_expected(monkeypatch) -> None:
    probe = {
        "status": "PASS",
        "cluster_state": "ok",
        "cluster_known_nodes": 4,
        "cluster_nodes": _cluster_nodes(4, role="primary"),
    }
    endpoints = [
        valkey_probe_lib.Endpoint("p0", "127.0.0.1", 7000, role="primary"),
        valkey_probe_lib.Endpoint("p1", "127.0.0.1", 7001, role="primary"),
        valkey_probe_lib.Endpoint("r0", "127.0.0.1", 7002, role="replica"),
        valkey_probe_lib.Endpoint("r1", "127.0.0.1", 7003, role="replica"),
    ]

    monkeypatch.setattr(valkey_probe_lib, "probe_endpoint", lambda endpoint: dict(probe))
    monkeypatch.setattr(valkey_probe_lib.time, "sleep", lambda _: None)

    ok, observed = valkey_probe_lib.wait_for_cluster_ok(endpoints, min_nodes=4, timeout_seconds=0.01)

    assert ok is False
    assert len(observed) == 4


def _cluster_nodes(count: int, role: str = "primary") -> dict[str, dict[str, object]]:
    flags = ["master"] if role == "primary" else ["slave"]
    return {
        f"node-{index}": {
            "flags": flags,
            "link_state": "connected",
            "role": role,
        }
        for index in range(count)
    }
