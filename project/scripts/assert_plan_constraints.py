#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--max-nodes", type=int, default=100)
    parser.add_argument("--allow-opt-in-1000", action="store_true")
    parser.add_argument("--require-dry-run", action="store_true")
    args = parser.parse_args()
    path = Path(args.plan)
    if not path.exists():
        print(f"plan missing: {path}", file=sys.stderr)
        return 1
    plan = load(path)
    errors: list[str] = []
    nodes = plan.get("nodes", [])
    node_count = int(plan.get("node_count", len(nodes)))
    constraints = plan.get("constraints", {})
    if node_count != len(nodes):
        errors.append(f"node_count mismatch: node_count={node_count}, len(nodes)={len(nodes)}")
    if node_count > args.max_nodes:
        if not args.allow_opt_in_1000:
            errors.append(f"node_count {node_count} exceeds max {args.max_nodes} without opt-in")
        if not constraints.get("opt_in_1000"):
            errors.append("node_count exceeds max but constraints.opt_in_1000 is not true")
    if args.require_dry_run and not constraints.get("dry_run"):
        errors.append("dry-run plan required but constraints.dry_run is not true")
    if constraints.get("default_node_cap") != 100:
        errors.append("constraints.default_node_cap must be 100")
    if constraints.get("shard_az_balanced") is not True:
        errors.append("constraints.shard_az_balanced must be true")

    for field in ["logical_id", "container_name", "data_dir", "log_dir"]:
        values = [n.get(field) for n in nodes if n.get(field)]
        duplicates = [v for v, count in Counter(values).items() if count > 1]
        if duplicates:
            errors.append(f"duplicate {field}: {duplicates[:5]}")

    ports_by_host: dict[str, list[int]] = defaultdict(list)
    for n in nodes:
        host = n.get("host_id")
        for key in ["client_port", "cluster_bus_port"]:
            port = n.get(key)
            if port is not None:
                ports_by_host[host].append(int(port))
    for host, ports in ports_by_host.items():
        duplicates = [p for p, count in Counter(ports).items() if count > 1]
        if duplicates:
            errors.append(f"host {host}: duplicate ports {duplicates[:10]}")

    az_ids = sorted({n.get("az_id") for n in nodes if n.get("az_id")})
    by_shard: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        by_shard[n.get("shard_id", "")].append(n)
    for shard, shard_nodes in by_shard.items():
        primaries = [n for n in shard_nodes if n.get("role") == "primary"]
        replicas = [n for n in shard_nodes if n.get("role") == "replica"]
        if len(primaries) != 1:
            errors.append(f"shard {shard}: expected exactly 1 primary, got {len(primaries)}")
            continue
        # P1, per-shard AZ balance: a shard's members are spread evenly over the
        # AZs, so its per-AZ counts differ by at most one. At one replica over
        # two AZs this is the old "replica is not in the primary's AZ" check; at
        # four replicas it is 3/2, and a check demanding distinct AZs would call
        # the placement the runtime actually starts a violation.
        member_counts = Counter(n.get("az_id") for n in shard_nodes)
        for az in az_ids:
            member_counts.setdefault(az, 0)
        if member_counts and max(member_counts.values()) - min(member_counts.values()) > 1:
            errors.append(f"shard {shard}: AZ placement is not balanced across the shard: {dict(member_counts)}")
        if len(replicas) == 1:
            azs = {n.get("az_id") for n in shard_nodes}
            if len(azs) != 2:
                errors.append(f"shard {shard}: 1 primary + 1 replica must occupy exactly 2 AZs, got {sorted(azs)}")

    az_counts = Counter(n.get("az_id") for n in nodes)
    if len(az_counts) > 1 and max(az_counts.values()) - min(az_counts.values()) > 1:
        errors.append(f"AZ placement is not balanced: {dict(az_counts)}")

    runtime = plan.get("runtime", {})
    if runtime.get("network_mode") == "host":
        errors.append("runtime.network_mode=host is forbidden")

    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS plan_constraints nodes={node_count} plan={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
