from __future__ import annotations

import base64
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from valkey_scale_lab.observability.contracts import (
    CollectionError,
    ConvergenceFailure,
    SemanticFailure,
    is_collection_failure,
    is_transient_transport_error,
)
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
# A freshly formed cluster reports every replica as `loading` until each
# observer learns that replica's non-zero replication offset through gossip.
# Measured at 200 nodes, that resolves as a serialised queue: exactly one node is
# unhealthy at a time, it clears, the next appears. Total convergence is
# therefore (laggards) x (per-laggard dwell) and *both* factors grow with node
# count, so no fixed total can hold across scales. Five exact-200 formations
# measured 83.1s, 102.5s, 137.0s, 152.0s and 205.8s - one of five past the old
# 180s bound, matching the flakiness that prompted this.
#
# The wait is therefore bounded on lack of progress rather than on total time.
# Progress is a node *leaving* the unhealthy set; a set that only grows is not
# progress. That quantity is bounded by the longest single dwell, which grows far
# more slowly than the total: 14.3s at 30 nodes against 83.1s at 200, over 26
# measured dwells whose median is 23.5s and p90 51.1s.
#
# 240s is ~2.9x the longest dwell observed and ~4.7x the p90. It is deliberately
# larger than the 180s it replaces: a single laggard legitimately held one node
# unhealthy, unchanged, for 83.1s in a run that then converged, so anything
# tighter rejects a healthy cluster. This is not scale-free and will need
# re-measuring before 500 nodes.
CONVERGENCE_NO_PROGRESS_SECONDS = 240.0
# Re-measured at 1280 nodes on 2026-08-18, which is what the paragraph above
# asked for. The dwell really is close to linear in node count - 14.3s at 30 and
# 83.1s at 200 are 0.477 and 0.416 seconds per node - so the same 2.9x margin
# gives 1.25s per node, and a fixed 240s is a bound for 192 nodes and no more.
#
# Measured directly, sampling `CLUSTER SHARDS` health across all 1280 nodes every
# 20s while a real run formed: replicas leave the `loading` set steadily, 25 -> 7
# over 225s, roughly one every 12.5s. Nothing was stuck and the cluster was `ok`
# with 16384 slots and 1280 known nodes throughout - but as the tail empties the
# gap between departures grows, and three 1280-node runs were failed by it with a
# single replica still `loading`.
#
# Scaled, not simply raised, so the small scales keep the bound they were
# measured under: the floor binds at and below 192 nodes, so exact-30 and
# exact-50 are byte-for-byte unaffected. **exact-200 moves 240s -> 250s**, and
# that is stated rather than fudged away - the bound only decides how long a run
# waits before declaring a cluster stuck, so a longer one can never fail a run
# that passes, nor change any artifact of one. It costs 10s only on a run that
# was going to fail anyway.
def convergence_no_progress_seconds(node_count: int) -> float:
    """The no-progress bound for a cluster of this size, floored at the constant."""

    return max(CONVERGENCE_NO_PROGRESS_SECONDS, 1.25 * max(0, int(node_count)))


