from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_gate():
    path = Path("scripts/fault_failover_gate.py")
    spec = importlib.util.spec_from_file_location("fault_failover_gate_partition_gap", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_minority_and_majority_partitions_inject_distinct_group_faults(monkeypatch) -> None:
    gate = _load_gate()
    constructed: list[tuple[str, int, str]] = []

    class FakeProxy:
        def __init__(self, *, target_host: str, target_port: int, rule) -> None:
            constructed.append((target_host, target_port, rule.fault_type))
            self.listen_host = "127.0.0.1"
            self.listen_port = 29999

        def start(self) -> None:
            pass

        def close(self) -> None:
            pass

        def snapshot(self) -> dict[str, int]:
            return {"accepted_connections": 1}

    endpoints = [
        SimpleNamespace(
            logical_id=f"node-{index}",
            host="127.0.0.1",
            port=17000 + index,
            password=None,
            az_id="az-a" if index < 3 else "az-b",
            role="primary",
            container_ip=f"172.18.0.{index + 2}",
        )
        for index in range(6)
    ]
    monkeypatch.setattr(gate, "SandboxNetworkProxy", FakeProxy)
    monkeypatch.setattr(gate, "workload_target_for_logical", lambda *_args: None)
    monkeypatch.setattr(gate, "workload_window", lambda *_args: {"status": "MEASURED"})

    profile = SimpleNamespace(label_lower="fault_matrix_exact_50")
    for row_name in ("minority_partition", "majority_partition"):
        gate.fault_matrix_proxy_window(row_name, endpoints, [], "node-0", "run", profile)

    assert constructed[0] != constructed[1], (
        "minority_partition and majority_partition must isolate distinct Valkey node groups; "
        "both currently apply the same client-side proxy rule to the same single endpoint"
    )
