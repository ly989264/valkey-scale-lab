from __future__ import annotations

from collections import Counter
from math import ceil
from typing import Any

NODEHOST_DENSITY_FIELDS = [
    "nodehost_strategy",
    "max_nodehosts",
    "nodehosts_per_az",
    "max_logical_nodes_per_nodehost",
    "actual_nodehost_count",
    "logical_nodes_per_nodehost",
    "nodehost_distribution",
]


class NodehostDensityError(ValueError):
    pass


def density_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    runtime = config.get("runtime", {})
    return {
        "nodehost_strategy": str(runtime.get("nodehost_strategy", "density_limited")),
        "max_nodehosts": int(runtime.get("max_nodehosts", 64)),
        "nodehosts_per_az": int(runtime.get("nodehosts_per_az", 2)),
        "max_logical_nodes_per_nodehost": int(runtime.get("max_logical_nodes_per_nodehost", 25)),
        "nodehost_distribution": str(runtime.get("nodehost_distribution", "round_robin_by_az")),
    }


def build_nodehost_density_plan(
    *,
    config: dict[str, Any],
    nodes: list[dict[str, Any]],
    run_id: str,
    assign: bool = False,
    default_host_id: str = "local",
    fleet_hosts: list[dict[str, Any]] | None = None,
    runtime_type: str = "docker_process",
) -> dict[str, Any]:
    """Plan which logical nodes live on which nodehost, and where each nodehost is.

    `fleet_hosts` places the plan on a real fleet. Without it nothing changes and
    `host_id` stays `default_host_id`, which is every Docker run: the nodehosts
    are all on the machine this runs from and there is nothing to join.

    Placement is planning rather than the backend's, and an artifact settles it:
    `nodehost_density_plan.json` is written before any nodehost is started, so a
    backend that chose the hosts would leave that artifact claiming `host_id:
    "local"` for a run that placed its nodehosts on named hosts. See
    `project/docs/native_backend_slice_map.md` §6.2.
    """
    density = density_runtime_config(config)
    strategy = density["nodehost_strategy"]
    distribution = density["nodehost_distribution"]
    max_nodehosts = density["max_nodehosts"]
    nodehosts_per_az = density["nodehosts_per_az"]
    max_per_nodehost = density["max_logical_nodes_per_nodehost"]
    if strategy != "density_limited":
        raise NodehostDensityError(f"unsupported runtime.nodehost_strategy: {strategy}")
    if distribution != "round_robin_by_az":
        raise NodehostDensityError(f"unsupported runtime.nodehost_distribution: {distribution}")
    if max_nodehosts < 1:
        raise NodehostDensityError("runtime.max_nodehosts must be at least 1")
    if nodehosts_per_az < 1:
        raise NodehostDensityError("runtime.nodehosts_per_az must be at least 1")
    if max_per_nodehost < 1:
        raise NodehostDensityError("runtime.max_logical_nodes_per_nodehost must be at least 1")

    az_order = _active_az_order(config, nodes)
    by_az = {az: _nodes_for_az(nodes, az) for az in az_order}
    replicas_per_shard = int(config.get("cluster", {}).get("replicas_per_shard", 0) or 0)
    # How many fault domains one AZ must offer for a shard's members to be able
    # to sit on distinct ones: the largest number of that shard's members the AZ
    # holds, which under the placement policy is `ceil((replicas + 1) / AZs)`.
    # This used to be computed only for the single-AZ case, where it reads
    # `replicas + 1` - the same expression at one AZ - and multi-AZ was left at 1
    # because at one replica per shard a shard never has two members in one AZ.
    # At four replicas over two AZs it is 3, and stating it here is what lets the
    # refusal below name a number that is both necessary and sufficient.
    min_fault_domains = _min_fault_domains_per_az(replicas_per_shard, len(az_order))
    min_per_az = max(nodehosts_per_az, min_fault_domains)
    safe_run = run_id.lower().replace("_", "-")
    nodehosts: list[dict[str, Any]] = []
    logical_nodes_per_nodehost: dict[str, int] = {}
    client_ports_per_nodehost: dict[str, list[int]] = {}

    for az in az_order:
        hosted = by_az[az]
        count = len(hosted)
        if count == 0:
            continue
        requested_for_az = max(min_per_az, ceil(count / max_per_nodehost))
        for index in range(requested_for_az):
            nodehost_id = f"nodehost-{az}-{index:02d}"
            nodehosts.append(
                {
                    "nodehost_id": nodehost_id,
                    "az_id": az,
                    "host_id": default_host_id,
                    "ordinal": len(nodehosts),
                    "container_name": f"vslab-{safe_run}-{nodehost_id}",
                    "ports": [],
                    "logical_node_count": 0,
                }
            )
            logical_nodes_per_nodehost[nodehost_id] = 0
        az_nodehosts = nodehosts[-requested_for_az:]
        ordered = sorted(hosted, key=lambda item: int(item.get("ordinal", 0)))
        for node, target in zip(ordered, _assign_within_az(ordered, az_nodehosts)):
            target["logical_node_count"] += 1
            target["ports"].extend([int(node["client_port"]), int(node["cluster_bus_port"])])
            # Kept apart from `ports` above, which mixes both. Only the client
            # ports are ones the controller dials; the cluster bus is peer
            # traffic on the fleet's own data network, and a host's published
            # client range says nothing about it.
            client_ports_per_nodehost.setdefault(str(target["nodehost_id"]), []).append(
                int(node["client_port"])
            )
            logical_nodes_per_nodehost[str(target["nodehost_id"])] += 1
            if assign:
                node["runtime_type"] = runtime_type
                node["nodehost_id"] = target["nodehost_id"]
                node["nodehost_container_name"] = target["container_name"]

    actual_count = len(nodehosts)
    if actual_count > max_nodehosts:
        raise NodehostDensityError(f"requested nodehost count {actual_count} exceeds max_nodehosts {max_nodehosts}")
    over_limit = {
        nodehost_id: count
        for nodehost_id, count in logical_nodes_per_nodehost.items()
        if count > max_per_nodehost
    }
    if over_limit:
        raise NodehostDensityError(f"logical nodes per nodehost exceed max {max_per_nodehost}: {over_limit}")
    unsafe = _colliding_shard(nodes)
    if unsafe is not None:
        shard_id, shared = unsafe
        raise NodehostDensityError(
            f"shard {shard_id} has more than one member on nodehost {shared}: "
            f"a shard of {replicas_per_shard + 1} members over {len(az_order)} AZ(s) "
            f"needs at least {min_fault_domains} nodehost(s) in each AZ, and "
            f"runtime.nodehosts_per_az is {nodehosts_per_az}"
        )

    for nodehost in nodehosts:
        nodehost["ports"] = sorted(set(int(port) for port in nodehost["ports"]))
        nodehost["logical_node_count"] = int(logical_nodes_per_nodehost[str(nodehost["nodehost_id"])])

    if fleet_hosts is not None:
        _place_nodehosts_on_fleet(
            nodehosts,
            fleet_hosts,
            assign=assign,
            nodes=nodes,
            client_ports_per_nodehost=client_ports_per_nodehost,
        )

    density_evidence = {
        **density,
        "actual_nodehost_count": actual_count,
        "logical_nodes_per_nodehost": dict(sorted(logical_nodes_per_nodehost.items())),
        "nodehost_count_by_az": dict(sorted(Counter(item["az_id"] for item in nodehosts).items())),
        "node_count": len(nodes),
    }
    return {
        "schema_version": "v1",
        "artifact_type": "nodehost_density_plan",
        "status": "PASS",
        "run_id": run_id,
        "nodehost_density": density_evidence,
        **density_evidence,
        "nodehosts": nodehosts,
    }


