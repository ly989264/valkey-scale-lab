#!/usr/bin/env python3
from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
        pong = conn.execute("PING")
        info_raw = conn.execute("INFO", "server")
        cluster_info_raw = conn.execute("CLUSTER", "INFO")
        cluster_nodes_raw = conn.execute("CLUSTER", "NODES")
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


def wait_for_cluster_ok(endpoints: list[Endpoint], min_nodes: int, timeout_seconds: float = 60.0, interval: float = 1.0) -> tuple[bool, list[dict[str, Any]]]:
    deadline = time.monotonic() + timeout_seconds
    last: list[dict[str, Any]] = []
    expected_role_counts = _expected_role_counts(endpoints)
    while time.monotonic() < deadline:
        probes = [probe_endpoint(ep) for ep in endpoints]
        last = probes
        ok = [p for p in probes if _probe_has_full_membership(p, min_nodes, expected_role_counts)]
        if len(ok) >= min_nodes:
            return True, probes
        time.sleep(interval)
    return False, last


def _expected_role_counts(endpoints: list[Endpoint]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for endpoint in endpoints:
        role = getattr(endpoint, "role", None)
        if role not in {"primary", "replica"}:
            return {}
        counts[role] = counts.get(role, 0) + 1
    return counts


def _probe_has_full_membership(probe: dict[str, Any], min_nodes: int, expected_role_counts: dict[str, int] | None = None) -> bool:
    if probe.get("status") != "PASS" or probe.get("cluster_state") != "ok":
        return False
    try:
        known_nodes = int(probe.get("cluster_known_nodes") or 0)
    except (TypeError, ValueError):
        return False
    cluster_nodes = probe.get("cluster_nodes")
    if not isinstance(cluster_nodes, dict):
        return False
    if known_nodes < min_nodes or len(cluster_nodes) < min_nodes:
        return False
    observed_role_counts: dict[str, int] = {}
    for node in cluster_nodes.values():
        flags = set(node.get("flags") or [])
        if flags.intersection({"fail", "handshake", "noaddr"}):
            return False
        if node.get("link_state") != "connected":
            return False
        role = str(node.get("role"))
        if role in {"primary", "replica"}:
            observed_role_counts[role] = observed_role_counts.get(role, 0) + 1
    if expected_role_counts:
        for role, expected in expected_role_counts.items():
            if observed_role_counts.get(role, 0) != expected:
                return False
    return True
