from __future__ import annotations

import base64
import binascii
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from valkey_scale_lab.observability.cluster import NodeEndpoint
from valkey_scale_lab.observability.contracts import CollectionError, SemanticFailure
from valkey_scale_lab.valkey.resp import (
    Endpoint,
    RespCommandError,
    RespConnection,
)


def key_slot(key: str) -> int:
    left = key.find("{")
    if left >= 0:
        right = key.find("}", left + 1)
        if right > left + 1:
            key = key[left + 1 : right]
    return binascii.crc_hqx(key.encode("utf-8"), 0) % 16384


def representative_slot(bitmap: bytes) -> int:
    if len(bitmap) != 2048:
        raise ValueError("slot bitmap must be 2048 bytes")
    for byte_index, byte in enumerate(bitmap):
        if byte:
            for bit in range(8):
                if byte & (1 << bit):
                    return byte_index * 8 + bit
    raise ValueError("slot bitmap contains no slot")


def slot_tags(slots: Sequence[int]) -> dict[int, str]:
    wanted = set(slots)
    if len(wanted) != len(slots):
        raise ValueError("representative slots must be unique")
    found: dict[int, str] = {}
    candidate = 0
    while len(found) < len(wanted):
        tag = f"s{candidate}"
        slot = key_slot(f"{{{tag}}}")
        if slot in wanted and slot not in found:
            found[slot] = tag
        candidate += 1
    return found


@dataclass(frozen=True)
class Canary:
    shard_id: str
    slot: int
    key: str
    value: str


@dataclass(frozen=True)
class SentinelNode:
    endpoint: NodeEndpoint
    node_id: str
    shard_id: str
    role: str
    canary: Canary


def build_sentinel_nodes(
    light_report: Mapping[str, Any],
    inventory: Sequence[NodeEndpoint],
    *,
    run_scope: str,
) -> list[SentinelNode]:
    inventory_by_logical = {node.logical_id: node for node in inventory}
    rows = list(light_report.get("nodes", []))
    primary_rows = [
        row for row in rows if row.get("myslots", {}).get("role") == "primary"
    ]
    shard_slots: dict[str, int] = {}
    for row in primary_rows:
        fields = row["myslots"]
        bitmap = base64.b64decode(fields["slot-bitmap-base64"], validate=True)
        shard_slots[str(fields["shard-id"])] = representative_slot(bitmap)
    tags = slot_tags(list(shard_slots.values()))
    canaries = {
        shard_id: Canary(
            shard_id=shard_id,
            slot=slot,
            key=f"vsl:sentinel:{run_scope}:{{{tags[slot]}}}:{shard_id}",
            value=f"vsl-sentinel-value:{run_scope}:{shard_id}",
        )
        for shard_id, slot in shard_slots.items()
    }
    result: list[SentinelNode] = []
    for row in rows:
        logical_id = str(row["logical_id"])
        if logical_id not in inventory_by_logical:
            raise SemanticFailure(f"Sentinel inventory lacks {logical_id}")
        fields = row["myslots"]
        shard_id = str(fields["shard-id"])
        result.append(
            SentinelNode(
                endpoint=inventory_by_logical[logical_id],
                node_id=str(fields["node-id"]),
                shard_id=shard_id,
                role=str(fields["role"]),
                canary=canaries[shard_id],
            )
        )
    return result


class _DirectCanaryClient:
    def __init__(
        self,
        node: SentinelNode,
        *,
        timeout: float,
        connection_factory: Callable[[Endpoint, float], RespConnection],
    ) -> None:
        self.node = node
        self.timeout = timeout
        self._factory = connection_factory
        self._connection: RespConnection | None = None
        self._paused = False
        self.events: list[dict[str, Any]] = []

    def mark_expected_down(self) -> None:
        self._paused = True
        self._disconnect("actuator_expected_down")

    def mark_restore_started(self) -> None:
        self._paused = False

    def close(self) -> None:
        self._disconnect("lane_closed")

    def _disconnect(self, reason: str) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
            self.events.append(
                {
                    "event": "disconnect",
                    "logical_id": self.node.endpoint.logical_id,
                    "reason": reason,
                    "wall_time": time.time(),
                    "monotonic": time.monotonic(),
                }
            )

    def _connect(self) -> RespConnection:
        if self._paused:
            raise SemanticFailure(
                f"{self.node.endpoint.logical_id} reconnect is paused by actuator"
            )
        connection = self._factory(
            Endpoint(self.node.endpoint.host, self.node.endpoint.port), self.timeout
        )
        try:
            connection.connect()
            node_id, role_raw = connection.execute_many(
                [("CLUSTER", "MYID"), ("ROLE",)]
            )
            actual_id = (
                node_id.decode("ascii") if isinstance(node_id, bytes) else str(node_id)
            )
            raw_role = role_raw[0] if isinstance(role_raw, list) and role_raw else b""
            role_text = (
                raw_role.decode("ascii")
                if isinstance(raw_role, bytes)
                else str(raw_role)
            ).lower()
            actual_role = (
                "primary" if role_text in {"master", "primary"} else "replica"
            )
            if actual_id != self.node.node_id:
                raise SemanticFailure(
                    f"{self.node.endpoint.logical_id} reconnected to unexpected node"
                )
            if actual_role == "replica":
                connection.execute("READONLY")
        except Exception:
            connection.close()
            raise
        self._connection = connection
        self.events.append(
            {
                "event": "connected",
                "logical_id": self.node.endpoint.logical_id,
                "role": actual_role,
                "wall_time": time.time(),
                "monotonic": time.monotonic(),
            }
        )
        return connection

    def execute(self, *command: Any) -> Any:
        last_error: Exception | None = None
        for attempt in (1, 2):
            try:
                connection = self._connection or self._connect()
                return connection.execute(*command)
            except SemanticFailure:
                raise
            except Exception as exc:
                last_error = exc
                self._disconnect(f"command_attempt_{attempt}_failed")
        assert last_error is not None
        raise SemanticFailure(
            f"{self.node.endpoint.logical_id} command failed after reconnect: "
            f"{last_error}"
        ) from last_error