def _place_nodehosts_on_fleet(
    nodehosts: list[dict[str, Any]],
    fleet_hosts: list[dict[str, Any]],
    *,
    assign: bool,
    nodes: list[dict[str, Any]],
    client_ports_per_nodehost: dict[str, list[int]],
) -> None:
    """Join planned nodehosts to fleet hosts, one nodehost per host.

    **One per host, and a refusal otherwise.** A nodehost is a fault domain here:
    the check above rejects a plan where a shard's primary and replica share one,
    and the fault actuator suspends or isolates a whole nodehost. Under Docker
    each is its own container, so nodehost and fault domain coincide by
    construction; on a fleet they coincide only if the placement makes them. Two
    nodehosts on one host would let a host-scoped fault take out a domain the
    plan believed was independent, and the fault evidence would then describe
    something that never held. See `native_backend_slice_map.md` §3.

    The second refusal is the port range. A host states which ports it will serve
    as one contiguous range, the way a real host states a security group; the
    run's port base is chosen by configuration that has never seen the fleet. A
    run whose ports fall outside would form a cluster the controller cannot
    reach - the failure `NodeBackend.client_host` warns about - so it is refused
    with both the range and the offending ports named.
    """
    available: dict[str, list[dict[str, Any]]] = {}
    for host in fleet_hosts:
        available.setdefault(str(host["az_id"]), []).append(host)
    for hosts in available.values():
        hosts.sort(key=lambda item: str(item["host_id"]))

    taken: dict[str, str] = {}
    for nodehost in sorted(nodehosts, key=lambda item: int(item["ordinal"])):
        az_id = str(nodehost["az_id"])
        candidates = available.get(az_id, [])
        placed = [host for host in candidates if str(host["host_id"]) not in taken]
        if not placed:
            raise NodehostDensityError(
                f"the fleet has no unused host in {az_id!r} for nodehost "
                f"{nodehost['nodehost_id']}: a native run places exactly one nodehost per host, "
                f"and {az_id!r} offers {len(candidates)} host(s) for "
                f"{sum(1 for item in nodehosts if str(item['az_id']) == az_id)} nodehost(s)"
            )
        host = placed[0]
        taken[str(host["host_id"])] = str(nodehost["nodehost_id"])

        outside = sorted(
            port
            for port in client_ports_per_nodehost.get(str(nodehost["nodehost_id"]), [])
            if not int(host["client_port_first"]) <= int(port) <= int(host["client_port_last"])
        )
        if outside:
            raise NodehostDensityError(
                f"host {host['host_id']} serves ports "
                f"{host['client_port_first']}-{host['client_port_last']} and nodehost "
                f"{nodehost['nodehost_id']} needs {outside[:8]}"
            )

        nodehost["host_id"] = str(host["host_id"])
        nodehost["host_control_endpoint"] = dict(host["control_endpoint"])
        nodehost["host_data_address"] = str(host["data_address"])
        nodehost["host_client_address"] = str(host["client_address"])
        # Which fleet, and which manifest of it. Recorded here because placement
        # is the only step that sees both the plan and the manifest, and carried
        # into the run's host evidence so that a native result is attributable to
        # the fleet it was taken on. What that fleet *was* is not recorded and
        # cannot be - see `cross_host_evidence_slice_map.md` §8.
        if host.get("fleet_id"):
            nodehost["fleet_id"] = str(host["fleet_id"])
        if host.get("fleet_manifest_sha256"):
            nodehost["fleet_manifest_sha256"] = str(host["fleet_manifest_sha256"])

    if assign:
        host_by_nodehost = {str(item["nodehost_id"]): str(item["host_id"]) for item in nodehosts}
        for node in nodes:
            nodehost_id = str(node.get("nodehost_id", ""))
            if nodehost_id in host_by_nodehost:
                node["host_id"] = host_by_nodehost[nodehost_id]


