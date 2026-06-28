from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import valkey_probe_lib  # noqa: E402


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


def test_wait_for_cluster_ok_accepts_full_membership(monkeypatch) -> None:
    probes = [
        {
            "status": "PASS",
            "cluster_state": "ok",
            "cluster_known_nodes": 100,
            "cluster_nodes": _cluster_nodes(100),
        }
        for _ in range(100)
    ]

    monkeypatch.setattr(valkey_probe_lib, "probe_endpoint", lambda endpoint: probes.pop(0))

    ok, observed = valkey_probe_lib.wait_for_cluster_ok([object()] * 100, min_nodes=100, timeout_seconds=1)

    assert ok is True
    assert len(observed) == 100


def _cluster_nodes(count: int) -> dict[str, dict[str, object]]:
    return {
        f"node-{index}": {
            "flags": ["master"],
            "link_state": "connected",
        }
        for index in range(count)
    }