class ClusterRouter:
    """Persistent small client that follows MOVED/ASK for Sentinel GETs."""

    def __init__(
        self,
        seeds: Sequence[Endpoint],
        *,
        timeout: float = 1.0,
        connection_factory: Callable[[Endpoint, float], RespConnection] | None = None,
    ) -> None:
        if not seeds:
            raise ValueError("cluster router requires a seed")
        self.seeds = list(seeds)
        self.timeout = timeout
        self._factory = connection_factory or (
            lambda endpoint, timeout: RespConnection(endpoint, timeout=timeout)
        )
        self._connections: dict[Endpoint, RespConnection] = {}
        self._slot_routes: dict[int, Endpoint] = {}

    def close(self) -> None:
        for connection in self._connections.values():
            connection.close()
        self._connections.clear()

    def _connection(self, endpoint: Endpoint) -> RespConnection:
        connection = self._connections.get(endpoint)
        if connection is None:
            connection = self._factory(endpoint, self.timeout)
            self._connections[endpoint] = connection
        return connection

    @staticmethod
    def _redirect(error: RespCommandError) -> tuple[str, int, Endpoint] | None:
        parts = str(error).split()
        if len(parts) < 3 or parts[0] not in {"MOVED", "ASK"}:
            return None
        host, separator, port = parts[2].rpartition(":")
        if not separator:
            return None
        return parts[0], int(parts[1]), Endpoint(host, int(port))

    def get(self, key: str) -> Any:
        slot = key_slot(key)
        route = self._slot_routes.get(slot)
        candidates = ([route] if route is not None else []) + [
            seed for seed in self.seeds if seed != route
        ]
        last_connection_error: Exception | None = None
        for candidate in candidates:
            endpoint = candidate
            for _ in range(3):
                try:
                    return self._connection(endpoint).execute("GET", key)
                except RespCommandError as exc:
                    redirect = self._redirect(exc)
                    if redirect is None:
                        raise
                    kind, redirected_slot, endpoint = redirect
                    if kind == "MOVED":
                        self._slot_routes[redirected_slot] = endpoint
                    else:
                        self._connection(endpoint).execute("ASKING")
                except (OSError, EOFError, TimeoutError) as exc:
                    last_connection_error = exc
                    break
            else:
                raise SemanticFailure(
                    f"too many redirections for Sentinel key slot {slot}"
                )
        raise SemanticFailure(
            f"all Sentinel seeds failed for key slot {slot}: "
            f"{last_connection_error}"
        ) from last_connection_error


