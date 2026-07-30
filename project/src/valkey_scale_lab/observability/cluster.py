from __future__ import annotations

import base64
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from valkey_scale_lab.observability.contracts import CollectionError, SemanticFailure
from valkey_scale_lab.valkey.resp import Endpoint, RespConnection

LIGHT_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("PING",),
    ("CLUSTER", "INFO"),
    ("ROLE",),
    ("CLUSTER", "MYID"),
    ("CLUSTER", "MYSHARDID"),
    ("CLUSTER", "MYSLOTS"),
)
MYSLOTS_FIELDS = (
    "node-id",
    "shard-id",
    "role",
    "slot-owner-id",
    "slot-count",
    "bitmap-encoding",
    "slot-bitmap",
)
FULL_SLOT_BITMAP = bytes([0xFF]) * 2048


def observation_complexity(
    node_count: int, *, observer_count: int = 3
) -> dict[str, int]:
    if node_count <= 0:
        raise ValueError("node count must be positive")
    if observer_count < 3 or observer_count > 5:
        raise ValueError("observer count must be between 3 and 5")
    return {
        "node_count": node_count,
        "light_command_count": node_count * len(LIGHT_COMMANDS),
        "light_bitmap_bytes": node_count * 2048,
        "cluster_shards_view_count": min(observer_count, node_count),
        "cluster_nodes_command_count": 0,
    }


@dataclass(frozen=True)
class NodeEndpoint:
    logical_id: str
    host: str
    port: int
    expected_role: str
    expected_shard: str
    az_id: str = ""
    placement_id: str = ""

    @classmethod
    def from_inventory(cls, node: Mapping[str, Any]) -> "NodeEndpoint":
        return cls(
            logical_id=str(node["logical_id"]),
            host=str(node.get("host", "127.0.0.1")),
            port=int(node["client_port"]),
            expected_role=str(node["role"]),
            expected_shard=str(node["shard_id"]),
            az_id=str(node.get("az_id", "")),
            placement_id=str(
                node.get("host_id")
                or node.get("nodehost_id")
                or node.get("nodehost_container_name")
                or node.get("container_name")
                or ""
            ),
        )


@dataclass(frozen=True)
class MySlots:
    node_id: str
    shard_id: str
    role: str
    slot_owner_id: str
    slot_count: int
    bitmap_encoding: str
    bitmap: bytes

    def as_dict(self) -> dict[str, Any]:
        return {
            "node-id": self.node_id,
            "shard-id": self.shard_id,
            "role": self.role,
            "slot-owner-id": self.slot_owner_id,
            "slot-count": self.slot_count,
            "bitmap-encoding": self.bitmap_encoding,
            "slot-bitmap-bytes": len(self.bitmap),
            "slot-bitmap-sha256": hashlib.sha256(self.bitmap).hexdigest(),
            "slot-bitmap-base64": base64.b64encode(self.bitmap).decode("ascii"),
        }


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    return str(value)


def parse_info(value: Any) -> dict[str, str]:
    text = _text(value)
    result: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, raw = line.partition(":")
        if separator:
            result[key] = raw
    return result