def extract_density_evidence(obj: dict[str, Any]) -> dict[str, Any]:
    if isinstance(obj.get("nodehost_density"), dict):
        return dict(obj["nodehost_density"])
    runtime = obj.get("runtime") if isinstance(obj.get("runtime"), dict) else {}
    source: dict[str, Any] = {}
    for container in [obj, runtime]:
        for field in NODEHOST_DENSITY_FIELDS:
            if field in container and field not in source:
                source[field] = container[field]
    if "actual_nodehost_count" not in source and isinstance(obj.get("nodehosts"), list):
        source["actual_nodehost_count"] = len(obj["nodehosts"])
    if "logical_nodes_per_nodehost" not in source and isinstance(obj.get("nodehosts"), list):
        source["logical_nodes_per_nodehost"] = {
            str(item.get("nodehost_id")): int(item.get("logical_node_count", 0) or 0)
            for item in obj["nodehosts"]
            if isinstance(item, dict)
        }
    return source


def _active_az_order(config: dict[str, Any], nodes: list[dict[str, Any]]) -> list[str]:
    configured = list(config.get("network", {}).get("azs", []))
    observed = [str(node.get("az_id")) for node in nodes if node.get("az_id")]
    order: list[str] = []
    for az in configured + observed:
        if az and az not in order and any(str(node.get("az_id")) == az for node in nodes):
            order.append(az)
    return order


