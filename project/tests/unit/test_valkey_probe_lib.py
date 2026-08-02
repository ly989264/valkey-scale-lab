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
    monkeypatch.setattr(valkey_probe_lib, "light_probe_endpoint", lambda endpoint: dict(probe))
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
            "cluster_slots_assigned": 16384,
            "cluster_slots_ok": 16384,
            "cluster_slots_fail": 0,
            "role": "primary",
        }
        for _ in range(101)
    ]
    timing: dict[str, object] = {}

    monkeypatch.setattr(valkey_probe_lib, "light_probe_endpoint", lambda endpoint: probes.pop(0))

    ok, observed = valkey_probe_lib.wait_for_cluster_ok([object()] * 100, min_nodes=100, timeout_seconds=1, timing=timing)

    assert ok is True
    assert len(observed) == 100
    assert timing["representative_probe"]["count"] == 1
    assert timing["all_endpoint_light_probe"]["count"] == 1
    assert "final_full_probe" not in timing


def test_wait_for_cluster_ok_success_uses_light_probe_not_cluster_nodes(monkeypatch) -> None:
    calls: list[str] = []

    def light(endpoint):
        calls.append("light")
        return {
            "status": "PASS",
            "cluster_state": "ok",
            "cluster_known_nodes": 2,
            "cluster_slots_assigned": 16384,
            "cluster_slots_ok": 16384,
            "cluster_slots_fail": 0,
            "role": endpoint.role,
            "replication_state": "connected" if endpoint.role == "replica" else "not_applicable",
        }

    def full(endpoint):
        calls.append("full")
        raise AssertionError("success path must not run CLUSTER NODES full probe")

    endpoints = [
        valkey_probe_lib.Endpoint("p0", "127.0.0.1", 7000, role="primary"),
        valkey_probe_lib.Endpoint("r0", "127.0.0.1", 7001, role="replica"),
    ]
    monkeypatch.setattr(valkey_probe_lib, "light_probe_endpoint", light)
    monkeypatch.setattr(valkey_probe_lib, "probe_endpoint", full)

    ok, observed = valkey_probe_lib.wait_for_cluster_ok(endpoints, min_nodes=2, timeout_seconds=1)

    assert ok is True
    assert len(observed) == 2
    assert "full" not in calls


def test_wait_for_cluster_ok_failure_runs_one_full_diagnostic(monkeypatch) -> None:
    full_calls: list[str] = []

    monkeypatch.setattr(
        valkey_probe_lib,
        "light_probe_endpoint",
        lambda endpoint: {"status": "PASS", "cluster_state": "fail", "cluster_known_nodes": 1},
    )

    def full(endpoint):
        full_calls.append(endpoint.logical_id)
        return {
            "status": "PASS",
            "cluster_state": "fail",
            "cluster_known_nodes": 1,
            "cluster_nodes": _cluster_nodes(1),
        }

    monkeypatch.setattr(valkey_probe_lib, "probe_endpoint", full)
    monkeypatch.setattr(valkey_probe_lib.time, "sleep", lambda _: None)

    endpoints = [valkey_probe_lib.Endpoint(f"n{idx}", "127.0.0.1", 7000 + idx) for idx in range(3)]
    ok, _observed = valkey_probe_lib.wait_for_cluster_ok(endpoints, min_nodes=3, timeout_seconds=0.01)

    assert ok is False
    assert full_calls == ["n0", "n1", "n2"]


def test_wait_for_cluster_ok_light_failure_runs_one_full_diagnostic(monkeypatch) -> None:
    full_calls: list[str] = []

    def light(endpoint):
        return {
            "status": "PASS",
            "cluster_state": "ok",
            "cluster_known_nodes": 2,
            "cluster_slots_assigned": 16384,
            "cluster_slots_ok": 16384,
            "cluster_slots_fail": 0,
            "role": "primary",
        }

    def full(endpoint):
        full_calls.append(endpoint.logical_id)
        return {
            "status": "PASS",
            "cluster_state": "ok",
            "cluster_known_nodes": 2,
            "cluster_nodes": _cluster_nodes(2),
        }

    endpoints = [
        valkey_probe_lib.Endpoint("p0", "127.0.0.1", 7000, role="primary"),
        valkey_probe_lib.Endpoint("r0", "127.0.0.1", 7001, role="replica"),
    ]
    monkeypatch.setattr(valkey_probe_lib, "light_probe_endpoint", light)
    monkeypatch.setattr(valkey_probe_lib, "probe_endpoint", full)

    ok, observed = valkey_probe_lib.wait_for_cluster_ok(endpoints, min_nodes=2, timeout_seconds=1)

    assert ok is False
    assert [probe["status"] for probe in observed] == ["PASS", "PASS"]
    assert full_calls == ["p0", "r0"]


def test_natural_probe_key_from_topology_uses_owned_primary_slot() -> None:
    bitmap = bytearray(2048)
    slot = 121
    bitmap[slot >> 3] |= 1 << (slot & 7)
    logical_id, observed_slot, key = valkey_probe_lib.natural_probe_key_from_topology(
        [{"status": "PASS", "role": "primary", "logical_id": "p0", "slot_bitmap": bytes(bitmap)}],
        prefix="probe",
    )

    assert logical_id == "p0"
    assert observed_slot == slot
    assert valkey_probe_lib.key_slot(key) == slot


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
    monkeypatch.setattr(valkey_probe_lib, "light_probe_endpoint", lambda endpoint: dict(probe))
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