def _pairs(value: Any, *, label: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return {_text(key): item for key, item in value.items()}
    if isinstance(value, (list, tuple)) and len(value) % 2 == 0:
        return {
            _text(value[index]): value[index + 1]
            for index in range(0, len(value), 2)
        }
    raise SemanticFailure(f"{label} is not a RESP map or flat key/value array")


def parse_myslots(value: Any) -> MySlots:
    fields = _pairs(value, label="CLUSTER MYSLOTS response")
    if len(fields) != len(MYSLOTS_FIELDS) or set(fields) != set(MYSLOTS_FIELDS):
        raise SemanticFailure(
            "CLUSTER MYSLOTS fields differ from the fixed seven-field contract"
        )
    bitmap = fields["slot-bitmap"]
    if not isinstance(bitmap, bytes) or len(bitmap) != 2048:
        raise SemanticFailure("CLUSTER MYSLOTS slot-bitmap is not exactly 2048 bytes")
    try:
        slot_count = int(fields["slot-count"])
    except (TypeError, ValueError) as exc:
        raise SemanticFailure("CLUSTER MYSLOTS slot-count is not an integer") from exc
    result = MySlots(
        node_id=_text(fields["node-id"]),
        shard_id=_text(fields["shard-id"]),
        role=_text(fields["role"]),
        slot_owner_id=_text(fields["slot-owner-id"]),
        slot_count=slot_count,
        bitmap_encoding=_text(fields["bitmap-encoding"]),
        bitmap=bitmap,
    )
    if result.role not in {"primary", "replica"}:
        raise SemanticFailure(f"CLUSTER MYSLOTS returned invalid role {result.role!r}")
    if result.bitmap_encoding != "lsb0":
        raise SemanticFailure("CLUSTER MYSLOTS bitmap-encoding is not lsb0")
    if sum(bin(byte).count("1") for byte in bitmap) != slot_count:
        raise SemanticFailure("CLUSTER MYSLOTS slot-count does not match bitmap")
    return result


def parse_role(value: Any) -> dict[str, Any]:
    if not isinstance(value, (list, tuple)) or not value:
        raise SemanticFailure("ROLE response is not an array")
    raw_role = _text(value[0]).lower()
    if raw_role in {"master", "primary"}:
        return {"role": "primary", "replication_state": "not_applicable"}
    if raw_role not in {"slave", "replica"} or len(value) < 5:
        raise SemanticFailure(f"ROLE returned unsupported role {raw_role!r}")
    return {
        "role": "replica",
        "primary_host": _text(value[1]),
        "primary_port": int(value[2]),
        "replication_state": _text(value[3]).lower(),
        "replication_offset": int(value[4]),
    }


class LightClusterProbe:
    def __init__(
        self,
        nodes: Sequence[NodeEndpoint],
        *,
        concurrency: int = 64,
        timeout: float = 3.0,
        connection_factory: Callable[[Endpoint, float], RespConnection] | None = None,
    ) -> None:
        if not nodes:
            raise ValueError("light cluster probe requires at least one node")
        if concurrency < 32 or concurrency > 64:
            raise ValueError("light cluster probe concurrency must be between 32 and 64")
        self.nodes = list(nodes)
        self.concurrency = concurrency
        self.timeout = timeout
        self._connection_factory = connection_factory or (
            lambda endpoint, timeout: RespConnection(endpoint, timeout=timeout)
        )

    def observe_node(self, node: NodeEndpoint) -> dict[str, Any]:
        wall_started = time.time()
        monotonic_started = time.monotonic()
        try:
            with self._connection_factory(
                Endpoint(node.host, node.port), self.timeout
            ) as connection:
                values = connection.execute_many(LIGHT_COMMANDS)
        except Exception as exc:  # successfully classifiable endpoint observation
            return {
                "logical_id": node.logical_id,
                "host": node.host,
                "port": node.port,
                "status": "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
                "wall_time": wall_started,
                "monotonic": monotonic_started,
            }
        try:
            ping, info_raw, role_raw, node_id_raw, shard_id_raw, myslots_raw = values
            info = parse_info(info_raw)
            role = parse_role(role_raw)
            myslots = parse_myslots(myslots_raw)
            node_id = _text(node_id_raw)
            shard_id = _text(shard_id_raw)
            if ping not in {"PONG", b"PONG"}:
                raise SemanticFailure(f"PING returned {ping!r}")
            if node_id != myslots.node_id or shard_id != myslots.shard_id:
                raise SemanticFailure(
                    "CLUSTER MYID/MYSHARDID disagree with CLUSTER MYSLOTS"
                )
            if role["role"] != myslots.role:
                raise SemanticFailure("ROLE disagrees with CLUSTER MYSLOTS role")
        except Exception as exc:
            return {
                "logical_id": node.logical_id,
                "host": node.host,
                "port": node.port,
                "status": "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
                "wall_time": wall_started,
                "monotonic": monotonic_started,
            }
        return {
            "logical_id": node.logical_id,
            "host": node.host,
            "port": node.port,
            "expected_role": node.expected_role,
            "expected_shard": node.expected_shard,
            "az_id": node.az_id,
            "placement_id": node.placement_id,
            "status": "OK",
            "wall_time": wall_started,
            "monotonic": monotonic_started,
            "duration_ms": round((time.monotonic() - monotonic_started) * 1000, 3),
            "cluster_info": info,
            "role": role,
            "myslots": myslots,
        }

    def collect(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any] | None] = [None] * len(self.nodes)
        workers = min(self.concurrency, len(self.nodes))
        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(self.observe_node, node): index
                    for index, node in enumerate(self.nodes)
                }
                for future in as_completed(futures):
                    rows[futures[future]] = future.result()
        except Exception as exc:  # executor or collector implementation failed
            raise CollectionError(f"all-node light collection failed: {exc}") from exc
        if any(row is None for row in rows):
            raise CollectionError("all-node light collection lost a worker result")
        return [row for row in rows if row is not None]

    def collect_rolling(self, *, duration_seconds: float = 60.0) -> list[dict[str, Any]]:
        """Spread one observation per node evenly across the fixed round."""

        if duration_seconds != 60.0:
            raise ValueError("rolling light validation round must be 60 seconds")
        rows: list[dict[str, Any] | None] = [None] * len(self.nodes)
        interval = duration_seconds / len(self.nodes)
        started = time.monotonic()
        try:
            with ThreadPoolExecutor(
                max_workers=min(self.concurrency, len(self.nodes))
            ) as executor:
                futures: dict[Any, int] = {}
                for index, node in enumerate(self.nodes):
                    target = started + index * interval
                    delay = target - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    futures[executor.submit(self.observe_node, node)] = index
                for future in as_completed(futures):
                    rows[futures[future]] = future.result()
        except Exception as exc:
            raise CollectionError(f"rolling light collection failed: {exc}") from exc
        if any(row is None for row in rows):
            raise CollectionError("rolling light collection lost a worker result")
        return [row for row in rows if row is not None]

    def validate(
        self,
        rows: Sequence[dict[str, Any]],
        *,
        require_plan_roles: bool = True,
        require_replica_connected: bool = True,
        require_cluster_ok: bool = True,
        expected_unavailable: Iterable[str] = (),
    ) -> dict[str, Any]:
        if len(rows) != len(self.nodes):
            raise SemanticFailure(
                f"light observation covered {len(rows)}/{len(self.nodes)} nodes"
            )
        unavailable = set(expected_unavailable)
        unknown_unavailable = unavailable - {node.logical_id for node in self.nodes}
        if unknown_unavailable:
            raise ValueError(
                f"unknown expected-unavailable nodes: {sorted(unknown_unavailable)}"
            )
        failures = [
            f"{row.get('logical_id')}: {row.get('error', 'probe failed')}"
            for row in rows
            if row.get("status") != "OK"
            and row.get("logical_id") not in unavailable
        ]
        if failures:
            raise SemanticFailure("; ".join(failures[:20]))
        unexpectedly_available = [
            row["logical_id"]
            for row in rows
            if row.get("logical_id") in unavailable and row.get("status") == "OK"
        ]
        if unexpectedly_available:
            raise SemanticFailure(
                f"planned-down nodes remained available: {unexpectedly_available}"
            )
        by_logical = {node.logical_id: node for node in self.nodes}
        observations = [row for row in rows if row.get("status") == "OK"]
        node_ids = [row["myslots"].node_id for row in observations]
        if len(set(node_ids)) != len(node_ids):
            raise SemanticFailure("CLUSTER MYID values are not unique")

        shard_groups: dict[str, list[dict[str, Any]]] = {}
        primary_rows: list[dict[str, Any]] = []
        for row in observations:
            expected = by_logical[row["logical_id"]]
            myslots: MySlots = row["myslots"]
            if require_plan_roles and myslots.role != expected.expected_role:
                raise SemanticFailure(
                    f"{expected.logical_id} role is {myslots.role}, expected {expected.expected_role}"
                )
            if require_cluster_ok:
                info = row["cluster_info"]
                expected_info = {
                    "cluster_state": "ok",
                    "cluster_slots_assigned": "16384",
                    "cluster_slots_ok": "16384",
                    "cluster_slots_fail": "0",
                    "cluster_known_nodes": str(len(self.nodes)),
                }
                mismatches = {
                    key: {"expected": value, "observed": info.get(key)}
                    for key, value in expected_info.items()
                    if info.get(key) != value
                }
                if mismatches:
                    raise SemanticFailure(
                        f"{expected.logical_id} CLUSTER INFO mismatch: {mismatches}"
                    )
            if (
                require_replica_connected
                and myslots.role == "replica"
                and row["role"]["replication_state"] != "connected"
            ):
                raise SemanticFailure(
                    f"{expected.logical_id} replica link is "
                    f"{row['role']['replication_state']!r}"
                )
            shard_groups.setdefault(expected.expected_shard, []).append(row)
            if myslots.role == "primary":
                primary_rows.append(row)

        for expected_shard, group in shard_groups.items():
            primaries = [row for row in group if row["myslots"].role == "primary"]
            if len(primaries) != 1:
                raise SemanticFailure(
                    f"{expected_shard} has {len(primaries)} observed primaries"
                )
            primary = primaries[0]["myslots"]
            if primary.slot_owner_id != primary.node_id:
                raise SemanticFailure(f"{expected_shard} primary is not its slot owner")
            for row in group:
                myslots = row["myslots"]
                if myslots.shard_id != primary.shard_id:
                    raise SemanticFailure(
                        f"{expected_shard} members disagree on shard-id"
                    )
                if (
                    myslots.slot_owner_id != primary.node_id
                    or myslots.slot_count != primary.slot_count
                    or myslots.bitmap != primary.bitmap
                ):
                    raise SemanticFailure(
                        f"{row['logical_id']} does not match its shard primary bitmap"
                    )

        union = bytearray(2048)
        for row in primary_rows:
            bitmap = row["myslots"].bitmap
            for index, byte in enumerate(bitmap):
                if union[index] & byte:
                    raise SemanticFailure("primary slot bitmaps overlap")
                union[index] |= byte
        if bytes(union) != FULL_SLOT_BITMAP:
            raise SemanticFailure(
                "primary slot bitmap union does not cover slots 0..16383 exactly"
            )
        return {
            "status": "OK",
            "nodes_expected": len(self.nodes),
            "nodes_observed": len(observations),
            "nodes_expected_unavailable": sorted(unavailable),
            "primary_count": len(primary_rows),
            "replica_count": len(observations) - len(primary_rows),
            "shard_count": len(shard_groups),
            "coverage": {
                "all_slots_covered_exactly_once": True,
                "primary_bitmaps_pairwise_disjoint": True,
                "replicas_match_primaries": True,
                "inventory_roles_and_shards_match": require_plan_roles,
            },
            "nodes": [
                {
                    **{
                        key: value
                        for key, value in row.items()
                        if key not in {"myslots"}
                    },
                    "myslots": row["myslots"].as_dict(),
                }
                for row in observations
            ],
        }

    def run(self, **validation_options: Any) -> dict[str, Any]:
        return self.validate(self.collect(), **validation_options)


