# P30_MANAGEMENT_MATRIX_50_REAL — Real 50-Node Management Matrix

## Purpose

Execute and quantify the complete management operation matrix on a real 50-node Valkey cluster.

## Exact scale requirement

This stage must run exactly 50 real Valkey nodes. It must not downshift. If resource preflight cannot support 50 nodes, write `BLOCKED.md` and do not pass the stage.

## Required management rows

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

Each row must update the coverage registry with a `PASS` only when the row executed on the real 50-node cluster and all verification checks passed.

## Required artifacts

```text
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/phase_summary.json
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/valkey_e2e_evidence.json
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/resource_preflight.json
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/cluster_plan.json
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/run_state.json
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/cleanup_report.json
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/events.jsonl
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/metrics_timeseries.jsonl
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/workload_windows.json
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/quant_summary.json
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/coverage_ledger.json
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/management_ops_matrix.json
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/management_operation_results.jsonl
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/management_topology_snapshots.jsonl
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/management_command_log.jsonl
artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/management_workload_impact.json
```

## Required gates

```text
python3 scripts/assert_exact_scale_real_evidence.py --phase P30_MANAGEMENT_MATRIX_50_REAL --nodes 50
python3 scripts/assert_management_matrix_strict.py --phase P30_MANAGEMENT_MATRIX_50_REAL --scale 50 --require-all-rows
python3 scripts/assert_quant_completeness.py --phase P30_MANAGEMENT_MATRIX_50_REAL --category management --scale 50
python3 scripts/assert_coverage_registry.py --phase P30_MANAGEMENT_MATRIX_50_REAL --scale 50 --category management
python3 scripts/assert_no_bypass.py --phase P30_MANAGEMENT_MATRIX_50_REAL
python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/cleanup_report.json
```

## Pass criteria

This stage passes only when:

```text
resource preflight can_run=true
nodes_requested=50
nodes_observed=50
Valkey versions start with 9.1.
all required management rows are PASS
all row source artifacts exist
workload impact is measured for every row
telemetry artifacts validate
coverage registry rows for 50.management.* are PASS
cleanup_report status is PASS
review says Decision: PASS
```

## Blocking conditions

```text
resource preflight fails
node count is not exactly 50
any required management row is skipped or missing
any required metric is null/NaN/omitted
operation result is synthetic or replayed
cleanup fails
```
