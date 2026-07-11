# P29_QUANT_TELEMETRY_COLLECTOR_HARDENING — Quant Telemetry Collector Hardening

## Purpose

Unify the telemetry model before large real stages run. This stage must make missing metrics explicit and ensure every later operation/fault can be analyzed.

## Required implementation

P29 must implement or strengthen:

```text
event writer
metric JSONL writer
workload window aggregator
topology snapshot collector
Valkey INFO / CLUSTER INFO / CLUSTER NODES samplers
Docker/process stats sampler where available
missing-data encoder
artifact provenance writer
schema validation helper
```

P29 should run a bounded small real Valkey proof to validate the collector before 50/100/200 stages. It must not claim large-scale coverage.

## Required artifacts

```text
artifacts/phases/P29_QUANT_TELEMETRY_COLLECTOR_HARDENING/phase_summary.json
artifacts/phases/P29_QUANT_TELEMETRY_COLLECTOR_HARDENING/valkey_e2e_evidence.json
artifacts/phases/P29_QUANT_TELEMETRY_COLLECTOR_HARDENING/cleanup_report.json
artifacts/phases/P29_QUANT_TELEMETRY_COLLECTOR_HARDENING/events.jsonl
artifacts/phases/P29_QUANT_TELEMETRY_COLLECTOR_HARDENING/metrics_timeseries.jsonl
artifacts/phases/P29_QUANT_TELEMETRY_COLLECTOR_HARDENING/workload_windows.json
artifacts/phases/P29_QUANT_TELEMETRY_COLLECTOR_HARDENING/quant_summary.json
artifacts/phases/P29_QUANT_TELEMETRY_COLLECTOR_HARDENING/telemetry_completeness_report.json
```

## Required gates

```text
python3 scripts/assert_quant_completeness.py --phase P29_QUANT_TELEMETRY_COLLECTOR_HARDENING
python3 scripts/assert_exact_scale_real_evidence.py --phase P29_QUANT_TELEMETRY_COLLECTOR_HARDENING --min-nodes 6
python3 scripts/assert_no_bypass.py --phase P29_QUANT_TELEMETRY_COLLECTOR_HARDENING
```

## Pass criteria

P29 passes only when:

```text
real Valkey proof exists for collector smoke
JSONL validates line-by-line
every MISSING metric has a reason
null/NaN/undefined are rejected
workload windows contain required metrics
provenance links raw samples to summaries
cleanup passes
```

## Blocking conditions

```text
metrics silently omit required fields
latency percentiles are fabricated
JSONL accepts invalid lines
real proof is fake or absent
cleanup fails
```
