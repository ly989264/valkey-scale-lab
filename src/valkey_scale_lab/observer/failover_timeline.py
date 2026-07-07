from __future__ import annotations

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

REQUIRED_TIMESTAMPS = [
    "fault_apply_at_ms",
    "target_process_gone_at_ms",
    "first_pfail_seen_at_ms",
    "first_fail_seen_at_ms",
    "first_promotion_seen_at_ms",
    "first_slots_covered_at_ms",
    "first_cluster_ok_at_ms",
    "first_client_success_at_ms",
    "clean_snapshot_passed_at_ms",
]

RTO_METRIC_FIELDS = [
    "kill_to_pfail_ms",
    "pfail_to_cluster_ok_ms",
    "kill_to_client_recovered_ms",
    "cluster_ok_to_client_success_ms",
    "cluster_ok_to_clean_snapshot_ms",
    "kill_to_clean_snapshot_ms",
]


class FailoverTimelineError(ValueError):
    """Raised when P44 timeline inputs cannot support a real RTO metric."""


@dataclass(frozen=True)
class ObserverEndpoint:
    logical_id: str
    host: str
    port: int
    password: str | None = None
    az_id: str | None = None
    role: str | None = None
    container_ip: str | None = None

    @classmethod
    def from_node(cls, node: dict[str, Any]) -> "ObserverEndpoint":
        return cls(
            logical_id=str(node.get("logical_id") or node.get("id") or f"{node.get('host')}:{node.get('client_port')}"),
            host=str(node.get("host") or node.get("ip") or "127.0.0.1"),
            port=int(node.get("client_port") or node.get("port")),
            password=node.get("password"),
            az_id=node.get("az_id"),
            role=node.get("role"),
            container_ip=node.get("container_ip"),
        )


def unix_ms() -> int:
    return int(time.time() * 1000)


