# M1-S07 Design Brief

Role: simulated design subagent
Reason: explicit subagent launch failed with usage-limit error; this document preserves the required independent design artifact before worker implementation.

## Goal Understanding

M1-S07 must add system-level observability that is not report-only. Process, network, and Valkey-side metrics must be emitted as schema-validated artifacts, attached to node ids and lifecycle windows, aggregated by analysis, rendered in the offline Chinese report, and checked by a strong harness gate. Unsupported metrics must be explicit `MISSING`/`SKIPPED_WITH_REASON` with reasons.

## Relevant Current Paths

- Runtime writers: `src/valkey_scale_lab/runtime/docker_runtime.py`
- Common telemetry row shape: `src/valkey_scale_lab/metrics/__init__.py`
- Analysis reader/aggregator: `src/valkey_scale_lab/analysis/summary.py`
- Offline Chinese report renderer: `src/valkey_scale_lab/report/render.py`
- Metric sample schema: `schemas/artifact/goal_loop_metric_sample.schema.json`
- Stage gates: `scripts/assert_*_m1.py`
- Fixtures/tests: `tests/fixtures/*`, `tests/artifacts`, `tests/analysis`, `tests/report`, `tests/unit`

## Propagation Plan

- Schema: add system metric source types and a `system_metrics_report` schema.
- Writer: runtime emits `system_metrics_timeseries.jsonl`, appends compatible rows to `metrics_timeseries.jsonl`, and writes `system_metrics_report.json`.
- Fixture: add success, missing, blocked, cleanup, dry-run, and scale 30/50/100/200 fixture directories.
- Reader: analysis loads `system_metrics_timeseries.jsonl`, with fallback to compatible `metrics_timeseries.jsonl` rows.
- Aggregator: compute per-node, per-window, aggregate distributions, missing metrics, and abnormal-node TopN.
- Renderer: create CSV and SVG outputs plus Chinese Markdown/HTML sections for resource trends and abnormal nodes.
- Gate: add `scripts/assert_system_metrics_m1.py` to verify non-empty rows, node ids, window aggregation, missing reasons, and report display.
- Docs/artifacts: update coverage matrix, worker summary, review, completion, and handoff.

## Coverage Matrix Intent

- Execution shape: fixture/unit/integration/report/smoke plus real or blocked evidence.
- Scale rung: small fixture plus 30/50/100/200 fixture structure; 200+ dry-run remains blocked/planning only.
- Functional path: setup, management, workload, fault, cleanup via lifecycle window labels.
- Data path: schema -> writer -> fixture -> reader -> aggregator -> renderer -> gate -> docs.
- Outcomes: success, missing metric, blocked, cleanup residual/report missing inputs.

## Risks

- Some process/network counters are platform-dependent. The safe default collector should avoid host `/proc`, firewall, route, or interface mutation and encode unsupported counters with reasons.
- A single end-of-scenario collection cannot claim high-frequency trend fidelity. It should be described as low-frequency lifecycle samples and preserve actual collection timestamps.
- Real 50/100/200 execution may be resource-blocked; blocked artifacts must not claim PASS.

## Non-Local-Patch Checks

Review should fail if rows only exist in fixtures, if report sections are not backed by analysis aggregates, if missing metrics lack reasons, if node ids/windows are absent, or if real gates are faked.
