# 09_FAULT_FAILOVER_MATRIX_SPEC.md — Strict Fault, Failover, Partition, and Split-Brain Matrix

## Purpose

Fault behavior must be real, measured, exact-scale, and safe. Primary stop alone is not sufficient. Network faults must not mutate host networking.

## Required scales

Fault/failover rows must run at:

```text
50 nodes in P33_FAULT_FAILOVER_MATRIX_50_REAL
100 nodes in P34_FAULT_FAILOVER_MATRIX_100_REAL
200 nodes in P35_FAULT_FAILOVER_MATRIX_200_REAL
```

## Required rows

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

## Required failover sample policy

For `primary_stop_failover`, each scale must produce at least three independent real samples.

Each sample must record:

```text
coverage_id
scale
node_count
sample_id
target_primary_logical_id
target_primary_node_id
target_primary_az_id
target_primary_host_id
replica_candidates
fault_injected_at_ms
primary_unreachable_at_ms
replica_promoted_at_ms
cluster_state_ok_at_ms
slot_coverage_ok_at_ms
first_successful_read_at_ms
first_successful_write_at_ms
fault_cleared_at_ms
old_primary_rejoined_at_ms or MISSING with reason
promotion_latency_ms
cluster_recovery_latency_ms
read_unavailability_ms
write_unavailability_ms
split_brain_window_ms or MISSING with reason
workload_impact_ref
cleanup_ref
```

Reusing one generated value for multiple samples is forbidden.

## Required fault result fields

Every fault row must record:

```text
coverage_id
fault_type
fault_id
scale
node_count
scope
implementation_path
targets
fault_parameters
apply_started_at_ms
apply_completed_at_ms
observed_effect_started_at_ms
clear_started_at_ms
clear_completed_at_ms
recovery_completed_at_ms
expected_impact
observed_impact
safety_scope_verified
cleanup_verified
workload_impact_ref
topology_before_ref
topology_during_ref
topology_after_ref
source_evidence_ref
```

## Fault-specific requirements

### replica_stop

Must prove target role is replica before stop and that no unintended primary promotion is counted as success.

### node_host_stop

Logical host stop may map to local Docker container groups. It must stop all nodes assigned to one logical host through owned controls, record role/AZ/slot impact, measure workload impact, restore the host group, and verify cleanup.

### az_stop

Virtual AZ stop must target all nodes in an AZ from the plan, record minority/majority implications, measure recovery and split-brain indicators, and verify cleanup.

### network_delay

Must record delay, jitter, direction, target set, duration, implementation path, workload impact, and recovery. Acceptable paths:

```text
container_netns_tc
sandbox_proxy
```

If neither path is available, the stage is blocked. Do not pass with `unsupported` for required 50/100/200 rows.

### network_loss

Must record loss percentage, correlation if used, direction, target set, duration, implementation path, workload impact, and recovery.

### network_flap

Must record up/down cadence, iterations, target set, observed transitions, workload impact, and recovery.

### network_partition / minority_partition / majority_partition

Must record partition groups:

```text
majority: [logical_node_ids]
minority: [logical_node_ids]
isolated: [logical_node_ids]
block_between_groups: true
allow_within_group: true
```

Probes must compare both sides where feasible. Majority and minority availability must be measured separately.

### split_brain_window_detection

Must run detectors for:

```text
overlapping primary slot claims
divergent partition-side cluster views
conflicting successful writes
old primary accepts writes after new primary promotion
```

`split_brain_window_ms=0` is valid only when detectors ran and observed no indicator. It cannot mean “not implemented.”

## Required fault gates

Fault stages must include assertions equivalent to:

```text
assert_exact_scale_real_evidence --nodes <50|100|200>
assert_fault_matrix_strict --scale <50|100|200>
assert_failover_latency_curve --scale <50|100|200> --min-samples 3
assert_split_brain_report --scale <50|100|200>
assert_quant_completeness --category fault --scale <50|100|200>
assert_workload_impact --category fault --scale <50|100|200>
assert_cleanup --cleanup-report <path>
```
