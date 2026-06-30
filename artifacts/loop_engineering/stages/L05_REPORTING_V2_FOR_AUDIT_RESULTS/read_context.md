# Read Context: L05_REPORTING_V2_FOR_AUDIT_RESULTS

Created at: 2026-06-30T07:59:59Z
Branch: `codex/valkey-scale-lab-loop`
Base head: `bbc94d239ab349cda30588778bf92d08fb0e5458`

## Files Read

- `README.md`
- `AGENTS.md`
- `CODEX_START_HERE.md`
- `codex/phase_manifest.json`
- `.github/workflows/github-coverage-gates.yml`
- `.github/workflows/codex-gates.yml`
- `codex/loop_engineering/README.md`
- `codex/loop_engineering/00_OPERATING_CONTRACT.md`
- `codex/loop_engineering/01_STAGE_LOOP_PROTOCOL.md`
- `codex/loop_engineering/02_AGENT_PROTOCOL.md`
- `codex/loop_engineering/03_HARNESS_POLICY.md`
- `codex/loop_engineering/04_STAGE_MANIFEST.md`
- `codex/loop_engineering/05_VALIDATION_COMMANDS.md`
- `codex/loop_engineering/06_STATE_AND_ARTIFACT_CONTRACT.md`
- `artifacts/loop_engineering/global_loop_state.json`
- `artifacts/loop_engineering/stages/L04_P13_P14_SCALE_AUDIT_AND_REFRESH/stage_result.json`
- `artifacts/loop_engineering/reports/audit_report.json`
- `artifacts/loop_engineering/reports/provenance_graph.json`
- `artifacts/loop_engineering/reports/metric_catalog.json`
- `artifacts/loop_engineering/reports/coverage_matrix.json`
- `artifacts/loop_engineering/reports/p13_p14_scale_audit.json`
- `artifacts/phases/P13_SCALE_LADDER_50_100/scale_ladder_report.json`
- `artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json`
- `artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_100.json`

## Stage Definition Summary

L05 must convert audit results, metric catalog, coverage matrix, scale ladder, and P13 timing data into readable report and visualization artifacts. Required outputs are:

- `artifacts/loop_engineering/reports/index.html`
- `artifacts/loop_engineering/reports/coverage_matrix.csv`
- `artifacts/loop_engineering/reports/coverage_heatmap.svg`
- `artifacts/loop_engineering/reports/scale_ladder.svg`
- `artifacts/loop_engineering/reports/p13_timing_waterfall.svg`
- `artifacts/loop_engineering/reports/missing_metrics.csv`
- `artifacts/loop_engineering/reports/provenance_graph.json`

All rendered files must be views over machine-readable artifacts, not source-of-truth. Missing values must remain explicit (`MISSING`, `SKIPPED_WITH_REASON`, or equivalent existing semantics) and must not be invented.

## Current Artifact Inputs

- L01 audit report exists at `artifacts/loop_engineering/reports/audit_report.json`.
- L02 provenance graph exists at `artifacts/loop_engineering/reports/provenance_graph.json`.
- L03 metric catalog and coverage matrix exist at `artifacts/loop_engineering/reports/metric_catalog.json` and `coverage_matrix.json`.
- L04 P13/P14 scale audit exists at `artifacts/loop_engineering/reports/p13_p14_scale_audit.json` and reports P13 50/100 evidence with P14 dry-run boundary.
- P13 scale ladder and timing breakdown artifacts exist under `artifacts/phases/P13_SCALE_LADDER_50_100/`.

## Constraints

- Do not run P14 or set `VSLAB_ALLOW_1000_DRYRUN`.
- Do not invoke `scripts/valkey_e2e_gate.py`, `scripts/fault_safety_gate.py`, or `scripts/fault_failover_gate.py` for L05.
- Keep report outputs deterministic enough for regression tests; record generated artifacts as views.
- Do not modify historical phase/gate artifacts to make report rendering easier.
- If a source artifact is absent, encode the missing report section explicitly instead of fabricating values.

## Risks

- Existing `scripts/render_audit_report.py` and `tests/visualization` are absent, so L05 must add report/visualization harness before implementation.
- Existing report tests cover package-level P09 rendering but not loop-engineering report artifacts.
- `rg` exploration found missing historical phase directories (`P09_REPORT`, `P11_STABILITY_BASELINE`) when queried directly; L05 should use existing artifacts and provenance graph paths rather than assuming those directories exist locally.
- SVG/CSV golden tests must verify source-driven outputs without brittle timestamp-only comparisons.