class SentinelLane:
    def __init__(
        self,
        nodes: Sequence[SentinelNode],
        *,
        timeout: float = 1.0,
        connection_factory: Callable[[Endpoint, float], RespConnection] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not nodes:
            raise ValueError("Sentinel Lane requires nodes")
        self.nodes = list(nodes)
        self.timeout = timeout
        self._factory = connection_factory or (
            lambda endpoint, timeout: RespConnection(endpoint, timeout=timeout)
        )
        self._clients = {
            node.endpoint.logical_id: _DirectCanaryClient(
                node,
                timeout=timeout,
                connection_factory=self._factory,
            )
            for node in nodes
        }
        self._sleep = sleep
        self._monotonic = monotonic
        self.events: list[dict[str, Any]] = []

    def close(self) -> None:
        for client in self._clients.values():
            client.close()

    def mark_expected_down(self, logical_id: str) -> None:
        self._clients[logical_id].mark_expected_down()

    def mark_restore_started(self, logical_id: str) -> None:
        self._clients[logical_id].mark_restore_started()

    def prepare(self, *, replica_timeout: float = 30.0) -> dict[str, Any]:
        primaries = [node for node in self.nodes if node.role == "primary"]
        for node in primaries:
            result = self._clients[node.endpoint.logical_id].execute(
                "SET", node.canary.key, node.canary.value
            )
            if result not in {"OK", b"OK"}:
                raise SemanticFailure(
                    f"{node.endpoint.logical_id} Sentinel SET returned {result!r}"
                )
        deadline = self._monotonic() + replica_timeout
        pending = {
            node.endpoint.logical_id
            for node in self.nodes
            if node.role == "replica"
        }
        while pending and self._monotonic() < deadline:
            for logical_id in list(pending):
                node = self._clients[logical_id].node
                try:
                    value = self._clients[logical_id].execute("GET", node.canary.key)
                except SemanticFailure:
                    continue
                if _value_text(value) == node.canary.value:
                    pending.remove(logical_id)
            if pending:
                self._sleep(min(0.1, max(deadline - self._monotonic(), 0.0)))
        if pending:
            raise SemanticFailure(
                f"Sentinel canary did not reach replicas: {sorted(pending)}"
            )
        return {
            "status": "OK",
            "canary_count": len(primaries),
            "node_count": len(self.nodes),
            "replicas_confirmed": len(self.nodes) - len(primaries),
            "writes_during_formal_window": 0,
        }

    def rolling_sweep(self, *, duration_seconds: float = 60.0) -> dict[str, Any]:
        interval = duration_seconds / len(self.nodes)
        started = self._monotonic()
        rows: list[dict[str, Any]] = []
        for index, node in enumerate(self.nodes):
            target = started + index * interval
            delay = target - self._monotonic()
            if delay > 0:
                self._sleep(delay)
            observed_at = self._monotonic()
            try:
                value = self._clients[node.endpoint.logical_id].execute(
                    "GET", node.canary.key
                )
                ok = _value_text(value) == node.canary.value
                error = "" if ok else f"unexpected value {value!r}"
            except Exception as exc:  # observed node data-path failure
                ok = False
                error = f"{type(exc).__name__}: {exc}"
            rows.append(
                {
                    "logical_id": node.endpoint.logical_id,
                    "role": node.role,
                    "shard_id": node.shard_id,
                    "slot": node.canary.slot,
                    "monotonic": observed_at,
                    "status": "OK" if ok else "FAIL",
                    "error": error,
                }
            )
        failures = [row for row in rows if row["status"] != "OK"]
        if failures:
            raise SemanticFailure(
                "Sentinel sweep failed: "
                + "; ".join(
                    f"{row['logical_id']}: {row['error']}" for row in failures[:20]
                )
            )
        return {
            "status": "OK",
            "duration_seconds": duration_seconds,
            "nodes_observed": len(rows),
            "get_count": len(rows),
            "rows": rows,
        }

    def fault_probe(
        self,
        *,
        affected: Canary,
        control: Canary,
        recovery_deadline_seconds: float,
        fault_monotonic: float,
        interval_seconds: float = 0.1,
        stable_rounds: int = 10,
        router: ClusterRouter | None = None,
    ) -> dict[str, Any]:
        if interval_seconds != 0.1:
            raise ValueError("Sentinel fault probe interval must be 100ms")
        if stable_rounds != 10:
            raise ValueError("Sentinel recovery requires exactly 10 stable rounds")
        owned_router = router is None
        if router is None:
            router = ClusterRouter(
                [
                    Endpoint(node.endpoint.host, node.endpoint.port)
                    for node in self.nodes
                    if node.role == "primary"
                ],
                timeout=self.timeout,
                connection_factory=self._factory,
            )
        deadline = fault_monotonic + recovery_deadline_seconds
        streak = 0
        streak_start: float | None = None
        rows: list[dict[str, Any]] = []
        try:
            while self._monotonic() <= deadline:
                round_started = self._monotonic()
                values: dict[str, Any] = {}
                errors: dict[str, str] = {}
                for label, canary in (("affected", affected), ("control", control)):
                    try:
                        values[label] = router.get(canary.key)
                    except Exception as exc:
                        errors[label] = f"{type(exc).__name__}: {exc}"
                ok = (
                    not errors
                    and _value_text(values.get("affected")) == affected.value
                    and _value_text(values.get("control")) == control.value
                )
                if ok:
                    if streak == 0:
                        streak_start = round_started
                    streak += 1
                else:
                    streak = 0
                    streak_start = None
                rows.append(
                    {
                        "monotonic": round_started,
                        "status": "OK" if ok else "FAIL",
                        "affected_value_ok": _value_text(
                            values.get("affected")
                        )
                        == affected.value,
                        "control_value_ok": _value_text(values.get("control"))
                        == control.value,
                        "errors": errors,
                        "stable_streak": streak,
                    }
                )
                if streak == stable_rounds:
                    assert streak_start is not None
                    return {
                        "status": "OK",
                        "interval_ms": 100,
                        "stable_rounds": stable_rounds,
                        "rto_ms": round(
                            max(streak_start - fault_monotonic, 0.0) * 1000, 3
                        ),
                        "stable_confirmed_at_monotonic": round_started,
                        "samples": rows,
                    }
                delay = interval_seconds - (self._monotonic() - round_started)
                if delay > 0:
                    self._sleep(delay)
        finally:
            if owned_router:
                router.close()
        raise SemanticFailure(
            "Sentinel affected/control canaries did not form 10 stable "
            "100ms rounds before the recovery deadline"
        )


def _value_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