def _nodes_for_az(nodes: list[dict[str, Any]], az: str) -> list[dict[str, Any]]:
    return [node for node in nodes if str(node.get("az_id")) == az]


def _assign_within_az(
    ordered: list[dict[str, Any]], az_nodehosts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Choose a nodehost for each of one AZ's logical nodes.

    The assignment is round-robin over the AZ's nodehosts by position in the
    ordinal-sorted list, which is what this has always done and what every
    frozen baseline records. It is safe as long as no shard has more than one
    member in this AZ, because then two members of a shard are never at two
    positions of the same list.

    At two or more replicas per shard a shard does have several members in one
    AZ, and their positions are not adjacent: the runtime and the validator both
    order every primary before every replica, so a shard's primary sits in the
    leading block and its same-AZ replicas far down the tail, and whether the
    two collide is a question about where the stride happens to land rather
    than about how many nodehosts there are. Measured at ten shards with four replicas: the
    positional assignment puts a shard's primary and one of its replicas on one
    nodehost at *every* value of `nodehosts_per_az` from 1 to 16, so more
    fault domains do not help and the refusal below could not be escaped.

    So where the positional assignment would do that, the AZ's nodes are walked
    a shard at a time instead, each shard's members taking consecutive nodehosts
    from a running cursor. That makes a shard's members distinct whenever the AZ
    has at least as many nodehosts as the shard has members in it - the minimum
    `min_fault_domains` now states - and keeps the per-nodehost counts within
    one of each other, because the cursor never rewinds.

    Chosen only where the positional assignment fails, rather than always, so
    that a plan which can be made the way it always was still is: that is what
    makes this change nothing at all on the one-replica shape every existing
    run and both frozen baselines were taken at.
    """

    positional = [
        az_nodehosts[offset % len(az_nodehosts)] for offset in range(len(ordered))
    ]
    if _shard_members_distinct(ordered, positional):
        return positional

    by_shard: dict[str, list[int]] = {}
    for index, node in enumerate(ordered):
        by_shard.setdefault(str(node.get("shard_id")), []).append(index)
    grouped: list[dict[str, Any] | None] = [None] * len(ordered)
    cursor = 0
    for indexes in by_shard.values():
        for offset, index in enumerate(indexes):
            grouped[index] = az_nodehosts[(cursor + offset) % len(az_nodehosts)]
        cursor += len(indexes)
    return [target for target in grouped if target is not None]


def _shard_members_distinct(
    ordered: list[dict[str, Any]], targets: list[dict[str, Any]]
) -> bool:
    seen: dict[str, set[str]] = {}
    for node, target in zip(ordered, targets):
        shard_id = str(node.get("shard_id"))
        nodehost_id = str(target["nodehost_id"])
        if nodehost_id in seen.setdefault(shard_id, set()):
            return False
        seen[shard_id].add(nodehost_id)
    return True


def _min_fault_domains_per_az(replicas_per_shard: int, az_count: int) -> int:
    """The nodehosts one AZ must offer for one shard's members to be distinct."""

    if replicas_per_shard <= 0:
        return 1
    return ceil((replicas_per_shard + 1) / max(az_count, 1))


def _colliding_shard(nodes: list[dict[str, Any]]) -> tuple[str, str] | None:
    """The first shard with two members on one nodehost, and that nodehost.

    Names them, because the previous refusal named neither the shard, the
    nodehost, the shard shape nor the knob that governs it - and at more than one
    replica per shard the knob is the whole content of the answer.
    """

    by_shard: dict[str, dict[str, int]] = {}
    for node in nodes:
        nodehost_id = node.get("nodehost_id")
        if not nodehost_id:
            continue
        counts = by_shard.setdefault(str(node.get("shard_id")), {})
        counts[str(nodehost_id)] = counts.get(str(nodehost_id), 0) + 1
    for shard_id in sorted(by_shard):
        for nodehost_id, count in sorted(by_shard[shard_id].items()):
            if count > 1:
                return shard_id, nodehost_id
    return None
