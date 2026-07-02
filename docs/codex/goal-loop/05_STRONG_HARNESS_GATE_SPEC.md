# 05_STRONG_HARNESS_GATE_SPEC.md — Strong Harness Requirements

## Purpose

The harness must prevent false completion. A stage cannot pass because code compiles or because a report file exists. It must pass because the harness independently verifies the promised capability.

## P15 required harness extensions

P15 must add or strengthen harness support for the goal loop.

Required capabilities:

```text
1. stage discovery for P15-P26
2. per-stage common artifact checks
3. per-stage Markdown handoff checks
4. schema validation for new JSON/JSONL artifacts
5. management operation coverage assertions
6. failover latency curve assertions
7. network fault coverage assertions
8. partition/split-brain assertions
9. workload-impact assertions
10. cleanup assertions for every real stage
```

Do not weaken existing `codex_gate.py`, `gate_lock.json`, or existing schemas. If the lock must change because new harness files are added, update it transparently and prove the lock still detects unauthorized changes.

## Required assertion scripts

The implementation should create scripts equivalent to the following names. Exact names may differ only if the manifest, docs, and tests agree.

```text
scripts/assert_goal_loop_stage.py
scripts/assert_quant_artifacts.py
scripts/assert_management_ops_coverage.py
scripts/assert_failover_latency_curve.py
scripts/assert_fault_matrix_coverage.py
scripts/assert_workload_impact.py
scripts/assert_split_brain_report.py
```

Each script must fail closed. Missing file, malformed JSON, missing metric, empty sample set, or invalid status must be a non-zero exit.

## Required schema families

The implementation should create schemas equivalent to:

```text
schemas/artifact/quant_summary.schema.json
schemas/artifact/workload_windows.schema.json
schemas/artifact/management_ops_matrix.schema.json
schemas/artifact/management_operation_result.schema.json
schemas/artifact/failover_latency_curve.schema.json
schemas/artifact/fault_matrix_report.schema.json
schemas/artifact/network_fault_report.schema.json
schemas/artifact/partition_report.schema.json
schemas/artifact/split_brain_report.schema.json
schemas/artifact/workload_impact_report.schema.json
```

JSONL files must validate line-by-line. A single invalid line fails the stage.

## Required real-gate behavior

Real gates must independently verify:

- Valkey version prefix `9.1.`;
- live endpoints respond;
- cluster topology matches expected node count and roles;
- `CLUSTER INFO` reaches an expected state after operations/faults unless the stage specifically expects unavailability;
- data-path SET/GET or workload transactions actually occur;
- cleanup removes owned containers/networks/volumes or fails.

## Management coverage gate

The management coverage assertion must require stage-specific operation rows with these fields:

```text
operation_name
node_count
operation_status
started_at_unix_ms
ended_at_unix_ms
wall_ms
command_ms
convergence_ms
cluster_state_before
cluster_state_after
slots_before
slots_after
workload_window_ref
errors_by_type
missing_fields
```

`operation_status=PASS` is allowed only when a real operation was executed and verified. Unsupported operations must be `SKIPPED_WITH_REASON`. Failed operations must be `FAIL`.

## Failover latency curve gate

The failover curve assertion must require:

```text
rungs: 30, 50, 100 for P20
rung: 200 for P21
sample_count_per_rung >= stage minimum
each sample has fault timestamp, promotion timestamp, slot coverage timestamp, first read/write recovery timestamp, workload impact reference
curve data derived from samples only
```

If resource preflight fails, the stage is blocked; it must not emit a PASS curve with fake values.

## Network fault gate

The fault matrix assertion must require evidence for:

```text
delay
loss
partition
flap
```

Each network fault must record the sandbox implementation path:

```text
container_netns_tc
sandbox_proxy
unsupported_skipped_with_reason
```

A host-level firewall/routing mutation must fail safety review.

## Split-brain gate

Split-brain reporting must include both negative and positive evidence:

- whether multiple primaries claimed overlapping slots;
- whether conflicting writes were possible;
- whether cluster views diverged between partitions;
- duration of any observed split-brain indicator;
- `MISSING` with reason if an indicator cannot be measured.

Do not report `split_brain_window_ms=0` unless the detector actually ran and observed no window.

## Workload impact gate

Workload impact must compare windows:

```text
baseline
pre_fault_or_pre_operation
fault_or_operation
recovery
post_recovery
all_run
```

For each window, require requested QPS, achieved QPS, p50/p95/p99 latency, error count, timeout count, redirection count, and missing-data reason when absent.
