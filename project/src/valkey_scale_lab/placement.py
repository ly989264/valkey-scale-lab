"""Which availability zone each member of a shard goes in, decided once.

Four modules used to answer this question independently: the planner
(`planner/plan.py`), the config validator's semantic node model
(`config/validation.py`), the resource preflight's (`resource.py`) and the
runtime that actually starts the fleet (`runtime/docker_runtime.py`). The first
three agreed with each other and the fourth did not, and at one replica per
shard - the only shape any run of this product has ever taken - all four
produce the same placement, so nothing ever disagreed out loud. At two or more
replicas they diverge, and the divergence is not cosmetic: the runtime is what
starts the nodes, so the executed topology would contradict the plan artifact
that the plan's own constraints were asserted against.

The policy here is the runtime's, kept because it is the one that satisfies the
two properties the operator stated on 2026-08-14 (see
`docs/multi_replica_support_map.md` §7.1):

  P1, per-shard balance - within one shard, the per-AZ member counts differ by
  at most one. Five members over two AZs is 3/2; over three AZs it is 2/2/1.

  P2, global balance - the cluster's total per-AZ node counts differ by at most
  one. `_az_balanced` in the planner already asserts this.

Both hold by construction rather than by search. A shard's members take the
`replicas_per_shard + 1` *consecutive* AZ indices starting at the shard's own,
and consecutive residues modulo the AZ count can never be more than one apart in
frequency, which is P1. Summing that window over every shard is what gives P2 -
exactly even when the AZ count divides the shard count, and off by at most one
otherwise, at any replica count. The all-replicas-opposite policy the planner
used instead cannot say the second of those: over two AZs its per-AZ skew for an
odd shard count is exactly `replicas_per_shard - 1`, which is why odd shard
counts at three or more replicas were refused outright.

What P1 buys over "every replica in the other AZ" is surviving copies. Losing
one AZ leaves every shard with at least two members under this policy; under the
opposite policy half the shards at four replicas are left holding exactly one.
It is not full-AZ availability - half of a cluster's primaries is not an
election majority under any placement - and it is not claimed to be.

At one replica per shard this function returns exactly what the planner's old
`_replica_az` returned, for two AZs and for three, which is what keeps every
existing run's placement byte-identical. That property is asserted by a test
rather than carried by this paragraph.
"""

from __future__ import annotations


def primary_az(azs: list[str], shard_index: int) -> str:
    """The AZ a shard's primary is placed in."""

    return azs[shard_index % len(azs)]


def replica_az(azs: list[str], shard_index: int, replica_index: int) -> str:
    """The AZ a shard's `replica_index`-th replica is placed in.

    Deliberately not a function of the primary's AZ: the members of a shard walk
    the AZ list from the shard's own index, so the placement is stated once and
    reads the same from the planner, the validator, the preflight and the
    runtime.
    """

    if len(azs) <= 1:
        return azs[0]
    return azs[(shard_index + replica_index + 1) % len(azs)]


def shard_az_balanced(nodes: list[dict[str, object]], azs: list[str]) -> bool:
    """P1: no shard's per-AZ member counts differ by more than one.

    Counted over the cluster's declared AZs, so an AZ a shard does not reach
    counts as zero. At one replica over two AZs this is exactly the old
    `primary_replica_distinct_az` property - a two-member shard is balanced only
    when its members are in different AZs - and at every replica count it
    implies at least one replica in an AZ other than the primary's, whenever
    there is more than one AZ to be in.
    """

    if len(azs) <= 1:
        return True
    by_shard: dict[str, list[str]] = {}
    for node in nodes:
        by_shard.setdefault(str(node["shard_id"]), []).append(str(node["az_id"]))
    for members in by_shard.values():
        counts = [sum(1 for az in members if az == candidate) for candidate in azs]
        if max(counts) - min(counts) > 1:
            return False
    return True