# The backstop, not the discriminator. Only reachable when the queue keeps moving
# for this long, which at 2000 nodes could be legitimate, so it is generous: its
# job is to bound the run, not to judge the cluster.
CONVERGENCE_TIMEOUT_SECONDS = 1800.0
# Each attempt re-probes every node, so polling too fast adds load to the very
# cluster being measured.
CONVERGENCE_POLL_SECONDS = 2.0


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
    # Where this node is reached from the controller (`host`) and the address
    # it announces to its peers (`announced_host`) are two different things,
    # and a Docker run is the case where they differ: the controller dials a
    # published port on 127.0.0.1 while the cluster announces the nodehost's
    # network address. Anything comparing what one node says about another -
    # a replica naming its primary, say - must compare announced to announced,
    # because that is the only vocabulary the nodes themselves speak.
    announced_host: str = ""

    @classmethod
    def from_inventory(cls, node: Mapping[str, Any]) -> "NodeEndpoint":
        return cls(
            logical_id=str(node["logical_id"]),
            host=str(node.get("host", "127.0.0.1")),
            port=int(node["client_port"]),
            # `container_ip` is the peer address on both backends - the Docker
            # nodehost's network address, and `started.address` on a native
            # host - so this needs no backend branch. It falls back to `host`
            # for an inventory that carries no separate announced address.
            announced_host=str(node.get("container_ip") or node.get("host", "127.0.0.1")),
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


class EndpointConnections:
    """One RESP connection per endpoint, kept between probe rounds.

    The probe used to open and close a connection per node per round, and each
    caller builds a fresh probe, so nothing survived a round. Section 14 budgets
    O(N) *persistent* connections for the Sentinel and Load lanes and names FD
    pressure as the 2000-node preflight risk; it budgets no connection churn at
    all, and section 4.1 asks large-scale checks not to flood. Measured on one
    complete exact-200 run: 165,095 host TCP connections, 97,000 of them from
    485 whole-fleet probes, ending in `[Errno 49] Can't assign requested
    address` once the host's 16,384 ephemeral ports were gone. The Sentinel lane
    already holds a connection per endpoint; this gives the probe the same
    discipline, which section 17 leaves to the implementation.

    A connection is checked out for the duration of one observation and returned
    afterwards, so two threads never share a socket.
    """

    def __init__(self, *, reuse: bool = True) -> None:
        self.reuse = reuse
        self._lock = threading.Lock()
        self._idle: dict[tuple[str, int], RespConnection] = {}

    def take(
        self,
        endpoint: Endpoint,
        timeout: float,
        factory: Callable[[Endpoint, float], RespConnection],
    ) -> tuple[RespConnection, bool]:
        if self.reuse:
            with self._lock:
                connection = self._idle.pop((endpoint.host, endpoint.port), None)
            if connection is not None:
                return connection, True
        return factory(endpoint, timeout), False

    def give_back(self, endpoint: Endpoint, connection: RespConnection) -> None:
        if not self.reuse:
            connection.close()
            return
        key = (endpoint.host, endpoint.port)
        with self._lock:
            if key not in self._idle:
                self._idle[key] = connection
                return
        # Two observations of one endpoint overlapped; keep the first one back.
        connection.close()

    def close_all(self) -> None:
        with self._lock:
            idle, self._idle = list(self._idle.values()), {}
        for connection in idle:
            connection.close()


# The probe is rebuilt at every call site, so the connections have to outlive it
# somewhere. Endpoints are unique per run and a run is one process.
SHARED_CONNECTIONS = EndpointConnections()


class LightClusterProbe:
    def __init__(
        self,
        nodes: Sequence[NodeEndpoint],
        *,
        concurrency: int = 64,
        timeout: float = 3.0,
        connection_factory: Callable[[Endpoint, float], RespConnection] | None = None,
        connections: EndpointConnections | None = None,
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
        # A caller that supplies its own factory owns its connections' lifetime,
        # so it opts into reuse explicitly rather than inheriting the pool.
        self._connections = connections or (
            SHARED_CONNECTIONS
            if connection_factory is None
            else EndpointConnections(reuse=False)
        )

    def _light_commands(self, endpoint: Endpoint) -> list[Any]:
        connection, reused = self._connections.take(
            endpoint, self.timeout, self._connection_factory
        )
        try:
            values = connection.execute_many(LIGHT_COMMANDS)
        except Exception:
            connection.close()
            if not reused:
                raise
            # A kept connection can be closed by the peer between rounds, and a
            # dead socket is not evidence about the node. What the node is doing
            # is whatever a new connection finds, so the error reported for it
            # always comes from a fresh connect - a node that is really gone
            # still reports its own refusal rather than this stale one.
            connection = self._connection_factory(endpoint, self.timeout)
            try:
                values = connection.execute_many(LIGHT_COMMANDS)
            except Exception:
                connection.close()
                raise
        self._connections.give_back(endpoint, connection)
        return values

    @staticmethod
    def _failed_row(
        node: NodeEndpoint,
        exc: BaseException,
        wall_started: float,
        monotonic_started: float,
    ) -> dict[str, Any]:
        """One node's failed observation, keeping which §12.1 kind it was.

        The row is the only thing that outlives the exception, so recording just
        a rendered message throws away the distinction acceptance item 12 exists
        to protect - and every consumer that then had to guess got it wrong the
        same way, by treating an unobserved node as an absent one.
        """

        return {
            "logical_id": node.logical_id,
            "host": node.host,
            "port": node.port,
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
            "failure_kind": "tool" if is_collection_failure(exc) else "semantic",
            # A second field, not a changed one. `failure_kind` is §12.1's
            # verdict axis and stays exactly as it was - a timeout is still a
            # *semantic* observation of a node that did not answer. This says
            # whether asking again is reasonable, which is a different question
            # and the only one a retry layer can act on: without it a caller
            # reading this row cannot tell "timed out" from "answered wrongly",
            # because both render as `semantic`.
            "transport_transient": is_transient_transport_error(exc),
            "wall_time": wall_started,
            "monotonic": monotonic_started,
        }

    def observe_node(self, node: NodeEndpoint) -> dict[str, Any]:
        wall_started = time.time()
        monotonic_started = time.monotonic()
        try:
            values = self._light_commands(Endpoint(node.host, node.port))
        except Exception as exc:  # successfully classifiable endpoint observation
            return self._failed_row(node, exc, wall_started, monotonic_started)
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
            return self._failed_row(node, exc, wall_started, monotonic_started)
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
                raise ConvergenceFailure(
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


def cluster_shards_node_ids(value: Any) -> set[str]:
    """The node ids an observer still knows, from a CLUSTER SHARDS reply.

    Membership is a different question from health. Whether one node is still
    known to the cluster cannot depend on whether some unrelated node has
    finished converging, so this reads ids only and asserts no health contract.
    Callers that need the health contract use `normalize_cluster_shards`.
    """
    if not isinstance(value, (list, tuple)):
        raise SemanticFailure("CLUSTER SHARDS response is not an array")
    node_ids: set[str] = set()
    for shard_value in value:
        shard = _pairs(shard_value, label="CLUSTER SHARDS shard")
        nodes_raw = shard.get("nodes")
        if not isinstance(nodes_raw, (list, tuple)) or not nodes_raw:
            raise SemanticFailure("CLUSTER SHARDS shard has no nodes")
        for node_value in nodes_raw:
            node = _pairs(node_value, label="CLUSTER SHARDS node")
            node_id = _text(node.get("id", ""))
            if not node_id:
                raise SemanticFailure("CLUSTER SHARDS node has invalid id or role")
            node_ids.add(node_id)
    return node_ids


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
            raise ConvergenceFailure(
                "CLUSTER SHARDS contains unhealthy nodes: "
                + ", ".join(member["node_id"] for member in unhealthy),
                pending=[member["node_id"] for member in unhealthy],
            )
        # A shard is described by the primary actually serving it. A primary the
        # cluster has marked failed stays in the shard until something removes
        # it, so counting every primary would reject the correct state a shard
        # settles into after a failover. Anything unhealthy that the caller did
        # not declare expected-down has already failed the health check above,
        # so a failed member reaching this point is one the caller named.
        primaries = [member for member in members if member["role"] == "primary"]
        healthy_primaries = [
            member
            for member in primaries
            if member["health"].lower() in {"online", "healthy"}
        ]
        detail = ", ".join(
            f"{member['node_id']}({member['health'] or 'MISSING'})"
            for member in primaries
        )
        if len(healthy_primaries) > 1:
            # Two primaries both serving is split brain. It does not resolve by
            # looking again, and must never be waited out.
            raise SemanticFailure(
                f"CLUSTER SHARDS shard has {len(healthy_primaries)} healthy "
                f"primaries: {detail}"
            )
        if not healthy_primaries:
            # Nothing is serving the shard: either a promotion is in flight or
            # the shard is down. Both are worth observing again.
            raise ConvergenceFailure(
                "CLUSTER SHARDS shard has no serving primary"
                + (f": {detail}" if primaries else "")
            )
        primary_id = healthy_primaries[0]["node_id"]
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


# How many replacement observers one slot may dial before the AZ is declared
# unreadable. See `TopologyObserver._substitutes_for` for why this is capped at
# all: uncapped, one slot could dial every node in its AZ - 640 at 1280 nodes -
# at a 5s connect timeout apiece.
MAX_OBSERVER_SUBSTITUTIONS = 2


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

    def _substitutes_for(
        self,
        observer: NodeEndpoint,
        *,
        available: Sequence[NodeEndpoint],
        chosen: set[str],
        used_placements: set[str],
    ) -> list[NodeEndpoint]:
        """Replacements for one observer, at most `MAX_OBSERVER_SUBSTITUTIONS`.

        Never crosses the AZ. A substitute from another AZ would answer a
        question about the wrong part of the cluster, which is the fail-open
        behaviour this exists instead of.

        Three orderings, applied in turn:

        1. A placement no answering observer already occupies, and not the one
           that just failed. This is the ordinary case and it is what preserves
           the spread `choose_topology_observers` paid for - without it a
           substitute could land on a placement another view already came from,
           leaving two of three views inside one fault domain.
        2. Any other placement in the AZ. Diversity is preferred, not required:
           a reading from a doubled-up placement still beats no reading.
        3. The failed observer's own placement, last. The placement is this
           product's fault domain - `isolate_nodehost` isolates a whole
           `placement_id` - so when a node cannot be reached, its own nodehost is
           the *least* likely thing to answer, and dialling it first would spend
           the budget on a machine that is probably dark. It is kept rather than
           dropped because a single node can also fail alone.

        **The list is capped, and the cap is the point.** An uncapped walk would
        offer every node in the AZ - up to 640 at 1280 nodes - and at a 5s
        connect timeout that is ~53 minutes of serial dialling inside gates whose
        whole budget used to be one 5s dial. Two substitutes per slot bounds a
        three-observer read at 9 dials, so the worst case grows from ~15s to
        ~45s: enough to survive independent transients on two distinct fault
        domains, and still far inside the 180s the fault lane allows itself.

        The cap also protects contemporaneity. The three views are read serially
        and compared for equality, and "observers disagree" is a permanent
        `SemanticFailure` rather than a retryable one, so a long walk across a
        converging cluster would turn a transient timeout into a false permanent
        disagreement.

        The residual is bounded and it fails **closed**, which is why the views
        are not simply re-read from scratch after a substitution. A view taken up
        to the cap's worth of time later on a moving cluster can only produce a
        spurious disagreement - a run that would have passed fails, and says why
        in `observer_substitutions` - never a false pass. It can only happen when
        a transient has already occurred, and re-reading would add dials to a
        cluster that is already showing distress. If a real run ever reports a
        disagreement whose substitutions list is non-empty and whose views'
        `monotonic` stamps straddle the walk, a one-shot re-read is the recorded
        fix; until then it is speculative machinery.
        """

        def rank(node: NodeEndpoint) -> int:
            if node.placement_id == observer.placement_id:
                return 2
            if node.placement_id in used_placements:
                return 1
            return 0

        candidates = [
            node
            for node in available
            if node.logical_id not in chosen and node.az_id == observer.az_id
        ]
        candidates.sort(key=rank)
        return candidates[:MAX_OBSERVER_SUBSTITUTIONS]

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
        chosen = {observer.logical_id for observer in observers}
        used_placements: set[str] = set()
        substitutions: list[dict[str, Any]] = []
        for observer in observers:
            # A transiently unreachable observer is replaced by another node in
            # the *same* AZ rather than tolerated, and the read is taken again.
            # Tolerating it - a quorum of two agreeing views - would fail open on
            # exactly the event this redundancy exists to catch:
            # `choose_topology_observers` spreads across `az_id` and
            # `placement_id`, so under an AZ partition the observer that is lost
            # is the one correlated with the partition, and "cannot see AZ-b"
            # would be recorded as "AZ-b concurs". Substitution keeps the
            # question being asked of that AZ; only a *stated* answer counts.
            #
            # **The invariant this leans on**, so that whoever breaks it knows:
            # a substitute reads whichever side of a *nodehost*-level partition
            # it is on, and that is non-fatal only because this layer never gates
            # alone. `FullClusterValidator` runs `LightClusterProbe` over **every**
            # node, so an unreachable nodehost fails layer one whatever this layer
            # chose, and this layer's own contract is agreement between vantage
            # points rather than reachability. A topology-only gate with no light
            # layer would turn substitution into a fail-open hole.
            attempted: list[dict[str, str]] = []
            candidates = [observer] + self._substitutes_for(
                observer,
                available=available,
                chosen=chosen,
                used_placements=used_placements,
            )
            raw: Any = None
            answered: NodeEndpoint | None = None
            for candidate in candidates:
                try:
                    with self._connection_factory(
                        Endpoint(candidate.host, candidate.port), self.timeout
                    ) as connection:
                        raw = connection.execute("CLUSTER", "SHARDS")
                except Exception as exc:
                    if not is_transient_transport_error(exc):
                        raise SemanticFailure(
                            f"{candidate.logical_id} CLUSTER SHARDS failed: {exc}"
                        ) from exc
                    attempted.append(
                        {
                            "logical_id": candidate.logical_id,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    chosen.add(candidate.logical_id)
                    continue
                answered = candidate
                break
            if answered is None:
                # Every node this AZ and placement can offer was asked and none
                # answered. That is the fail-closed case and it is a semantic
                # observation: this part of the cluster cannot be read.
                detail = "; ".join(
                    f"{row['logical_id']} ({row['error']})" for row in attempted
                )
                raise SemanticFailure(
                    f"no readable CLUSTER SHARDS observer in az={observer.az_id!r} "
                    f"for planned observer {observer.logical_id} "
                    f"after {len(attempted)} attempt(s): {detail}"
                )
            if answered is not observer:
                substitutions.append(
                    {
                        "planned_logical_id": observer.logical_id,
                        "substituted_logical_id": answered.logical_id,
                        "az_id": answered.az_id,
                        "placement_id": answered.placement_id,
                        "attempts": attempted,
                    }
                )
            chosen.add(answered.logical_id)
            used_placements.add(answered.placement_id)
            normalized = normalize_cluster_shards(
                raw,
                allowed_unhealthy_node_ids=allowed_unhealthy_node_ids,
            )
            views.append(
                {
                    "logical_id": answered.logical_id,
                    "az_id": answered.az_id,
                    "placement_id": answered.placement_id,
                    "planned_logical_id": observer.logical_id,
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
            # Always present, so a reader can tell "no observer had to be
            # replaced" from "this artifact predates substitution". An empty
            # list is the ordinary case.
            "observer_substitutions": substitutions,
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
        convergence_timeout: float | None = None,
        convergence_poll_seconds: float = CONVERGENCE_POLL_SECONDS,
        no_progress_seconds: float | None = None,
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
        # Both bounds default from the cluster's own size. An explicit value
        # always wins, so every existing test and caller that states one is
        # unaffected.
        self.no_progress_seconds = (
            convergence_no_progress_seconds(len(nodes))
            if no_progress_seconds is None
            else no_progress_seconds
        )
        # The backstop stays a backstop rather than becoming the discriminator:
        # it has to sit clear of the no-progress bound, which at 1280 nodes is
        # 1600s against this ceiling's historical 1800s.
        self.convergence_timeout = (
            max(CONVERGENCE_TIMEOUT_SECONDS, 3.0 * self.no_progress_seconds)
            if convergence_timeout is None
            else convergence_timeout
        )
        self.convergence_poll_seconds = convergence_poll_seconds

    def run(self, **validation_options: Any) -> dict[str, Any]:
        """Validate the cluster, allowing a bounded wait for it to converge.

        Only a `ConvergenceFailure` is retried: a node still joining reports a
        transient health such as ``loading`` until its initial sync completes.
        The health contract is unchanged - every node must still report
        ``online`` or ``healthy`` - so the validation is repeated until it holds
        for every node or the deadline expires.

        Every other semantic failure is permanent and raises immediately. A
        role, slot, identity or coverage mismatch will not resolve by looking
        again, so retrying it would only delay the report by the full deadline.

        The wait ends when the cluster stops making progress, not when a fixed
        total elapses. Progress is something *leaving* the pending set; a set
        that only grew has not made any. A total-time bound cannot separate a
        large cluster still working through its queue from one that is stuck,
        and at 200 nodes the two are minutes apart.

        A *retry* re-reads the cheap layer first, which the first observation
        does not. Measured on a real exact-200 formation, this wait made 77
        attempts over 156.7s and every one of them spent a whole-fleet
        200-node light round to reach a check that failed on three observers:
        the light validation passed 77 times out of 77 and layer 2 raised 77
        times out of 77, because what a freshly formed cluster is pending on is
        a replica an observer has not yet learned is online. §6.1 is what that
        state is visible in and it costs three `CLUSTER SHARDS`; §4.4 budgets
        the whole-fleet round at one per 60s and this wait was issuing one
        every 2.0s. The first attempt keeps the original order so that a
        permanent failure in either layer is still reported at once.
        """
        deadline = time.monotonic() + self.convergence_timeout
        attempts = 0
        last_progress = time.monotonic()
        previous: frozenset[str] | None = None
        previous_reason: str | None = None
        while True:
            attempts += 1
            try:
                return self._run_once(
                    cheap_layer_first=attempts > 1, **validation_options
                )
            except ConvergenceFailure as failure:
                now = time.monotonic()
                if self.convergence_timeout <= 0:
                    # A caller that owns the waiting asked for a single
                    # observation, so report what was seen as it was seen.
                    raise
                pending = failure.pending
                reason = str(failure)
                if pending:
                    # Something left the set, even if something else arrived.
                    if previous is None or (previous - pending):
                        last_progress = now
                    previous = pending
                elif reason != previous_reason:
                    # A convergence state that does not name what it is waiting
                    # for - a replica link still connecting, say. A changed
                    # reason is the only progress signal available there.
                    last_progress = now
                previous_reason = reason
                stalled = now - last_progress
                if stalled >= self.no_progress_seconds:
                    raise ConvergenceFailure(
                        f"cluster stopped converging: nothing left the pending set "
                        f"for {stalled:.0f}s over {attempts} validation attempts: "
                        f"{failure}",
                        pending=pending,
                    ) from failure
                if now >= deadline:
                    raise ConvergenceFailure(
                        f"cluster did not converge within "
                        f"{self.convergence_timeout:g}s over {attempts} validation "
                        f"attempts, still making progress when the ceiling was "
                        f"reached: {failure}",
                        pending=pending,
                    ) from failure
            time.sleep(self.convergence_poll_seconds)

    def _run_once(
        self, *, cheap_layer_first: bool = False, **validation_options: Any
    ) -> dict[str, Any]:
        allowed_unhealthy = set(
            validation_options.pop("allowed_unhealthy_node_ids", ())
        )
        expected_unavailable = set(
            validation_options.get("expected_unavailable", ())
        )

        def observe_light() -> dict[str, Any]:
            return self.light.run(**validation_options)

        def observe_topology() -> dict[str, Any]:
            return self.topology.run(
                expected_node_count=len(self.light.nodes),
                allowed_unhealthy_node_ids=allowed_unhealthy,
                excluded_observer_logical_ids=expected_unavailable,
            )

        # Both layers are still required and the accept condition is unchanged;
        # only which one is read first moves, and only while waiting. Reading
        # the three observers first means a whole-fleet round is spent when it
        # can still be the answer, rather than to reach a check that is already
        # known to be pending.
        if cheap_layer_first:
            topology = observe_topology()
            light = observe_light()
        else:
            light = observe_light()
            topology = observe_topology()
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