def monotonic_ms() -> float:
    return round(time.monotonic() * 1000, 3)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        raise FailoverTimelineError("cannot compute percentile for empty values")
    ordered = sorted(float(v) for v in values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return round(ordered[index], 3)


def _require_number(row: dict[str, Any], field: str) -> float:
    value = row.get(field)
    if isinstance(value, (int, float)):
        return float(value)
    raise FailoverTimelineError(f"{field} must be numeric for a real P44 timeline sample")


def derive_rto_metrics(row: dict[str, Any]) -> dict[str, float]:
    timestamps = {field: _require_number(row, field) for field in REQUIRED_TIMESTAMPS}
    ordered_fields = [
        "fault_apply_at_ms",
        "target_process_gone_at_ms",
        "first_pfail_seen_at_ms",
        "first_fail_seen_at_ms",
        "first_promotion_seen_at_ms",
        "first_slots_covered_at_ms",
        "first_cluster_ok_at_ms",
        "first_client_success_at_ms",
        "clean_snapshot_passed_at_ms",
    ]
    for left, right in zip(ordered_fields, ordered_fields[1:]):
        if timestamps[left] > timestamps[right]:
            raise FailoverTimelineError(f"timestamps must be monotonic: {left} > {right}")
    metrics = {
        "kill_to_pfail_ms": timestamps["first_pfail_seen_at_ms"] - timestamps["fault_apply_at_ms"],
        "pfail_to_cluster_ok_ms": timestamps["first_cluster_ok_at_ms"] - timestamps["first_pfail_seen_at_ms"],
        "kill_to_client_recovered_ms": timestamps["first_client_success_at_ms"] - timestamps["fault_apply_at_ms"],
        "cluster_ok_to_client_success_ms": timestamps["first_client_success_at_ms"] - timestamps["first_cluster_ok_at_ms"],
        "cluster_ok_to_clean_snapshot_ms": timestamps["clean_snapshot_passed_at_ms"] - timestamps["first_cluster_ok_at_ms"],
        "kill_to_clean_snapshot_ms": timestamps["clean_snapshot_passed_at_ms"] - timestamps["fault_apply_at_ms"],
    }
    for name, value in metrics.items():
        if value < 0:
            raise FailoverTimelineError(f"{name} derived to negative duration")
    if (
        metrics["pfail_to_cluster_ok_ms"] == metrics["kill_to_clean_snapshot_ms"]
        and metrics["kill_to_pfail_ms"] + metrics["cluster_ok_to_clean_snapshot_ms"] > 0
    ):
        raise FailoverTimelineError("pfail_to_cluster_ok_ms must not be substituted with kill_to_clean_snapshot_ms")
    if metrics["pfail_to_cluster_ok_ms"] > metrics["kill_to_clean_snapshot_ms"]:
        raise FailoverTimelineError("pfail_to_cluster_ok_ms cannot include clean snapshot tail")
    return {name: round(value, 3) for name, value in metrics.items()}


def build_rto_summary(
    samples: list[dict[str, Any]],
    *,
    phase_id: str,
    run_id: str,
    timeout_config_ms: int,
    server_profile: str,
    nodehost_strategy: str,
    scale: str,
) -> dict[str, Any]:
    pass_samples = [sample for sample in samples if sample.get("status") == "PASS" and sample.get("real_valkey") is True]
    derived_series: dict[str, dict[str, float | int | str]] = {}
    for metric in [
        "kill_to_pfail_ms",
        "pfail_to_cluster_ok_ms",
        "kill_to_client_recovered_ms",
        "cluster_ok_to_clean_snapshot_ms",
        "kill_to_clean_snapshot_ms",
    ]:
        values = [float(sample[metric]) for sample in pass_samples if isinstance(sample.get(metric), (int, float))]
        derived_series[metric] = {
            "sample_count": len(values),
            "p50_ms": percentile(values, 0.50) if values else "MISSING",
            "p95_ms": percentile(values, 0.95) if values else "MISSING",
            "max_ms": round(max(values), 3) if values else "MISSING",
            "percentile_method": "nearest_rank_round_index",
        }
    node_counts = sorted({int(sample["node_count"]) for sample in pass_samples if isinstance(sample.get("node_count"), int)})
    return {
        "schema_version": "v1",
        "artifact_type": "failover_rto_summary",
        "phase_id": phase_id,
        "run_id": run_id,
        "status": "PASS" if pass_samples and len(pass_samples) == len(samples) else "FAIL",
        "sample_count": len(pass_samples),
        "sample_refs": [str(sample.get("sample_id")) for sample in pass_samples],
        "timeout_config_ms": timeout_config_ms,
        "server_profile": server_profile,
        "nodehost_strategy": nodehost_strategy,
        "node_count": node_counts[-1] if node_counts else "MISSING",
        "scale": scale,
        "required_real_scales": [30, 50, 100, 200],
        "observed_real_scales": node_counts,
        "derived_series": derived_series,
    }


class RespError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _encode_command(*args: Any) -> bytes:
    parts = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        blob = arg if isinstance(arg, bytes) else str(arg).encode("utf-8")
        parts.append(f"${len(blob)}\r\n".encode())
        parts.append(blob + b"\r\n")
    return b"".join(parts)


class _RespConnection:
    def __init__(self, endpoint: ObserverEndpoint, timeout_seconds: float):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def execute(self, *args: Any) -> Any:
        with socket.create_connection((self.endpoint.host, self.endpoint.port), timeout=self.timeout_seconds) as sock:
            sock.settimeout(self.timeout_seconds)
            fp = sock.makefile("rb")
            if self.endpoint.password:
                sock.sendall(_encode_command("AUTH", self.endpoint.password))
                _read_resp(fp)
            sock.sendall(_encode_command(*args))
            return _read_resp(fp)

    def execute_pipeline(self, commands: list[tuple[Any, ...]]) -> list[Any]:
        with socket.create_connection((self.endpoint.host, self.endpoint.port), timeout=self.timeout_seconds) as sock:
            sock.settimeout(self.timeout_seconds)
            fp = sock.makefile("rb")
            if self.endpoint.password:
                sock.sendall(_encode_command("AUTH", self.endpoint.password))
                _read_resp(fp)
            sock.sendall(b"".join(_encode_command(*command) for command in commands))
            return [_read_resp(fp) for _ in commands]


def _read_line(fp: Any) -> bytes:
    line = fp.readline()
    if not line or not line.endswith(b"\r\n"):
        raise OSError("invalid RESP line")
    return line[:-2]


def _read_resp(fp: Any) -> Any:
    prefix = fp.read(1)
    if prefix == b"+":
        return _read_line(fp).decode("utf-8", errors="replace")
    if prefix == b"-":
        raise RespError(_read_line(fp).decode("utf-8", errors="replace"))
    if prefix == b":":
        return int(_read_line(fp))
    if prefix == b"$":
        n = int(_read_line(fp))
        if n == -1:
            return None
        data = fp.read(n)
        if fp.read(2) != b"\r\n":
            raise OSError("bulk string missing CRLF")
        return data.decode("utf-8", errors="replace")
    if prefix == b"*":
        n = int(_read_line(fp))
        if n == -1:
            return None
        return [_read_resp(fp) for _ in range(n)]
    raise OSError(f"unknown RESP prefix {prefix!r}")


def parse_info(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key] = value
    return out


def parse_cluster_nodes(text: str) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 8:
            continue
        flags = set(parts[2].split(","))
        role = "primary" if "master" in flags else "replica" if flags.intersection({"slave", "replica"}) else "unknown"
        nodes[parts[0]] = {
            "node_id": parts[0],
            "addr": parts[1],
            "flags": sorted(flags),
            "role": role,
            "master_id": None if parts[3] == "-" else parts[3],
            "link_state": parts[7],
            "slots": parts[8:],
        }
    return nodes


def moved_target(message: str) -> tuple[str, int] | None:
    parts = message.split()
    if len(parts) >= 3 and parts[0] in {"MOVED", "ASK"} and ":" in parts[2]:
        host, port_s = parts[2].rsplit(":", 1)
        try:
            return host, int(port_s)
        except ValueError:
            return None
    return None


class ClientRecoveryAccumulator:
    def __init__(self, sample_id: str, fault_apply_at_ms: int, probe_interval_ms: int):
        self.sample_id = sample_id
        self.fault_apply_at_ms = fault_apply_at_ms
        self.probe_interval_ms = probe_interval_ms
        self.samples: list[dict[str, Any]] = []

    def record(self, row: dict[str, Any]) -> None:
        self.samples.append(row)

    def first_success_at_or_after(self, timestamp_unix_ms: int) -> int | None:
        for row in self.samples:
            timestamp = row.get("timestamp_unix_ms")
            if row.get("status") == "PASS" and isinstance(timestamp, int) and timestamp >= timestamp_unix_ms:
                return timestamp
        return None

    def summary(self) -> dict[str, Any]:
        first_success = None
        saw_failure_after_fault = False
        errors = 0
        timeouts = 0
        moved = 0
        ask = 0
        for row in self.samples:
            timestamp = row.get("timestamp_unix_ms")
            after_fault = isinstance(timestamp, int) and timestamp >= self.fault_apply_at_ms
            if row.get("status") == "PASS" and after_fault and saw_failure_after_fault and first_success is None:
                first_success = timestamp
                break
            if after_fault:
                if row.get("status") != "PASS":
                    saw_failure_after_fault = True
                    errors += 1
                    timeouts += 1 if row.get("timeout") is True else 0
                    moved += int(row.get("moved_count", 0) or 0)
                    ask += int(row.get("ask_count", 0) or 0)
        return {
            "client_probe_interval_ms": self.probe_interval_ms,
            "first_success_after_fault_ms": first_success if first_success is not None else "MISSING",
            "error_count_before_recovery": errors,
            "timeout_count_before_recovery": timeouts,
            "moved_count": moved,
            "ask_count": ask,
            "sample_count": len(self.samples),
        }


class FailoverTimelineObserver:
    def __init__(
        self,
        *,
        phase_id: str,
        run_id: str,
        scenario_name: str,
        sample_id: str,
        node_count: int,
        endpoints: list[ObserverEndpoint],
        target_primary_logical_id: str,
        target_primary_node_id: str,
        expected_replica_node_id: str,
        probe_interval_ms: int = 250,
        timeout_seconds: float = 1.0,
        max_observer_endpoints: int = 32,
    ) -> None:
        self.phase_id = phase_id
        self.run_id = run_id
        self.scenario_name = scenario_name
        self.sample_id = sample_id
        self.node_count = node_count
        self.endpoints = endpoints
        self.target_primary_logical_id = target_primary_logical_id
        self.target_primary_node_id = target_primary_node_id
        self.expected_replica_node_id = expected_replica_node_id
        self.probe_interval_ms = probe_interval_ms
        self.timeout_seconds = timeout_seconds
        self._sample_endpoints = self._select_endpoints(max_observer_endpoints)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples: list[dict[str, Any]] = []
        self.markers: dict[str, int] = {}

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("observer already started")
        self._thread = threading.Thread(target=self._run, name=f"p44-observer-{self.sample_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.probe_interval_ms / 1000.0 * 4))

    def sample_once(self) -> dict[str, Any]:
        timestamp = unix_ms()
        probes = self._probe_endpoints()
        aggregate = _aggregate_probes(
            probes,
            self.target_primary_logical_id,
            self.target_primary_node_id,
            self.expected_replica_node_id,
        )
        row = {
            "schema_version": "v1",
            "phase_id": self.phase_id,
            "run_id": self.run_id,
            "scenario_name": self.scenario_name,
            "sample_id": self.sample_id,
            "timestamp_unix_ms": timestamp,
            "monotonic_ms": monotonic_ms(),
            "node_count": self.node_count,
            "observer_endpoint_count": len(self._sample_endpoints),
            **aggregate,
        }
        self._update_markers(row)
        self.samples.append(row)
        return row

    def _run(self) -> None:
        while not self._stop.is_set():
            self.sample_once()
            self._stop.wait(self.probe_interval_ms / 1000.0)

    def _select_endpoints(self, max_count: int) -> list[ObserverEndpoint]:
        selected: list[ObserverEndpoint] = []
        seen: set[str] = set()
        for endpoint in self.endpoints:
            if endpoint.logical_id == self.target_primary_logical_id:
                selected.append(endpoint)
                seen.add(endpoint.logical_id)
                break
        for endpoint in self.endpoints:
            if endpoint.logical_id not in seen and len(selected) < max_count:
                selected.append(endpoint)
                seen.add(endpoint.logical_id)
        return selected

    def _probe_endpoints(self) -> list[dict[str, Any]]:
        if not self._sample_endpoints:
            return []
        results: list[dict[str, Any] | None] = [None] * len(self._sample_endpoints)
        max_workers = min(16, len(self._sample_endpoints))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_probe_endpoint, endpoint, self.timeout_seconds): idx for idx, endpoint in enumerate(self._sample_endpoints)}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:  # noqa: BLE001
                    endpoint = self._sample_endpoints[idx]
                    results[idx] = {"logical_id": endpoint.logical_id, "status": "FAIL", "error": repr(exc)}
        return [item for item in results if item is not None]

    def _update_markers(self, row: dict[str, Any]) -> None:
        ts = row["timestamp_unix_ms"]
        if row.get("target_reachable") is False:
            self.markers.setdefault("target_process_gone_at_ms", ts)
        if int(row.get("pfail_count", 0) or 0) > 0:
            self.markers.setdefault("first_pfail_seen_at_ms", ts)
        if int(row.get("fail_count", 0) or 0) > 0:
            self.markers.setdefault("first_fail_seen_at_ms", ts)
        if row.get("expected_replica_promoted") is True:
            self.markers.setdefault("first_promotion_seen_at_ms", ts)
        if (
            row.get("expected_replica_promoted") is True
            and int(row.get("cluster_slots_assigned", 0) or 0) == 16384
            and int(row.get("cluster_slots_ok", 0) or 0) == 16384
        ):
            self.markers.setdefault("first_slots_covered_at_ms", ts)
        if (
            row.get("expected_replica_promoted") is True
            and int(row.get("cluster_slots_assigned", 0) or 0) == 16384
            and int(row.get("cluster_slots_ok", 0) or 0) == 16384
            and row.get("cluster_state") == "ok"
        ):
            self.markers.setdefault("first_cluster_ok_at_ms", ts)


