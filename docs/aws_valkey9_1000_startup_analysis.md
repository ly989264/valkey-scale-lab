# AWS Valkey 9 1000-Node Startup Mapping

This note maps the Valkey 9 1000-node public benchmark startup pattern to the local
lab runtime while preserving the repository safety rules.

## Adopted Pattern

- Start all Valkey processes first with `cluster-enabled yes`.
- Place each virtual AZ in one owned Docker nodehost container.
- Run each Valkey node as an isolated process inside its AZ nodehost, with a unique
  client port, cluster bus port, data directory, log file, and PID file.
- After all processes respond to `PING`, use cluster bus `CLUSTER MEET` commands to
  form cluster membership. No workload `SET` or `GET` traffic is sent before cluster
  formation completes.
- Assign all 16384 slots to primaries after primary membership converges.
- Meet replicas after slot assignment, then bind each replica to its shard primary
  with `CLUSTER REPLICATE`.

## Rejected Host-Level Optimizations

The AWS benchmark environment uses host-level performance tuning that is outside this
lab's safety boundary. The local lab must not run or emulate:

- IRQ affinity changes.
- CPU shield or physical core isolation.
- `ethtool` changes.
- `systemctl` service changes.
- `sudo` network, route, firewall, or interface commands.
- host-level `ulimit` or system-wide process limit changes.

All runtime changes remain scoped to owned Docker containers, owned Docker networks,
and Valkey processes inside those containers.

## Virtual AZ Contract

Multi-AZ configs now require exactly two virtual AZs. With one replica per shard, the
planner alternates primaries across the two AZs and always places the replica in the
opposite AZ:

- shard N primary: `az-a` when N is even, `az-b` when N is odd.
- shard N replica: the other AZ.

This creates two Docker nodehosts for scale scenarios:

- `nodehost-az-a`
- `nodehost-az-b`

The 1000-node profile remains dry-run only unless the existing opt-in guard is present.
Default automatic phases remain capped at 100 nodes.
