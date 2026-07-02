# P16_QUANT_TELEMETRY_UNIFICATION — Unified Quantitative Telemetry

## Stage objective

Implement canonical metrics/events/workload-window collection so later management and fault stages all write comparable artifacts.

## Design subagent focus

Inspect current metrics, workload, runtime, artifact, CLI, and e2e gate implementation. Identify the minimum shared interfaces needed for later stages.

## Worker implementation requirements

Implement:

- metric sample writer for `metrics_timeseries.jsonl`;
- event writer for `events.jsonl`;
- workload window aggregator for baseline/pre_event/event/recovery/post_recovery/all_run;
- quant summary generator;
- missing-data encoding helpers;
- schema validation path for JSON and JSONL;
- CLI or internal API to attach telemetry to `gate scenario` runs;
- a real 6-node Valkey telemetry smoke scenario.

Do not implement management/fault stage logic beyond hooks needed for telemetry.

## Required real scenario

Run a real 6-node scenario that:

- starts a Valkey cluster;
- runs a low-QPS workload;
- samples `INFO`, `CLUSTER INFO`, and `CLUSTER NODES`;
- emits workload window metrics;
- independently verifies Valkey endpoints;
- cleans up.

## Required artifacts

```text
artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/phase_summary.json
artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/valkey_e2e_evidence.json
artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/cleanup_report.json
artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/events.jsonl
artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/metrics_timeseries.jsonl
artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/workload_windows.json
artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/quant_summary.json
```

## Required assertions

- JSONL line-by-line validation passes.
- At least one Valkey INFO sample exists per live node.
- At least one workload window has non-zero sample count.
- Missing metrics use `MISSING` with a reason.
- Cleanup has no owned resources remaining.

## Review focus

Verify telemetry is generic and cannot silently drop fields. Verify all later stage specs can use this telemetry model.
