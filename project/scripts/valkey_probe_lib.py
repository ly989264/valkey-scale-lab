#!/usr/bin/env python3
from __future__ import annotations

import json
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from valkey_scale_lab.observability.cluster import parse_myslots, parse_role
from valkey_scale_lab.observability.sentinel import key_slot, representative_slot, slot_tags


class RespError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class RespProtocolError(Exception):
    pass


def encode_command(*args: Any) -> bytes:
    parts = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        if isinstance(arg, bytes):
            b = arg
        else:
            b = str(arg).encode("utf-8")
        parts.append(f"${len(b)}\r\n".encode())
        parts.append(b + b"\r\n")
    return b"".join(parts)


class RespConnection:
    def __init__(self, host: str, port: int, password: str | None = None, timeout: float = 2.0):
        self.host = host
        self.port = int(port)
        self.password = password
        self.timeout = timeout

    def execute(self, *args: Any) -> Any:
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            fp = sock.makefile("rb")
            if self.password:
                sock.sendall(encode_command("AUTH", self.password))
                _ = self._read_response(fp)
            sock.sendall(encode_command(*args))
            return self._read_response(fp)

    def execute_pipeline(self, commands: list[tuple[Any, ...]]) -> list[Any]:
        if not commands:
            return []
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            fp = sock.makefile("rb")
            if self.password:
                sock.sendall(encode_command("AUTH", self.password))
                _ = self._read_response(fp)
            sock.sendall(b"".join(encode_command(*command) for command in commands))
            return [self._read_response(fp) for _ in commands]

    def _read_line(self, fp) -> bytes:
        line = fp.readline()
        if not line:
            raise RespProtocolError("connection closed while reading RESP line")
        if not line.endswith(b"\r\n"):
            raise RespProtocolError(f"RESP line missing CRLF: {line!r}")
        return line[:-2]

    def _read_response(self, fp) -> Any:
        prefix = fp.read(1)
        if not prefix:
            raise RespProtocolError("empty RESP response")
        if prefix == b"+":
            return self._read_line(fp).decode("utf-8", errors="replace")
        if prefix == b"-":
            raise RespError(self._read_line(fp).decode("utf-8", errors="replace"))
        if prefix == b":":
            return int(self._read_line(fp))
        if prefix == b"$":
            n = int(self._read_line(fp))
            if n == -1:
                return None
            data = fp.read(n)
            crlf = fp.read(2)
            if crlf != b"\r\n":
                raise RespProtocolError("bulk string missing CRLF")
            return data.decode("utf-8", errors="replace")
        if prefix == b"*":
            n = int(self._read_line(fp))
            if n == -1:
                return None
            return [self._read_response(fp) for _ in range(n)]
        raise RespProtocolError(f"unknown RESP prefix {prefix!r}")


@dataclass
class Endpoint:
    logical_id: str
    host: str
    port: int
    password: str | None = None
    az_id: str | None = None
    role: str | None = None
    container_ip: str | None = None

    @classmethod
    def from_node(cls, node: dict[str, Any]) -> "Endpoint":
        return cls(
            logical_id=str(node.get("logical_id") or node.get("id") or f"{node.get('host')}:{node.get('client_port')}"),
            host=str(node.get("host") or node.get("ip") or "127.0.0.1"),
            port=int(node.get("client_port") or node.get("port")),
            password=node.get("password"),
            az_id=node.get("az_id"),
            role=node.get("role"),
            container_ip=node.get("container_ip"),
        )


def parse_info(info: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in info.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k] = v
    return out


def parse_cluster_info(text: str) -> dict[str, str]:
    return parse_info(text)


def parse_cluster_nodes(text: str) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 8:
            continue
        node_id, addr, flags, master_id = parts[0], parts[1], parts[2], parts[3]
        flag_set = set(flags.split(","))
        role = "primary" if "master" in flag_set else "replica" if ("slave" in flag_set or "replica" in flag_set) else "unknown"
        nodes[node_id] = {
            "node_id": node_id,
            "addr": addr,
            "flags": sorted(flag_set),
            "role": role,
            "master_id": None if master_id == "-" else master_id,
            "link_state": parts[7] if len(parts) > 7 else "unknown",
            "slots": parts[8:],
        }
    return nodes


