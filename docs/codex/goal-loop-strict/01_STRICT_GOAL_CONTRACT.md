# 01_STRICT_GOAL_CONTRACT.md — Non-Negotiable Strict Goal Contract

## Objective

Extend `valkey-scale-lab` beyond the existing P15-P26 loop so it produces complete, runnable, strongly gated evidence for real 50/100/200-node Valkey cluster experiments and dry-run-only support above 200 nodes.

The product is not source code alone. The product is the combination of runnable implementation, fail-closed harness, schema-validated artifacts, quantitative analysis, visual report, fresh-context review, and stage-by-stage commits.

## Required real-scale coverage

The strict loop must cover exactly these real scales:

```text
50 nodes
100 nodes
200 nodes
```

For each real scale, the loop must cover:

```text
configuration validation
resource preflight
cluster planning
cluster creation and bootstrap
baseline workload
management operation matrix
fault/failover/partition/split-brain matrix
telemetry collection
workload impact analysis
report generation
cleanup verification
```

A stage cannot satisfy a real-scale requirement with a smaller cluster, fake Valkey, replayed logs, static generated metrics, or dry-run artifacts.

## Required 200+ support

For any target above 200 nodes, the project must support planning, resource estimation, scheduling, artifact schema generation, and report projection in dry-run mode only.

The strict loop must prove:

```text
no real containers above 200 are started
no real Valkey cluster above 200 is formed
no workload above 200 is run
all >200 artifacts are marked dry_run=true and execution_mode=dry_run
```

## Required management operation rows

Every real scale must cover these rows:

```text
create_cluster
meet_nodes
add_replica
remove_replica
remove_primary_drained_or_safe_replaced
remove_failed_node
reshard_slot_range
reshard_with_keys
rebalance_after_imbalance
rolling_restart_replica_first
rolling_restart_primary_safe
```

`PASS` means the operation was executed on a live Valkey cluster at the exact scale and independently verified. `SKIPPED_WITH_REASON` is not allowed for these required rows at 50/100/200 unless the current stage explicitly declares itself blocked and does not pass.

## Required fault/failover rows

Every real scale must cover these rows:

```text
primary_stop_failover
replica_stop
node_host_stop
az_stop
network_delay
network_loss
network_flap
network_partition
minority_partition
majority_partition
split_brain_window_detection
fault_period_workload_impact
```

Network faults must be scoped to owned containers or project-owned proxy layers. Host firewall, route, interface, or global OS network mutation is forbidden.

## Required quantitative evidence

Every real management and fault row must emit evidence for:

```text
real Valkey version and endpoint proof
topology before/during/after
slot ownership before/during/after
operation/fault event timeline
workload requested QPS and achieved QPS
latency p50/p90/p95/p99 and p99.9 or MISSING with reason
error counts by type
recovery and convergence durations
cleanup status
source artifact provenance
```

Missing values must be represented as `MISSING`, `SKIPPED_WITH_REASON`, or `UNSUPPORTED_WITH_REASON` with a reason field. Required real-scale metrics may not be silently omitted, set to `0`, or set to `null` to hide missing data.

## Required report quality

The final report must be comprehensive, readable, and visually correct. It must include:

```text
coverage heatmap for every required row and scale
management latency and convergence charts
failover latency curves for 50/100/200
fault impact charts and tables
workload QPS/latency/error comparisons
resource and cleanup summaries
missing-data table
source artifact provenance index
```

The report must not contain broken images, empty charts, `NaN`, `undefined`, stack traces, misleading zeroes, unresolved placeholders, or inconsistent table/chart counts.

## Completion definition

The strict loop is complete only when:

1. `codex/phase_manifest.json` contains P27-P40 in order.
2. `automatic_stop_after` is `P40_STRICT_FINAL_AUDIT_CLOSEOUT`.
3. `scripts/codex_gate.py next` returns no incomplete automatic stage after P40 is marked complete.
4. Every P27-P40 stage has context reload, design brief, worker summary, review, audit decision, completion record, gate result, and stage commit.
5. Every real 50/100/200 coverage cell is backed by real Valkey artifacts at the exact node count.
6. Every >200 support cell is dry-run-only with proof that no real runtime resources were created.
7. The final visual report passes a report quality gate.
8. P40 is committed and pushed.

## Blocking conditions

A stage is blocked, not complete, if any of the following is true:

```text
required Docker/runtime resource is unavailable
50/100/200 stage downshifts to a smaller node count
required real row is skipped
required metric is fabricated or silently omitted
fault injection mutates host networking
cleanup leaves owned resources without failing
review is missing or says Decision: FAIL
report has broken/misleading visual output
commit or push is attempted before postcheck and mark-complete
```

Blocked stages must write `artifacts/goal_loop_strict/<STAGE_ID>/BLOCKED.md` and must not run `mark-complete`.
