# 07_QUANTIFICATION_DATA_CONTRACT.md — Quantitative Data Contract

## Purpose

Every management and fault behavior must be analyzable from machine-readable artifacts. Reports must never scrape logs or infer missing values from chart output.

## Required artifact families

Every real stage P30-P36 must emit:

```text
phase_summary.json
valkey_e2e_evidence.json
resource_preflight.json
cluster_plan.json
run_state.json
cleanup_report.json
events.jsonl
metrics_timeseries.jsonl
workload_windows.json
quant_summary.json
coverage_ledger.json
```

Management stages must emit:

```text
management_ops_matrix.json
management_operation_results.jsonl
management_topology_snapshots.jsonl
management_command_log.jsonl
management_workload_impact.json
```

Fault stages must emit:

```text
fault_matrix_report.json
fault_operation_results.jsonl
failover_samples.jsonl
failover_latency_curve.json
partition_report.json
split_brain_report.json
fault_workload_impact.json
fault_topology_snapshots.jsonl
fault_command_log.jsonl
```

Analysis/report stages must emit:

```text
cross_scale_analysis_summary.json
coverage_heatmap_table.csv
management_latency_table.csv
fault_impact_table.csv
failover_curve_table.csv
missing_data_table.csv
report_index.json
report_quality_report.json
```

## Time model

Use both wall-clock and monotonic time:

```text
started_at_unix_ms
ended_at_unix_ms
monotonic_start_ms
monotonic_end_ms
duration_ms
clock_source
```

Durations must derive from monotonic timestamps. Wall-clock timestamps are for report alignment.

## Event schema requirements

Each line in `events.jsonl` must include:

```text
schema_version
run_id
stage_id
coverage_id
scale
node_count
scenario_name
sample_id
event_id
event_type
timestamp_unix_ms
monotonic_ms
severity
subject_type
subject_id
operation_id
fault_id
message
metadata
```

## Metric sample requirements

Each line in `metrics_timeseries.jsonl` must include:

```text
schema_version
run_id
stage_id
coverage_id
scale
node_count
scenario_name
sample_id
timestamp_unix_ms
monotonic_ms
source_type
source_id
metric_name
metric_value
metric_unit
labels
missing_reason
```

`metric_value` may be numeric, boolean, string, or `MISSING`. If it is `MISSING`, `missing_reason` is required.

## Workload window requirements

Every real operation/fault must provide windows:

```text
baseline
pre_event
event
recovery
post_recovery
all_run
```

Each window must contain:

```text
requested_qps
achieved_qps
ok_ops
error_ops
error_rate
latency_p50_ms
latency_p90_ms
latency_p95_ms
latency_p99_ms
latency_p999_ms or MISSING with reason
timeout_count
connection_error_count
moved_redirection_count
ask_redirection_count
cluster_down_error_count
readonly_error_count
tryagain_error_count
unknown_error_count
sample_count
window_start_event_id
window_end_event_id
```

Do not derive p99 from p95. Percentiles must be computed from observed operation latencies.

## Missing-data policy

Allowed missing states:

```text
MISSING
SKIPPED_WITH_REASON
UNSUPPORTED_WITH_REASON
FAIL
PASS
DRY_RUN_ONLY
```

Forbidden missing representations:

```text
null
empty string
0 used as a placeholder
field omission
NaN
Infinity
undefined
```

A required real-scale metric cannot be absent in a passing stage unless the stage document explicitly defines a blocked condition and the stage does not pass.

## Provenance requirements

Every derived table, chart, and report section must include source artifact paths. P38-P40 must be able to trace each final report value back to raw JSON/JSONL source artifacts and the commit that produced them.