def probe_endpoint(endpoint: Endpoint, timeout: float = 2.0) -> dict[str, Any]:
    result: dict[str, Any] = {
        "logical_id": endpoint.logical_id,
        "host": endpoint.host,
        "port": endpoint.port,
        "status": "FAIL",
    }
    try:
        conn = RespConnection(endpoint.host, endpoint.port, endpoint.password, timeout=timeout)
        pong, info_raw, cluster_info_raw, cluster_nodes_raw = conn.execute_pipeline(
            [
                ("PING",),
                ("INFO", "server"),
                ("CLUSTER", "INFO"),
                ("CLUSTER", "NODES"),
            ]
        )
        info = parse_info(str(info_raw))
        cinfo = parse_cluster_info(str(cluster_info_raw))
        cnodes = parse_cluster_nodes(str(cluster_nodes_raw))
        version = info.get("valkey_version") or info.get("redis_version") or "unknown"
        myself = None
        for nid, node in cnodes.items():
            if "myself" in node.get("flags", []):
                myself = nid
                break
        result.update({
            "status": "PASS",
            "ping": pong,
            "version": version,
            "cluster_state": cinfo.get("cluster_state", "unknown"),
            "cluster_known_nodes": int(cinfo.get("cluster_known_nodes", "0") or 0),
            "myself_node_id": myself,
            "cluster_nodes": cnodes,
        })
    except Exception as exc:  # noqa: BLE001 - gate evidence should include exact probe failure
        result["error"] = repr(exc)
    return result


def light_probe_endpoint(endpoint: Endpoint, timeout: float = 2.0) -> dict[str, Any]:
    result: dict[str, Any] = {
        "logical_id": endpoint.logical_id,
        "host": endpoint.host,
        "port": endpoint.port,
        "status": "FAIL",
    }
    try:
        conn = RespConnection(endpoint.host, endpoint.port, endpoint.password, timeout=timeout)
        pong, info_raw, cluster_info_raw, role_raw, node_id_raw, shard_id_raw, myslots_raw = conn.execute_pipeline(
                [
                    ("PING",),
                    ("INFO", "server"),
                    ("CLUSTER", "INFO"),
                    ("ROLE",),
                    ("CLUSTER", "MYID"),
                    ("CLUSTER", "MYSHARDID"),
                    ("CLUSTER", "MYSLOTS"),
                ]
            )
        info = parse_info(_text(info_raw))
        cinfo = parse_cluster_info(_text(cluster_info_raw))
        role = parse_role(role_raw)
        myslots = parse_myslots(myslots_raw)
        node_id = _text(node_id_raw)
        shard_id = _text(shard_id_raw)
        if pong not in {b"PONG", "PONG"}:
            raise RespProtocolError(f"PING returned {pong!r}")
        if node_id != myslots.node_id or shard_id != myslots.shard_id:
            raise RespProtocolError("CLUSTER MYID/MYSHARDID disagree with CLUSTER MYSLOTS")
        if role["role"] != myslots.role:
            raise RespProtocolError("ROLE disagrees with CLUSTER MYSLOTS")
        version = info.get("valkey_version") or info.get("redis_version") or "unknown"
        result.update({
            "status": "PASS",
            "ping": _text(pong),
            "version": version,
            "cluster_state": cinfo.get("cluster_state", "unknown"),
            "cluster_known_nodes": int(cinfo.get("cluster_known_nodes", "0") or 0),
            "cluster_slots_assigned": int(cinfo.get("cluster_slots_assigned", "0") or 0),
            "cluster_slots_ok": int(cinfo.get("cluster_slots_ok", "0") or 0),
            "cluster_slots_fail": int(cinfo.get("cluster_slots_fail", "0") or 0),
            "myself_node_id": node_id,
            "shard_id": shard_id,
            "role": role["role"],
            "replication_state": role.get("replication_state", "not_applicable"),
            "slot_owner_id": myslots.slot_owner_id,
            "slot_count": myslots.slot_count,
            "slot_bitmap": myslots.bitmap,
        })
    except Exception as exc:  # noqa: BLE001 - gate evidence should include exact probe failure
        result["error"] = repr(exc)
    return result


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def natural_probe_key_from_topology(probes: list[dict[str, Any]], *, prefix: str) -> tuple[str, int, str]:
    for probe in probes:
        if probe.get("status") != "PASS" or probe.get("role") != "primary":
            continue
        bitmap = probe.get("slot_bitmap")
        if not isinstance(bitmap, bytes):
            continue
        slot = representative_slot(bitmap)
        tag = slot_tags([slot])[slot]
        key = f"{{{tag}}}:{prefix}"
        if key_slot(key) == slot and (bitmap[slot >> 3] & (1 << (slot & 7))):
            return str(probe["logical_id"]), slot, key
    raise RuntimeError("no primary light probe exposed a natural owned slot for data path")


