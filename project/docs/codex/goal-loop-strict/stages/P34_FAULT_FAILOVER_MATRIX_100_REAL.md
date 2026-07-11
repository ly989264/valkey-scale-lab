# P34_FAULT_FAILOVER_MATRIX_100_REAL — Real 100-Node Fault/Failover Matrix

## Purpose

Execute and quantify the complete fault, failover, partition, split-brain, and workload-impact matrix on a real 100-node Valkey cluster.

## Exact scale requirement

This stage must run exactly 100 real Valkey nodes. It must not downshift. If resource preflight cannot support 100 nodes, write `BLOCKED.md` and do not pass the stage.

## Required fault rows

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

`primary_stop_failover` must produce at least three independent real samples.

## Required artifacts

```text
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/phase_summary.json
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/valkey_e2e_evidence.json
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/resource_preflight.json
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/cluster_plan.json
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/run_state.json
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/cleanup_report.json
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/events.jsonl
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/metrics_timeseries.jsonl
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/workload_windows.json
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/quant_summary.json
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/coverage_ledger.json
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/fault_matrix_report.json
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/fault_operation_results.jsonl
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/failover_samples.jsonl
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/failover_latency_curve.json
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/partition_report.json
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/split_brain_report.json
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/fault_workload_impact.json
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/fault_topology_snapshots.jsonl
artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/fault_command_log.jsonl
```

## Required gates

```text
python3 scripts/assert_exact_scale_real_evidence.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL --nodes 100
python3 scripts/assert_fault_matrix_strict.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL --scale 100 --require-all-rows
python3 scripts/assert_failover_latency_curve.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL --scale 100 --min-samples 3
python3 scripts/assert_split_brain_report.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL --scale 100
python3 scripts/assert_quant_completeness.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL --category fault --scale 100
python3 scripts/assert_coverage_registry.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL --scale 100 --category fault
python3 scripts/assert_no_bypass.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL
python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/cleanup_report.json
```

## Pass criteria

This stage passes only when:

```text
resource preflight can_run=true
nodes_requested=100
nodes_observed=100
Valkey versions start with 9.1.
all required fault rows are PASS
primary_stop_failover has >=3 independent samples
network faults use container_netns_tc or sandbox_proxy
partition probes compare sides where feasible
split-brain detectors actually ran
workload impact is measured for every row
coverage registry rows for 100.fault.* are PASS
cleanup_report status is PASS
review says Decision: PASS
```

## Blocking conditions

```text
resource preflight fails
node count is not exactly 100
network fault needs host-level mutation
any required fault row is skipped or missing
failover sample count < 3
split_brain_window_ms=0 without detector evidence
required workload window missing
cleanup fails
```
