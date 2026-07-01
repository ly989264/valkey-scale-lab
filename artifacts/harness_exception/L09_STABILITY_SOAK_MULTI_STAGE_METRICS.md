# Harness Exception: L09_STABILITY_SOAK_MULTI_STAGE_METRICS

## Locked File

- `schemas/artifact/stability_report.schema.json`

## Defect

The locked stability report schema was too permissive for L09. It required only
generic metadata, `duration_seconds`, and an unconstrained `summary` object.
That allowed a short P11 stability smoke artifact to remain schema-valid even
when it lacked the L09-required multi-stage soak model:

- no `baseline`, `steady`, `fault`, `recovery`, or `post_recovery` windows;
- no required `soak_profile` bounded metadata;
- no required JSONL time-series path;
- no required baseline comparison path;
- no strict requirement that each measured window encode p50/p95/p99 latency
  and workload counters, or an explicit `MISSING`/`SKIPPED_WITH_REASON`
  object with a reason;
- no guard against claiming long-run stability from bounded short windows.

## Patch

The schema is strengthened to require:

- `soak_profile`;
- `metrics_timeseries_path`;
- `baseline_comparison_path`;
- `summary.windows` with all five L09 windows;
- measured window workload counters and latency p50/p95/p99 values, either as
  numeric measurements or explicit missing/skipped objects with reasons;
- `soak_profile.long_run_stability_claim=false`;
- required workload, metric, restart, leak, error, and baseline summary
  sections.

The runtime and real P11 wrapper artifacts were regenerated so
`artifacts/phases/P11_STABILITY_SOAK/stability_report.json` now validates
against the stronger schema and points to a JSONL time series whose rows carry
L09 window labels.

## Before/After Behavior

Before: a P11 smoke report without L09 stage windows could satisfy the locked
schema, so L09 could pass with incomplete stability evidence.

After: the same incomplete report fails schema validation. Automatic short
soaks must be explicitly bounded, must include all five windows, must encode
per-window latency percentiles and workload counters as measured values or
reasoned missing/skipped objects, and must not claim long-run stability. P14
remains opt-in only and no 1000-node real gate is executed.

## Lock Update

- Previous `schemas/artifact/stability_report.schema.json` SHA256:
  `6bf8f2558b20a3f87b0aa6159e3a1d6f7d165a77c55437769a231698af2559c6`
- Updated `schemas/artifact/stability_report.schema.json` SHA256:
  `da32c1b4e796c5968dc176725031fefc94f8e864dd3ff3df65235fa22aab657f`
- Updated strict missing-metric `schemas/artifact/stability_report.schema.json`
  SHA256:
  `673c28b45ba95056b86fb8acf271c7ff58b245bd354a827fe64755d9a0963f38`

This lock update records the strengthened L09 schema rather than hiding a
weakened harness change.