def moved_target(message: str) -> tuple[str, int] | None:
    # MOVED 12182 127.0.0.1:7002 or ASK 12182 127.0.0.1:7002
    parts = message.split()
    if len(parts) >= 3 and parts[0] in {"MOVED", "ASK"} and ":" in parts[2]:
        host, port_s = parts[2].rsplit(":", 1)
        try:
            return host, int(port_s)
        except ValueError:
            return None
    return None


def execute_cluster_command(endpoints: list[Endpoint], *args: Any, timeout: float = 2.0, max_redirects: int = 8) -> Any:
    if not endpoints:
        raise RuntimeError("no endpoints")
    ep = endpoints[0]
    for _ in range(max_redirects + 1):
        try:
            return RespConnection(ep.host, ep.port, ep.password, timeout=timeout).execute(*args)
        except RespError as exc:
            target = moved_target(exc.message)
            if not target:
                raise
            host, port = target
            ep = _redirect_endpoint(endpoints, host, port, ep.password)
            if exc.message.startswith("ASK"):
                RespConnection(ep.host, ep.port, ep.password, timeout=timeout).execute("ASKING")
    raise RuntimeError("too many cluster redirects")


def _redirect_endpoint(endpoints: list[Endpoint], host: str, port: int, password: str | None) -> Endpoint:
    for endpoint in endpoints:
        if endpoint.host == host and endpoint.port == port:
            return endpoint
        if endpoint.container_ip == host and endpoint.port == port:
            return endpoint
        if endpoint.container_ip == host and port == 6379:
            return endpoint
    return Endpoint(logical_id=f"redirect-{host}:{port}", host=host, port=port, password=password)


