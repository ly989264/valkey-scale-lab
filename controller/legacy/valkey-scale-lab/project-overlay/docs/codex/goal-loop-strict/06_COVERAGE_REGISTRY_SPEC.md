# 06_COVERAGE_REGISTRY_SPEC.md — Coverage Registry and Scenario Compiler

## Purpose

The strict loop must turn the user goal into an explicit matrix. A matrix cell that is not represented cannot be verified. P28 must create a canonical coverage registry and scenario compiler that every later stage consumes.

## Coverage dimensions

Required dimensions:

```text
scale: 50 | 100 | 200 | >200_dry_run
category: lifecycle | management | fault | telemetry | analysis | report | cleanup
execution_mode: real | dry_run
stage_owner: P30-P40
```

## Required lifecycle rows per real scale

```text
config_validate
resource_preflight
plan_cluster
create_cluster
meet_nodes
assign_slots
add_replica
baseline_workload
telemetry_collect
analysis_build
report_render
cleanup_verify
```

## Required management rows per real scale

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

## Required fault rows per real scale

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

## Required >200 dry-run rows

For each configured dry-run target above 200, at minimum `201`, `250`, `300`, `500`, and `1000`, the registry must include:

```text
config_validate_dry_run
resource_preflight_dry_run
plan_cluster_dry_run
placement_schedule_dry_run
port_directory_collision_check_dry_run
artifact_schema_projection_dry_run
no_runtime_created_proof
report_projection_dry_run
```

The implementation may support additional dry-run sizes. It must not start real clusters above 200.

## Coverage ID format

Use deterministic IDs:

```text
<scale>.<category>.<row_name>
```

Examples:

```text
50.management.remove_replica
100.fault.network_delay
200.lifecycle.cleanup_verify
500.dry_run.no_runtime_created_proof
```

## Coverage registry artifact

P28 must define and later stages must update:

```text
artifacts/coverage/strict_coverage_registry.json
artifacts/coverage/strict_required_matrix.csv
artifacts/coverage/strict_scenario_plan.json
```

Required fields per coverage row:

```text
coverage_id
scale
node_count
category
row_name
stage_owner
required
execution_mode
status
status_reason
source_artifacts
validation_artifacts
metric_refs
cleanup_ref
review_ref
commit_sha
```

Allowed statuses:

```text
PENDING
PASS
FAIL
BLOCKED
DRY_RUN_PASS
MISSING
```

For real 50/100/200 required rows, `PENDING`, `MISSING`, `DRY_RUN_PASS`, and `SKIPPED_WITH_REASON` are not final pass states. P40 must fail if any required real row is not `PASS`.

For >200 rows, final pass state must be `DRY_RUN_PASS`, and the row must include no-runtime-created proof.

## Scenario compiler requirements

The scenario compiler must produce deterministic stage execution plans:

```text
management matrix plan for 50, 100, 200
fault/failover matrix plan for 50, 100, 200
full-flow E2E plan for 50, 100, 200
>200 dry-run plan
```

Each generated plan must include:

```text
node count
config path or generated config artifact
resource preflight requirement
workload profile
operation/fault sequence
timeout policy
cleanup policy
expected artifacts
coverage IDs satisfied by the run
```

## Coverage review rule

Every stage review must cite the coverage IDs it claims to satisfy. A review cannot pass with a vague statement such as “coverage looks good.”
