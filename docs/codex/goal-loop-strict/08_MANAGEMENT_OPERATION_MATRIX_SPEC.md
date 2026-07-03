# 08_MANAGEMENT_OPERATION_MATRIX_SPEC.md — Strict Management Operation Matrix

## Purpose

Management operations must be real, measured, and exact-scale. A static matrix, simulated Valkey, or small-cluster extrapolation is not sufficient for P30-P32.

## Required scales

Management matrix rows must run at:

```text
50 nodes in P30_MANAGEMENT_MATRIX_50_REAL
100 nodes in P31_MANAGEMENT_MATRIX_100_REAL
200 nodes in P32_MANAGEMENT_MATRIX_200_REAL
```

The node count in evidence must equal the stage scale exactly.

## Required rows

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

## Required operation result fields

Every operation row must record:

```text
coverage_id
operation_name
operation_id
scale
node_count
operation_status
status_reason
started_at_unix_ms
ended_at_unix_ms
wall_ms
prepare_ms
command_ms
convergence_ms
cleanup_ms
cluster_state_before
cluster_state_after
cluster_known_nodes_before
cluster_known_nodes_after
cluster_slots_assigned_before
cluster_slots_assigned_after
cluster_slots_ok_before
cluster_slots_ok_after
slots_before
slots_after
slots_moved
keys_moved
bytes_migrated or MISSING with reason
slot_balance_before
slot_balance_after
workload_window_ref
errors_by_type
topology_before_ref
topology_after_ref
command_log_ref
source_evidence_ref
```

## Status semantics

```text
PASS: operation executed on live Valkey at exact scale and all verification checks passed
FAIL: operation was attempted but did not satisfy verification
BLOCKED: resource/safety/runtime blocker prevented execution; stage must not pass
SKIPPED_WITH_REASON: not allowed for required real-scale rows in P30-P32
```

## Operation-specific requirements

### remove_replica

Must prove:

```text
target role before operation is replica
cluster forget/remove path recorded
removed node absent from CLUSTER NODES after convergence
slot coverage remains complete
workload read/write path remains valid
cleanup removes stopped/removed runtime resources
```

### remove_primary_drained_or_safe_replaced

Must prove:

```text
target role before operation is primary
owned slots are drained/moved or a safe replacement path is executed
no slot remains orphaned
cluster views converge
workload impact is measured through operation and recovery windows
```

### remove_failed_node

Must prove:

```text
fault applied through project-owned controls
target failure visible to cluster probes
metadata cleanup is performed safely
cluster recovers or records real failure
fault is cleared or node is intentionally removed
cleanup passes
```

### reshard_slot_range

Must prove:

```text
source and target primaries identified from live topology
explicit slot range selected and recorded
moved slot count > 0
slot ownership before/after recorded
MOVED/ASK/error telemetry collected
convergence latency measured
```

### reshard_with_keys

Must prove:

```text
keys exist in moved slots before movement
reads succeed after movement
writes succeed after convergence
key movement evidence is recorded
```

### rebalance_after_imbalance

Must prove:

```text
initial imbalance exists or is intentionally created
imbalance metric is declared
rebalance reduces imbalance
before/after slot distribution recorded per primary
data path verifies after rebalance
workload impact is measured
```

### rolling_restart_replica_first

Must prove:

```text
restart order deterministic and recorded
replicas restart before primaries
health gate passes between nodes or stage fails
one node or safe batch at a time
workload impact measured
cleanup verifies no stale containers/processes
```

### rolling_restart_primary_safe

Must prove:

```text
primary restart path is safe and recorded
promotion/unavailability/recovery measured if failover occurs
cluster returns to target state
workload impact measured
cleanup passes
```

## Required management gates

Management stages must include assertions equivalent to:

```text
assert_exact_scale_real_evidence --nodes <50|100|200>
assert_management_matrix_strict --scale <50|100|200>
assert_quant_completeness --category management --scale <50|100|200>
assert_workload_impact --category management --scale <50|100|200>
assert_cleanup --cleanup-report <path>
```