def load_state(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        state = json.load(f)
    if not isinstance(state.get("nodes"), list) or not state["nodes"]:
        raise ValueError("state file must contain non-empty nodes array")
    return state


def endpoints_from_state(state: dict[str, Any]) -> list[Endpoint]:
    return [Endpoint.from_node(n) for n in state.get("nodes", [])]


def wait_for_cluster_ok(
    endpoints: list[Endpoint],
    min_nodes: int,
    timeout_seconds: float = 60.0,
    interval: float = 1.0,
    timing: dict[str, Any] | None = None,
    diagnostic_rounds: list[dict[str, Any]] | None = None,
    round_context: dict[str, Any] | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    deadline = time.monotonic() + timeout_seconds
    last: list[dict[str, Any]] = []
    last_failure_reason = "representative_timeout"
    expected_role_counts = _expected_role_counts(endpoints, min_nodes)
    representatives = _representative_endpoints(endpoints)
    while time.monotonic() < deadline:
        rep_started = time.monotonic()
        rep_started_unix_ms = int(time.time() * 1000)
        probes = _probe_endpoints_concurrent(representatives, probe=light_probe_endpoint)
        rep_ended_unix_ms = int(time.time() * 1000)
        _record_wait_timing(
            timing,
            "representative_probe",
            rep_started,
            {"endpoint_count": len(representatives), "sample_scope": "representative"},
        )
        _append_clean_gate_round(
            diagnostic_rounds,
            round_context,
            probes,
            min_nodes,
            expected_role_counts,
            rep_started_unix_ms,
            rep_ended_unix_ms,
            "representative",
            "PASS" if _representative_probes_clean(probes, min_nodes) else "FAIL",
        )
        last = probes
        if _representative_probes_clean(probes, min_nodes):
            light_started = time.monotonic()
            light_started_unix_ms = int(time.time() * 1000)
            light_probes = _probe_endpoints_concurrent(endpoints, probe=light_probe_endpoint)
            light_ended_unix_ms = int(time.time() * 1000)
            _record_wait_timing(
                timing,
                "all_endpoint_light_probe",
                light_started,
                {"endpoint_count": len(endpoints), "sample_scope": "all_nodes_light"},
            )
            last = light_probes
            if _all_light_probes_clean(light_probes, min_nodes, expected_role_counts):
                _append_clean_gate_round(
                    diagnostic_rounds,
                    round_context,
                    light_probes,
                    min_nodes,
                    expected_role_counts,
                    light_started_unix_ms,
                    light_ended_unix_ms,
                    "all_nodes_light",
                    "PASS",
                )
                return True, light_probes
            _append_clean_gate_round(
                diagnostic_rounds,
                round_context,
                light_probes,
                min_nodes,
                expected_role_counts,
                light_started_unix_ms,
                light_ended_unix_ms,
                "all_nodes_light",
                "FAIL",
                failed_reason="all_endpoint_light_probe_failed",
            )
            last_failure_reason = "all_endpoint_light_probe_timeout"
        else:
            last_failure_reason = "representative_timeout"
        time.sleep(interval)
    diagnostic_started = time.monotonic()
    diagnostic_started_unix_ms = int(time.time() * 1000)
    diagnostic = _probe_endpoints_concurrent(endpoints, probe=probe_endpoint)
    diagnostic_ended_unix_ms = int(time.time() * 1000)
    _append_clean_gate_round(
        diagnostic_rounds,
        round_context,
        diagnostic,
        min_nodes,
        expected_role_counts,
        diagnostic_started_unix_ms,
        diagnostic_ended_unix_ms,
        "all_nodes",
        "FAIL",
        failed_reason=last_failure_reason,
        timed_out=True,
    )
    _record_wait_timing(
        timing,
        "diagnostic_full_probe",
        diagnostic_started,
        {"endpoint_count": len(endpoints), "sample_scope": "all_nodes", "reason": last_failure_reason},
    )
    return False, diagnostic or last


def _append_clean_gate_round(
    rows: list[dict[str, Any]] | None,
    context: dict[str, Any] | None,
    probes: list[dict[str, Any]],
    min_nodes: int,
    expected_role_counts: dict[str, int] | None,
    start_ms: int,
    end_ms: int,
    sample_scope: str,
    status: str,
    *,
    failed_reason: str | None = None,
    timed_out: bool = False,
) -> None:
    if rows is None:
        return
    reason = failed_reason or _probe_failure_reason(probes, min_nodes, expected_role_counts)
    slowest_node, slowest_ms = _slowest_probe(probes, end_ms - start_ms)
    base = {
        "schema_version": "v1",
        "artifact_type": "clean_gate_probe_round",
        "probe_start_ms": start_ms,
        "probe_end_ms": end_ms,
        "probe_duration_ms": max(0, end_ms - start_ms),
        "sample_scope": sample_scope,
        "sample_count": len(probes),
        "status": status,
        "failed_reason": "" if status == "PASS" else reason,
        "slowest_node": slowest_node,
        "slowest_probe_ms": slowest_ms,
        "timed_out": timed_out,
        "probe_status_counts": {
            "PASS": sum(1 for probe in probes if probe.get("status") == "PASS"),
            "FAIL": sum(1 for probe in probes if probe.get("status") != "PASS"),
        },
        "all_slots_covered": any(
            int(probe.get("cluster_slots_assigned", 0) or 0) == 16384
            and int(probe.get("cluster_slots_ok", 0) or 0) == 16384
            for probe in probes
        ),
        "all_nodes_clean": status == "PASS" and sample_scope.startswith("all_nodes"),
    }
    if context:
        base.update(context)
    rows.append(base)


def _probe_failure_reason(
    probes: list[dict[str, Any]],
    min_nodes: int,
    expected_role_counts: dict[str, int] | None,
) -> str:
    if not probes:
        return "no_probes"
    failing = [probe for probe in probes if not _probe_has_full_membership(probe, min_nodes, expected_role_counts)]
    if not failing:
        return ""
    probe = failing[0]
    if probe.get("status") != "PASS":
        return str(probe.get("error") or "probe_failed")[:200]
    if probe.get("cluster_state") != "ok":
        return f"cluster_state={probe.get('cluster_state')}"
    return "membership_not_clean"


def _slowest_probe(probes: list[dict[str, Any]], fallback_ms: int) -> tuple[str, int]:
    if not probes:
        return "MISSING", max(0, fallback_ms)
    return str(probes[-1].get("logical_id", "MISSING")), max(0, fallback_ms)


def _probe_endpoints_concurrent(endpoints: list[Endpoint], *, probe: Any = probe_endpoint) -> list[dict[str, Any]]:
    if not endpoints:
        return []
    max_workers = max(1, min(16, len(endpoints)))
    results: list[dict[str, Any] | None] = [None] * len(endpoints)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(probe, endpoint): (idx, endpoint) for idx, endpoint in enumerate(endpoints)}
        for future in as_completed(futures):
            idx, endpoint = futures[future]
            try:
                results[idx] = future.result()
            except Exception as exc:  # noqa: BLE001 - diagnostics must retain endpoint failures
                results[idx] = _failed_probe(endpoint, exc)
    return [item for item in results if item is not None]


def _failed_probe(endpoint: Any, exc: Exception) -> dict[str, Any]:
    return {
        "logical_id": str(getattr(endpoint, "logical_id", repr(endpoint))),
        "host": str(getattr(endpoint, "host", "MISSING")),
        "port": int(getattr(endpoint, "port", 0) or 0),
        "status": "FAIL",
        "error": repr(exc),
    }


def _representative_endpoints(endpoints: list[Endpoint]) -> list[Endpoint]:
    if len(endpoints) <= 8:
        return list(endpoints)
    representatives: list[Endpoint] = [endpoints[0]]
    first_id = str(getattr(endpoints[0], "logical_id", id(endpoints[0])))
    seen: set[str] = {first_id}
    per_key: set[tuple[str, str]] = set()
    for endpoint in endpoints:
        key = (str(getattr(endpoint, "az_id", None) or "MISSING"), str(getattr(endpoint, "role", None) or "MISSING"))
        if key in per_key:
            continue
        per_key.add(key)
        logical_id = str(getattr(endpoint, "logical_id", id(endpoint)))
        if logical_id not in seen:
            representatives.append(endpoint)
            seen.add(logical_id)
    return representatives


def _record_wait_timing(
    timing: dict[str, Any] | None,
    name: str,
    started: float,
    details: dict[str, Any],
    *,
    duration_override: float | None = None,
) -> None:
    if timing is None:
        return
    duration = duration_override if duration_override is not None else max(time.monotonic() - started, 0.0)
    entry = timing.setdefault(
        name,
        {
            "name": name,
            "status": "PASS",
            "duration_seconds": 0.0,
            "count": 0,
            "details": {},
        },
    )
    entry["duration_seconds"] = round(float(entry.get("duration_seconds", 0.0)) + duration, 6)
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["details"].update(details)


def _expected_role_counts(endpoints: list[Endpoint], min_nodes: int) -> dict[str, int]:
    if min_nodes < len(endpoints):
        return {}
    counts: dict[str, int] = {}
    for endpoint in endpoints:
        role = getattr(endpoint, "role", None)
        if role not in {"primary", "replica"}:
            return {}
        counts[role] = counts.get(role, 0) + 1
    return counts


def _representative_probes_clean(probes: list[dict[str, Any]], min_nodes: int) -> bool:
    required = min(min_nodes, len(probes))
    healthy = sum(
        probe.get("status") == "PASS"
        and probe.get("cluster_state") == "ok"
        and int(probe.get("cluster_known_nodes", 0) or 0) >= min_nodes
        and int(probe.get("cluster_slots_assigned", 0) or 0) == 16384
        and int(probe.get("cluster_slots_ok", 0) or 0) == 16384
        and int(probe.get("cluster_slots_fail", 0) or 0) == 0
        for probe in probes
    )
    return required > 0 and healthy >= required


def _all_light_probes_clean(
    probes: list[dict[str, Any]],
    min_nodes: int,
    expected_role_counts: dict[str, int] | None = None,
) -> bool:
    if len(probes) < min_nodes or not _representative_probes_clean(probes, min_nodes):
        return False
    if expected_role_counts:
        observed: dict[str, int] = {}
        for probe in probes:
            role = str(probe.get("role", ""))
            if role in {"primary", "replica"}:
                observed[role] = observed.get(role, 0) + 1
            if role == "replica" and probe.get("replication_state") != "connected":
                return False
        for role, expected in expected_role_counts.items():
            if observed.get(role, 0) != expected:
                return False
    primary_bitmaps = [
        probe.get("slot_bitmap")
        for probe in probes
        if probe.get("role") == "primary" and isinstance(probe.get("slot_bitmap"), bytes)
    ]
    if primary_bitmaps:
        union = bytearray(2048)
        for bitmap in primary_bitmaps:
            for index, byte in enumerate(bitmap):
                if union[index] & byte:
                    return False
                union[index] |= byte
        if bytes(union) != bytes([0xFF]) * 2048:
            return False
    return True


def _all_probes_have_full_membership(
    probes: list[dict[str, Any]],
    min_nodes: int,
    expected_role_counts: dict[str, int] | None = None,
) -> bool:
    return bool(probes) and all(_probe_has_full_membership(probe, min_nodes, expected_role_counts) for probe in probes)


def _enough_probes_have_full_membership(
    probes: list[dict[str, Any]],
    min_nodes: int,
    expected_role_counts: dict[str, int] | None = None,
) -> bool:
    ok = [probe for probe in probes if _probe_has_full_membership(probe, min_nodes, expected_role_counts)]
    return len(ok) >= min_nodes


def _probe_has_full_membership(probe: dict[str, Any], min_nodes: int, expected_role_counts: dict[str, int] | None = None) -> bool:
    if probe.get("status") != "PASS" or probe.get("cluster_state") != "ok":
        return False
    try:
        known_nodes = int(probe.get("cluster_known_nodes") or 0)
    except (TypeError, ValueError):
        return False
    if "cluster_nodes" not in probe:
        return (
            known_nodes >= min_nodes
            and int(probe.get("cluster_slots_assigned", 0) or 0) == 16384
            and int(probe.get("cluster_slots_ok", 0) or 0) == 16384
            and int(probe.get("cluster_slots_fail", 0) or 0) == 0
        )
    cluster_nodes = probe.get("cluster_nodes")
    if not isinstance(cluster_nodes, dict):
        return False
    if known_nodes < min_nodes or len(cluster_nodes) < min_nodes:
        return False
    observed_role_counts: dict[str, int] = {}
    healthy_nodes = 0
    strict = bool(expected_role_counts)
    for node in cluster_nodes.values():
        flags = set(node.get("flags") or [])
        if flags.intersection({"fail", "handshake", "noaddr"}):
            if strict:
                return False
            continue
        if node.get("link_state") != "connected":
            if strict:
                return False
            continue
        healthy_nodes += 1
        role = str(node.get("role"))
        if role in {"primary", "replica"}:
            observed_role_counts[role] = observed_role_counts.get(role, 0) + 1
    if healthy_nodes < min_nodes:
        return False
    if expected_role_counts:
        for role, expected in expected_role_counts.items():
            if observed_role_counts.get(role, 0) != expected:
                return False
    return True
