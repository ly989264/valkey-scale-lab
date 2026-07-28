from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from valkey_scale_lab.observability.cluster import NodeEndpoint, parse_info, parse_role
from valkey_scale_lab.observability.contracts import CollectionError, SemanticFailure
from valkey_scale_lab.valkey.resp import Endpoint, RespConnection


class ActuatorRecorder:
    """Authoritative, minimal record of one requested fault action."""

    def __init__(
        self,
        *,
        target: str,
        action: str,
        wall_clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.target = target
        self.action = action
        self._wall = wall_clock
        self._monotonic = monotonic
        self.record: dict[str, Any] = {
            "target": target,
            "action": action,
            "action_start": None,
            "signal_or_request_sent": None,
            "action_completed": None,
            "result": None,
        }

    def start(self) -> None:
        self.record["action_start"] = self._timestamp()

    def sent(self) -> None:
        if self.record["action_start"] is None:
            raise CollectionError("actuator request was sent before action start")
        self.record["signal_or_request_sent"] = self._timestamp()

    def complete(self, *, result: str) -> dict[str, Any]:
        if self.record["signal_or_request_sent"] is None:
            raise CollectionError("actuator completed without sending the action")
        self.record["action_completed"] = self._timestamp()
        self.record["result"] = result
        if result != "OK":
            raise CollectionError(
                f"actuator could not execute {self.action} on {self.target}: {result}"
            )
        return dict(self.record)

    def _timestamp(self) -> dict[str, float]:
        return {"wall_time": self._wall(), "monotonic": self._monotonic()}


@dataclass
class _SurvivorConnection:
    node: NodeEndpoint
    connection: RespConnection | None = None


class AffectedShardObserver:
    """500ms ROLE + CLUSTER INFO observer for only the surviving target shard."""

    def __init__(
        self,
        survivors: Sequence[NodeEndpoint],
        *,
        interval_seconds: float = 0.5,
        timeout: float = 1.0,
        connection_factory: Callable[[Endpoint, float], RespConnection] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not survivors:
            raise ValueError("affected shard observer requires surviving nodes")
        if interval_seconds != 0.5:
            raise ValueError("affected shard observer interval must be 500ms")
        expected_shards = {node.expected_shard for node in survivors}
        if len(expected_shards) != 1:
            raise ValueError("affected shard observer received multiple shards")
        self.survivors = [_SurvivorConnection(node) for node in survivors]
        self.interval_seconds = interval_seconds
        self.timeout = timeout
        self._factory = connection_factory or (
            lambda endpoint, timeout: RespConnection(endpoint, timeout=timeout)
        )
        self._sleep = sleep
        self._monotonic = monotonic

    def close(self) -> None:
        for survivor in self.survivors:
            if survivor.connection is not None:
                survivor.connection.close()
                survivor.connection = None

    def _connection(self, survivor: _SurvivorConnection) -> RespConnection:
        if survivor.connection is None:
            survivor.connection = self._factory(
                Endpoint(survivor.node.host, survivor.node.port), self.timeout
            )
        return survivor.connection

    def sample_round(self) -> dict[str, Any]:
        started = self._monotonic()
        rows: list[dict[str, Any]] = []
        for survivor in self.survivors:
            try:
                role_raw, info_raw = self._connection(survivor).execute_many(
                    [("ROLE",), ("CLUSTER", "INFO")]
                )
                role = parse_role(role_raw)
                info = parse_info(info_raw)
                rows.append(
                    {
                        "logical_id": survivor.node.logical_id,
                        "host": survivor.node.host,
                        "port": survivor.node.port,
                        "status": "OK",
                        "role": role,
                        "cluster_state": info.get("cluster_state"),
                    }
                )
            except Exception as exc:  # transient during failover is observed data
                if survivor.connection is not None:
                    survivor.connection.close()
                    survivor.connection = None
                rows.append(
                    {
                        "logical_id": survivor.node.logical_id,
                        "status": "TRANSIENT",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        relationship = self._relationship(rows)
        return {
            "monotonic": started,
            "rows": rows,
            "candidate": relationship,
        }

    @staticmethod
    def _relationship(rows: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
        if any(
            row.get("status") != "OK" or row.get("cluster_state") != "ok"
            for row in rows
        ):
            return None
        primaries = [
            row for row in rows if row.get("role", {}).get("role") == "primary"
        ]
        if len(primaries) != 1:
            return None
        primary = primaries[0]
        for row in rows:
            role = row["role"]
            if role["role"] == "replica" and (
                role.get("primary_host") != primary["host"]
                or int(role.get("primary_port", -1)) != int(primary["port"])
            ):
                return None
        return {
            "primary": primary["logical_id"],
            "relationships": {
                row["logical_id"]: (
                    "primary"
                    if row["role"]["role"] == "primary"
                    else f"replica-of:{primary['logical_id']}"
                )
                for row in rows
            },
        }

    def wait_for_convergence(
        self,
        *,
        deadline_seconds: float,
        full_validation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        deadline = self._monotonic() + deadline_seconds
        previous: dict[str, Any] | None = None
        previous_at: float | None = None
        rounds: list[dict[str, Any]] = []
        try:
            while self._monotonic() <= deadline:
                round_result = self.sample_round()
                rounds.append(round_result)
                candidate = round_result["candidate"]
                if (
                    candidate is not None
                    and previous == candidate
                    and previous_at is not None
                    and round_result["monotonic"] - previous_at >= 0.5
                ):
                    complete = full_validation()
                    if complete.get("status") != "OK":
                        raise SemanticFailure(
                            "formal full validation did not confirm failover convergence"
                        )
                    return {
                        "status": "OK",
                        "candidate_rounds_required": 2,
                        "round_interval_ms": 500,
                        "converged_relationship": candidate,
                        "rounds": rounds,
                        "full_validation": complete,
                        "failover_success": True,
                    }
                previous = candidate
                previous_at = (
                    round_result["monotonic"] if candidate is not None else None
                )
                remaining = deadline - self._monotonic()
                if remaining > 0:
                    self._sleep(min(self.interval_seconds, remaining))
        finally:
            self.close()
        raise SemanticFailure(
            "affected shard did not produce two identical healthy 500ms rounds "
            "and a passing full validation before the deadline"
        )


def redundancy_recovery(
    light_report: dict[str, Any],
    *,
    expected_replicas_per_shard: int,
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in light_report.get("nodes", []):
        fields = row.get("myslots", {})
        groups.setdefault(str(fields.get("shard-id")), []).append(row)
    incomplete: dict[str, Any] = {}
    for shard_id, rows in groups.items():
        replicas = [
            row for row in rows if row.get("myslots", {}).get("role") == "replica"
        ]
        connected = [
            row
            for row in replicas
            if row.get("role", {}).get("replication_state") == "connected"
        ]
        if len(replicas) != expected_replicas_per_shard or len(connected) != len(
            replicas
        ):
            incomplete[shard_id] = {
                "replicas": len(replicas),
                "connected": len(connected),
                "expected": expected_replicas_per_shard,
            }
    if incomplete:
        raise SemanticFailure(f"redundancy recovery is incomplete: {incomplete}")
    return {
        "status": "OK",
        "shard_count": len(groups),
        "expected_replicas_per_shard": expected_replicas_per_shard,
        "replicas_connected": True,
    }