def choose_topology_observers(
    nodes: Sequence[NodeEndpoint], *, count: int = 3
) -> list[NodeEndpoint]:
    if count < 3 or count > 5:
        raise ValueError("CLUSTER SHARDS observer count must be between 3 and 5")
    target = min(count, len(nodes))
    selected: list[NodeEndpoint] = []
    seen_az: set[str] = set()
    seen_placement: set[str] = set()
    for node in nodes:
        if len(selected) == target:
            break
        if node.az_id not in seen_az or node.placement_id not in seen_placement:
            selected.append(node)
            seen_az.add(node.az_id)
            seen_placement.add(node.placement_id)
    for node in nodes:
        if len(selected) == target:
            break
        if node not in selected:
            selected.append(node)
    return selected


def _integer(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SemanticFailure(f"{label} is not an integer") from exc


def normalize_cluster_shards(
    value: Any, *, allowed_unhealthy_node_ids: Iterable[str] = ()
) -> dict[str, Any]:
    if not isinstance(value, (list, tuple)):
        raise SemanticFailure("CLUSTER SHARDS response is not an array")
    shards: list[dict[str, Any]] = []
    all_ranges: list[tuple[int, int]] = []
    allowed_unhealthy = set(allowed_unhealthy_node_ids)
    for shard_value in value:
        shard = _pairs(shard_value, label="CLUSTER SHARDS shard")
        slots_raw = shard.get("slots")
        nodes_raw = shard.get("nodes")
        if not isinstance(slots_raw, (list, tuple)) or len(slots_raw) % 2:
            raise SemanticFailure("CLUSTER SHARDS slots is not start/end pairs")
        if not isinstance(nodes_raw, (list, tuple)) or not nodes_raw:
            raise SemanticFailure("CLUSTER SHARDS shard has no nodes")
        ranges = [
            (
                _integer(slots_raw[index], "slot start"),
                _integer(slots_raw[index + 1], "slot end"),
            )
            for index in range(0, len(slots_raw), 2)
        ]
        all_ranges.extend(ranges)
        members: list[dict[str, Any]] = []
        for node_value in nodes_raw:
            node = _pairs(node_value, label="CLUSTER SHARDS node")
            raw_role = _text(node.get("role", "")).lower()
            role = "primary" if raw_role in {"master", "primary"} else "replica"
            node_id = _text(node.get("id", ""))
            if not node_id or raw_role not in {"master", "primary", "slave", "replica"}:
                raise SemanticFailure("CLUSTER SHARDS node has invalid id or role")
            members.append(
                {
                    "node_id": node_id,
                    "role": role,
                    "endpoint": _text(node.get("endpoint", node.get("ip", ""))),
                    "port": _integer(node.get("port", 0), "node port"),
                    "health": _text(node.get("health", "")),
                }
            )
        unhealthy = [
            member
            for member in members
            if member["health"].lower() not in {"online", "healthy"}
            and member["node_id"] not in allowed_unhealthy
        ]
        if unhealthy:
            raise SemanticFailure(
                "CLUSTER SHARDS contains unhealthy nodes: "
                + ", ".join(member["node_id"] for member in unhealthy)
            )
        primaries = [member for member in members if member["role"] == "primary"]
        if len(primaries) != 1:
            raise SemanticFailure(
                f"CLUSTER SHARDS shard has {len(primaries)} primaries"
            )
        primary_id = primaries[0]["node_id"]
        shards.append(
            {
                "shard_id": primary_id,
                "slots": sorted(ranges),
                "primary_id": primary_id,
                "nodes": sorted(members, key=lambda member: member["node_id"]),
            }
        )
    _validate_slot_ranges(all_ranges)
    return {
        "shard_count": len(shards),
        "shards": sorted(shards, key=lambda shard: shard["shard_id"]),
        "all_slots_covered_exactly_once": True,
    }


def _validate_slot_ranges(ranges: Iterable[tuple[int, int]]) -> None:
    coverage = bytearray(16384)
    for start, end in ranges:
        if start < 0 or end > 16383 or start > end:
            raise SemanticFailure(f"invalid CLUSTER SHARDS slot range {start}-{end}")
        for slot in range(start, end + 1):
            if coverage[slot]:
                raise SemanticFailure(f"CLUSTER SHARDS slot {slot} is duplicated")
            coverage[slot] = 1
    if any(value != 1 for value in coverage):
        raise SemanticFailure("CLUSTER SHARDS slot ranges do not cover 0..16383")


class TopologyObserver:
    def __init__(
        self,
        nodes: Sequence[NodeEndpoint],
        *,
        observer_count: int = 3,
        timeout: float = 5.0,
        connection_factory: Callable[[Endpoint, float], RespConnection] | None = None,
    ) -> None:
        self.nodes = list(nodes)
        self.observers = choose_topology_observers(nodes, count=observer_count)
        self.timeout = timeout
        self._connection_factory = connection_factory or (
            lambda endpoint, timeout: RespConnection(endpoint, timeout=timeout)
        )

    def run(
        self,
        *,
        expected_node_count: int | None = None,
        allowed_unhealthy_node_ids: Iterable[str] = (),
        excluded_observer_logical_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        views: list[dict[str, Any]] = []
        excluded = set(excluded_observer_logical_ids)
        available = [node for node in self.nodes if node.logical_id not in excluded]
        observers = choose_topology_observers(
            available, count=min(max(len(self.observers), 3), 5)
        )
        for observer in observers:
            try:
                with self._connection_factory(
                    Endpoint(observer.host, observer.port), self.timeout
                ) as connection:
                    raw = connection.execute("CLUSTER", "SHARDS")
            except Exception as exc:
                raise SemanticFailure(
                    f"{observer.logical_id} CLUSTER SHARDS failed: {exc}"
                ) from exc
            normalized = normalize_cluster_shards(
                raw,
                allowed_unhealthy_node_ids=allowed_unhealthy_node_ids,
            )
            views.append(
                {
                    "logical_id": observer.logical_id,
                    "az_id": observer.az_id,
                    "placement_id": observer.placement_id,
                    "wall_time": time.time(),
                    "monotonic": time.monotonic(),
                    "view": normalized,
                }
            )
        if not views:
            raise CollectionError("no CLUSTER SHARDS observer was selected")
        baseline = views[0]["view"]
        for row in views[1:]:
            if row["view"] != baseline:
                raise SemanticFailure(
                    "CLUSTER SHARDS observers disagree on normalized topology"
                )
        node_ids = {
            member["node_id"]
            for shard in baseline["shards"]
            for member in shard["nodes"]
        }
        expected = expected_node_count if expected_node_count is not None else len(self.nodes)
        if len(node_ids) != expected:
            raise SemanticFailure(
                f"CLUSTER SHARDS contains {len(node_ids)}/{expected} unique nodes"
            )
        return {
            "status": "OK",
            "observer_count": len(views),
            "observers": views,
            "normalized_topology": baseline,
        }


class FullClusterValidator:
    """The exact layer-one plus layer-two replacement for a full validation."""

    def __init__(
        self,
        nodes: Sequence[NodeEndpoint],
        *,
        concurrency: int = 64,
        observer_count: int = 3,
        timeout: float = 5.0,
        connection_factory: Callable[[Endpoint, float], RespConnection] | None = None,
    ) -> None:
        self.light = LightClusterProbe(
            nodes,
            concurrency=concurrency,
            timeout=timeout,
            connection_factory=connection_factory,
        )
        self.topology = TopologyObserver(
            nodes,
            observer_count=observer_count,
            timeout=timeout,
            connection_factory=connection_factory,
        )

    def run(self, **validation_options: Any) -> dict[str, Any]:
        allowed_unhealthy = set(
            validation_options.pop("allowed_unhealthy_node_ids", ())
        )
        expected_unavailable = set(
            validation_options.get("expected_unavailable", ())
        )
        light = self.light.run(**validation_options)
        topology = self.topology.run(
            expected_node_count=len(self.light.nodes),
            allowed_unhealthy_node_ids=allowed_unhealthy,
            excluded_observer_logical_ids=expected_unavailable,
        )
        light_shards: dict[str, dict[str, Any]] = {}
        for row in light["nodes"]:
            fields = row["myslots"]
            owner = fields["slot-owner-id"]
            shard = light_shards.setdefault(
                owner,
                {
                    "bitmap_sha256": fields["slot-bitmap-sha256"],
                    "members": [],
                },
            )
            if shard["bitmap_sha256"] != fields["slot-bitmap-sha256"]:
                raise SemanticFailure(
                    "light shard members disagree before topology correlation"
                )
            shard["members"].append(fields["node-id"])
        topology_shards: dict[str, dict[str, Any]] = {}
        for shard in topology["normalized_topology"]["shards"]:
            bitmap = bytearray(2048)
            for start, end in shard["slots"]:
                for slot in range(start, end + 1):
                    bitmap[slot >> 3] |= 1 << (slot & 7)
            topology_shards[shard["primary_id"]] = {
                "bitmap_sha256": hashlib.sha256(bitmap).hexdigest(),
                "members": [
                    member["node_id"]
                    for member in shard["nodes"]
                    if member["node_id"] not in allowed_unhealthy
                ],
            }
        canonical_light = {
            primary: {
                "bitmap_sha256": shard["bitmap_sha256"],
                "members": sorted(shard["members"]),
            }
            for primary, shard in light_shards.items()
        }
        canonical_topology = {
            primary: {
                "bitmap_sha256": shard["bitmap_sha256"],
                "members": sorted(shard["members"]),
            }
            for primary, shard in topology_shards.items()
        }
        if canonical_light != canonical_topology:
            raise SemanticFailure(
                "light CLUSTER MYSLOTS ownership disagrees with CLUSTER SHARDS"
            )
        return {
            "status": "OK",
            "complexity": observation_complexity(
                len(self.light.nodes),
                observer_count=len(self.topology.observers),
            ),
            "light_validation": light,
            "topology_validation": topology,
        }
