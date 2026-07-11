# 07_MANAGEMENT_OPS_SPEC.md — Management Operation Matrix

## Purpose

This document defines what “remove/reshard/rebalance/rolling restart are complete” means. A stage is incomplete if it only provides CLI placeholders, generated static artifacts, or fake-only tests.

## Operation matrix rows

The final management matrix must include at least these rows:

| Operation | Required stage | Node counts | Required status semantics |
|---|---|---:|---|
| create_cluster | existing/P16 evidence | 6+ | Must pass as setup evidence. |
| meet_nodes | existing/P16 evidence | 6+ | Must pass as setup evidence. |
| add_replica | existing/P16 evidence | 6+ | Must pass or be inherited with real evidence. |
| remove_replica | P17 | 6, 10 | Must execute and verify cluster forget/convergence. |
| remove_primary_drained | P17 | 6, 10 | Must drain/migrate slots before removal or use a documented safe replacement path. |
| remove_failed_node | P17 | 6, 10 | Must fault/stop a node and remove it from cluster metadata safely. |
| reshard_slot_range | P18 | 6, 10 | Must move an explicit slot range and verify ownership/data path. |
| reshard_with_keys | P18 | 6, 10 | Must move slots containing keys and verify reads/writes after movement. |
| rebalance_after_imbalance | P18 | 6, 10 | Must intentionally create or detect imbalance and reduce it. |
| rolling_restart_replica_first | P19 | 6, 10 | Must restart replicas before primaries with health gates between nodes. |
| rolling_restart_primary_safe | P19 | 6, 10 | Must restart primaries through a safe path and quantify unavailability. |

Scale phases and final reports should include management summaries for 30/50/100 when those clusters exist. Do not block P17-P19 solely on large-scale management if their stage doc only requires 6/10 nodes.

## Remove node semantics

### Remove replica

A replica removal passes only when:

- the target is a replica before removal;
- the removal command path is recorded;
- the removed node is absent from `CLUSTER NODES` views after convergence;
- cluster slot coverage remains complete;
- workload read/write path remains valid;
- cleanup removes the container/process.

### Remove primary with slot drain

A primary removal passes only when:

- the target is a primary before removal;
- slots owned by the primary are moved or otherwise safely reassigned before final removal;
- cluster views converge to full slot coverage;
- no slot remains orphaned;
- workload impact is measured across operation windows.

If Valkey cannot support a safe remove-primary path in the current implementation, the operation must be `FAIL` or `SKIPPED_WITH_REASON` only if the stage gate explicitly allows that skip. The goal-loop default is that P17 must implement a real safe path.

### Remove failed node

Failed-node removal passes only when:

- the target fault is applied through the project fault API or owned runtime control;
- the failure is visible to cluster probes;
- metadata cleanup is performed safely;
- the cluster recovers or the stage records a real failure;
- cleanup clears the fault and owned resources.

## Reshard semantics

Resharding passes only when:

- source and target primaries are identified from live cluster topology;
- slot ownership before and after is recorded;
- moved slot count is greater than zero;
- keys in moved slots remain readable after movement;
- writes to moved slots succeed after convergence;
- ASK/MOVED redirections are counted during operation;
- convergence latency is measured.

The implementation may use `valkey-cli --cluster` or direct cluster commands, but the artifact must record the command path.

## Rebalance semantics

Rebalance passes only when:

- the cluster starts from a measurable slot imbalance or a node-add condition;
- the rebalance operation reduces imbalance according to a declared metric;
- balance before/after is recorded per primary;
- data-path verification passes after rebalance;
- workload impact is measured.

A no-op rebalance may pass only if the stage explicitly includes a no-op row and the report says `SKIPPED_WITH_REASON` or `PASS_NOOP_VERIFIED` with a reason. It cannot replace the required imbalance-reducing row.

## Rolling restart semantics

Rolling restart passes only when:

- restart order is deterministic and recorded;
- only one node or one safe batch is restarted at a time;
- cluster health gate passes before proceeding to the next node;
- replicas are restarted before primaries by default;
- primary restart path measures promotion, unavailability, and recovery if failover occurs;
- workload QPS/latency/error deltas are measured during restart windows;
- cleanup verifies no stale containers/processes.

## Required management artifacts

Each management stage must emit:

```text
management_ops_matrix.json
management_operation_results.jsonl
management_workload_impact.json
management_topology_snapshots.jsonl
management_command_log.jsonl
```

These artifacts must be schema-validated and referenced by `quant_summary.json`.

## Required tests

Unit/integration tests must cover:

- operation status taxonomy;
- missing metric encoding;
- topology before/after comparison;
- slot coverage invariants;
- workload window aggregation;
- failure handling and cleanup.

Real gates must cover at least one live Valkey execution per required operation row.
