# 06_QUANTIFICATION_SPEC.md — Canonical Quantitative Collection

## Purpose

Every management operation and fault scenario must be measurable. The reporting layer must be able to build tables and curves from artifacts without reading logs or source code.

## Canonical time model

Use monotonic timestamps for durations and wall-clock timestamps for report alignment.

Every event should include:

```text
run_id
phase_id
scenario_name
sample_id
node_count
event_type
event_time_unix_ms
monotonic_ms
logical_node_id
role
az_id
host_id
operation_id_or_fault_id
metadata
```

If a timestamp cannot be captured, write `MISSING` with a reason and fail the stage if the timestamp is required for that stage's core metric.

## Canonical workload windows

All management and fault scenarios must define workload windows:

```text
baseline: before any operation/fault setup starts
pre_event: immediately before the operation/fault trigger
event: operation/fault active period
recovery: trigger cleared or operation command complete, waiting for health/data path recovery
post_recovery: stable period after recovery
all_run: entire workload duration
```

Window boundaries must be represented as event IDs, not only as timestamps.

## Workload metrics per window

Each workload window must contain:

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
```

Latency percentiles must be calculated from observed operation latencies. Do not derive p99 from p95.

## Management metrics

Every operation result must contain:

```text
operation_name
operation_id
node_count
started_at_unix_ms
ended_at_unix_ms
wall_ms
prepare_ms
command_ms
convergence_ms
cleanup_ms
slots_moved
keys_moved
bytes_migrated or MISSING
slot_balance_before
slot_balance_after
cluster_known_nodes_before
cluster_known_nodes_after
cluster_state_before
cluster_state_after
cluster_slots_assigned_before
cluster_slots_assigned_after
cluster_slots_ok_before
cluster_slots_ok_after
workload_impact_ref
errors_by_type
```

## Failover metrics

Every failover sample must contain:

```text
node_count
sample_id
target_primary_logical_id
target_primary_node_id
target_primary_az_id
target_primary_host_id
fault_injected_at_ms
primary_unreachable_at_ms
replica_promoted_at_ms
cluster_state_ok_at_ms
slot_coverage_ok_at_ms
first_successful_read_at_ms
first_successful_write_at_ms
fault_cleared_at_ms
old_primary_rejoined_at_ms or MISSING
promotion_latency_ms
cluster_recovery_latency_ms
read_unavailability_ms
write_unavailability_ms
split_brain_window_ms or MISSING
workload_impact_ref
```

Promotion latency is `replica_promoted_at_ms - fault_injected_at_ms`. Cluster recovery latency is `slot_coverage_ok_at_ms - fault_injected_at_ms` unless a stage-specific detector defines a stricter endpoint.

## Fault metrics

Every fault report must contain:

```text
fault_type
fault_id
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
```

Network fault parameters must include delay/loss/flap/partition parameters as applicable.

## Metric sample JSONL

`metrics_timeseries.jsonl` must contain one JSON object per sample. Required common fields:

```text
schema_version
run_id
phase_id
scenario_name
sample_id
timestamp_unix_ms
monotonic_ms
source_type        # valkey_info | cluster_info | cluster_nodes | docker_stats | workload | harness
source_id
metric_name
metric_value
metric_unit
labels
missing_reason
```

`metric_value` may be numeric, string, boolean, or `MISSING`. If it is `MISSING`, `missing_reason` is required.

## Event JSONL

`events.jsonl` must contain one JSON object per event. Required common fields:

```text
schema_version
run_id
phase_id
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

Events should be stable enough for regression comparison. Use deterministic event types.

## Missing-data policy

Allowed missing states:

```text
MISSING: measurement expected but not available; reason required
SKIPPED_WITH_REASON: scenario intentionally skipped by stage rules; reason required and gate must allow the skip
UNSUPPORTED_WITH_REASON: platform/runtime lacks capability; reason required and gate must explicitly allow unsupported status
FAIL: attempted and failed
PASS: attempted and verified
```

Do not use `null`, empty string, `0`, or omitted field to represent missing data.

## Reporting derivation rule

All CSV, Markdown, HTML, and chart outputs must derive from JSON/JSONL artifacts. Reports must cite input artifact paths and include a generator version or commit hash.
