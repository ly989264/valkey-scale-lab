# L07 Stage Design

## Objective

Strengthen 30/50/100 real scale build metric coverage with a normalized, source-of-truth audit artifact. The artifact must connect each rung to committed machine-readable evidence, record measured metrics where they exist, preserve explicit missing/skipped semantics where historical artifacts lack detail, and keep P14 dry-run-only.

## Agent Inputs

- `requirements_analyst`: approved. Main gaps are unified 30/50/100 build metric coverage, resource preflight blocker semantics, 50/100 timing report cross-links, and explicit missing semantics for 30-node timing gaps.
- `harness_architect`: approved. Recommended a new schema, artifact builder, resource/data-path/timing/cleanup checks, report consistency tests, provenance checks, and P14 misclassification guard.
- `risk_auditor`: approved. Key risks are stale committed evidence, missing 30-node timing, P14 dry-run counted as real, report-layer fabrication, host-network safety, and harness weakening.

## Harness Plan

L07 adds `scripts/audit_scale_build_metrics.py`, `schemas/artifact/scale_build_metrics.schema.json`, and tests that validate committed 30/50/100 scale artifacts without running real scale gates by default.

The audit reads only JSON source artifacts:

- P12 scale_30: resource preflight, real evidence, scale rung/report, cleanup report, cluster snapshots.
- P13 scale_50/scale_100: resource preflight, real evidence, scale rung/report, cleanup report, runtime timing, setup timeline, P13 timing breakdown, cluster snapshots.
- P14 boundary: manifest/config/planner artifacts only, and never real Valkey evidence.

The audit emits `artifacts/loop_engineering/reports/scale_build_metrics.json` with:

- canonical rungs `[30, 50, 100]`;
- per-source SHA-256;
- resource preflight status and blocker semantics;
- real Valkey proof checks for version, node count, cluster state, probe count, and SET/GET data path;
- build metric records for startup, cluster create/meet, slot assignment, role convergence, membership convergence, data path, cleanup timing, residual scan, and report consistency;
- explicit `MISSING`/`SKIPPED_WITH_REASON` records for historical gaps, especially 30-node timing;
- P14 dry-run boundary with `real_valkey_coverage=false`.

## Acceptance Criteria

- The new artifact validates against its schema and has no blocking findings on current committed evidence.
- 30, 50, and 100 all appear as canonical real rungs.
- Failed/can_run=false preflight for any canonical rung is blocking.
- Real scale evidence must be `real_valkey=true`, Valkey `9.1.x`, exact node count, `cluster_state_observed=ok`, `probe_result=PASS`, and `data_path_result=PASS`.
- 50/100 detailed timing fields are measured from P13 timing/setup/runtime artifacts.
- 30-node detailed timing gaps remain explicit `MISSING` or `SKIPPED_WITH_REASON`, never invented.
- Cleanup residual resources are blocking; cleanup timing gaps are explicit.
- Rendered views are not accepted as metric sources.
- P14 real evidence or a real 1000-node rung is blocking.

## Validation

- Schema validation for `scale_build_metrics.json`.
- Unit and artifact tests under `tests/scale`, `tests/coverage`, `tests/report`, and `tests/ci`.
- Existing previous harness and loop-engineering validations.
- No P14 execution and no real scale wrapper rerun unless resource preflight and user policy later permit it.