def _probe_endpoint(endpoint: ObserverEndpoint, timeout_seconds: float) -> dict[str, Any]:
    result: dict[str, Any] = {"logical_id": endpoint.logical_id, "status": "FAIL"}
    try:
        conn = _RespConnection(endpoint, timeout_seconds)
        ping, cluster_info_raw, cluster_nodes_raw = conn.execute_pipeline([("PING",), ("CLUSTER", "INFO"), ("CLUSTER", "NODES")])
        info = parse_info(str(cluster_info_raw))
        result.update(
            {
                "status": "PASS",
                "ping": ping,
                "cluster_state": info.get("cluster_state", "unknown"),
                "cluster_slots_assigned": _as_int(info.get("cluster_slots_assigned")),
                "cluster_slots_ok": _as_int(info.get("cluster_slots_ok")),
                "cluster_known_nodes": _as_int(info.get("cluster_known_nodes")),
                "cluster_nodes": parse_cluster_nodes(str(cluster_nodes_raw)),
            }
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
    return result


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _aggregate_probes(
    probes: list[dict[str, Any]],
    target_primary_logical_id: str,
    target_primary_node_id: str,
    expected_replica_node_id: str,
) -> dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}
    pass_probes = [probe for probe in probes if probe.get("status") == "PASS"]
    pfail_count = 0
    fail_count = 0
    handshake_count = 0
    target_reachable = any(
        probe.get("logical_id") == target_primary_logical_id and probe.get("status") == "PASS"
        for probe in probes
    )
    expected_replica_promoted = False
    cluster_state = "unknown"
    slots_assigned = 0
    slots_ok = 0
    for probe in pass_probes:
        if probe.get("cluster_state") == "ok":
            cluster_state = "ok"
        slots_assigned = max(slots_assigned, int(probe.get("cluster_slots_assigned", 0) or 0))
        slots_ok = max(slots_ok, int(probe.get("cluster_slots_ok", 0) or 0))
        merged.update(probe.get("cluster_nodes") or {})
    for node_id, node in merged.items():
        flags = set(node.get("flags") or [])
        if flags.intersection({"pfail", "fail?"}):
            pfail_count += 1
        if "fail" in flags:
            fail_count += 1
        if "handshake" in flags:
            handshake_count += 1
        if node_id == expected_replica_node_id and node.get("role") == "primary":
            expected_replica_promoted = True
    return {
        "status": "PASS" if pass_probes else "FAIL",
        "probe_status_counts": {"PASS": len(pass_probes), "FAIL": len(probes) - len(pass_probes)},
        "cluster_state": cluster_state,
        "cluster_slots_assigned": slots_assigned,
        "cluster_slots_ok": slots_ok,
        "pfail_count": pfail_count,
        "fail_count": fail_count,
        "handshake_count": handshake_count,
        "target_reachable": target_reachable,
        "expected_replica_promoted": expected_replica_promoted,
        "observed_node_count": len(merged),
        "role_changes": {
            expected_replica_node_id: "primary" if expected_replica_promoted else "not_primary_observed",
        },
    }
