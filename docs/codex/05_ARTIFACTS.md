# 05_ARTIFACTS.md — Artifact Contract

## 1. Artifact envelope

Every JSON artifact should include:

```json
{
  "schema_version": "v1",
  "artifact_type": "...",
  "phase_id": "P06_OBSERVABILITY_METRICS",
  "run_id": "...",
  "created_at": "2026-01-01T00:00:00Z",
  "producer": {"name": "valkey-scale-lab", "version": "0.1.0"},
  "status": "PASS"
}
```

Allowed statuses:

```text
PASS
FAIL
PARTIAL
MISSING
SKIPPED_WITH_REASON
NO_BASELINE_YET
```

## 2. Required artifact families

```text
run_metadata.json              run ID, environment, seed, versions
config_effective.json          normalized config after defaults
cluster_plan.json              host/AZ/port/container placement
valkey_e2e_evidence.json       independent real Valkey probe result
management_ops_report.json     operation matrix and timings
workload_report.json           QPS, latency, errors, data-path stats
metrics_timeseries.jsonl       timestamped metrics samples
events.jsonl                   experiment event timeline
fault_report.json              injected faults and observed impact
failover_report.json           failover timings and slot recovery
stability_report.json          soak/stability summary
analysis_summary.json          computed conclusions from artifacts
report_index.json              generated report paths and checksums
cleanup_report.json            owned resource cleanup evidence
scale_ladder_report.json       rung-by-rung scale comparison
```

## 3. Missing data rule

If a collector or analyzer cannot measure a field, use this shape:

```json
{
  "value": null,
  "status": "MISSING",
  "reason": "docker_stats_unavailable_on_runtime",
  "impact": "cpu_per_container omitted; run still valid for cluster convergence metrics"
}
```

Never replace missing data with zero unless zero was measured.

## 4. JSONL rule

Each JSONL line is an independent JSON object with at least:

```json
{
  "schema_version": "v1",
  "artifact_type": "metric_sample",
  "phase_id": "P06_OBSERVABILITY_METRICS",
  "run_id": "...",
  "timestamp": "..."
}
```

Line-level schema validation must fail the artifact if any line is invalid.

