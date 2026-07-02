# P21_FAILOVER_LATENCY_CURVE_200 — Failover Latency Curve: 200 Nodes

## Stage objective

Extend the failover latency curve to 200 nodes with real Valkey evidence.

## Required rung

```text
200 nodes: minimum 3 samples
```

## Worker implementation requirements

Implement:

- strict resource preflight for 200 nodes;
- low but non-zero workload profile appropriate for 200-node safety;
- real 200-node cluster execution;
- primary stop through project-owned control;
- promotion, slot coverage, read/write recovery timing;
- raw sample and curve update;
- cleanup after every sample.

## Blocking rule

If preflight fails or Docker cannot run 200 nodes, write `BLOCKED.md` and stop. Do not mark complete. Do not substitute 100 nodes or dry-run output.

## Required artifacts

```text
resource_preflight_200.json
failover_latency_samples_200.jsonl
failover_latency_curve_200.json
failover_latency_curve_combined_30_50_100_200.json
workload_impact_report.json
events.jsonl
metrics_timeseries.jsonl
quant_summary.json
```

## Required assertions

- node_count is exactly 200 for each sample;
- sample count is at least three;
- real Valkey endpoint evidence exists;
- workload impact exists;
- combined curve includes 30/50/100/200;
- cleanup passes.

## Review focus

Reject dry-run evidence. Reject changing global default max to 200 for unrelated stages. Confirm P14 remains non-automatic.
