# P25_FAULT_WORKLOAD_IMPACT_ANALYSIS — Fault-Period Workload Impact Analysis

## Stage objective

Consolidate workload impact across management and fault stages into comparable quantitative artifacts.

## Worker implementation requirements

Implement analysis that consumes artifacts from P17-P24 and produces:

- cross-operation QPS delta table;
- cross-fault QPS delta table;
- latency p50/p95/p99 delta table;
- error-rate delta table;
- recovery duration table;
- missing-data summary;
- machine-readable comparison artifact;
- report-ready CSV exports.

Analysis must read existing artifacts only. It must not rerun scenarios unless a stage-specific gate requires a smoke verification.

## Required artifacts

```text
workload_impact_cross_stage.json
workload_impact_by_operation.csv
workload_impact_by_fault.csv
latency_delta_table.csv
error_delta_table.csv
recovery_duration_table.csv
missing_data_summary.json
quant_summary.json
```

## Required assertions

- all required source stages are represented or explicitly marked missing with reason;
- calculations use artifact data only;
- baseline/fault/recovery/post windows are present for each included row;
- no fabricated data;
- CSV rows match JSON source counts.

## Review focus

Trace several rows back to source artifacts. Reject hand-written report numbers.
