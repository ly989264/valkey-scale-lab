# L05 Reporting V2 Design

## Scope

L05 renders the committed loop-engineering JSON artifacts into readable views:

- `artifacts/loop_engineering/reports/index.html`
- `artifacts/loop_engineering/reports/coverage_matrix.csv`
- `artifacts/loop_engineering/reports/coverage_heatmap.svg`
- `artifacts/loop_engineering/reports/scale_ladder.svg`
- `artifacts/loop_engineering/reports/p13_timing_waterfall.svg`
- `artifacts/loop_engineering/reports/missing_metrics.csv`
- `artifacts/loop_engineering/reports/provenance_graph.json`

The source-of-truth remains the JSON artifacts. HTML, CSV, and SVG files are report views only.

## Inputs

- `artifacts/loop_engineering/reports/audit_report.json`
- `artifacts/loop_engineering/reports/provenance_graph.json`
- `artifacts/loop_engineering/reports/metric_catalog.json`
- `artifacts/loop_engineering/reports/coverage_matrix.json`
- `artifacts/loop_engineering/reports/p13_p14_scale_audit.json`
- `artifacts/phases/P13_SCALE_LADDER_50_100/scale_ladder_report.json`
- `artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json`
- `artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_100.json`

## Implementation

Add `scripts/render_audit_report.py` as a deterministic renderer. It reads the input artifacts, writes the required report views, and writes `artifacts/loop_engineering/reports/report_index.json` with hashes for every source and rendered view.

The renderer must:

- preserve coverage matrix layer/surface ordering from `coverage_matrix.json`;
- keep `MISSING`, `SKIPPED_WITH_REASON`, and `NO_BASELINE_YET` rows visible in CSV and HTML;
- render P14 only as opt-in dry-run/skipped coverage, never as real evidence;
- render P13 scale/timing values from the committed scale and timing JSON artifacts;
- reject measured metrics sourced from rendered `.html`, `.csv`, `.svg`, or `.md` views;
- avoid executing P14, real Valkey wrappers, or fault wrappers.

## Harness

New harness files:

- `schemas/artifact/loop_report_index.schema.json`
- `tests/report/test_loop_report_rendering.py`
- `tests/visualization/test_loop_report_visualizations.py`
- `tests/ci/test_loop_report_gate.py`

CI will run:

- `python3 scripts/render_audit_report.py --input-dir artifacts/loop_engineering/reports --out-dir artifacts/loop_engineering/reports`
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/loop_report_index.schema.json --instance artifacts/loop_engineering/reports/report_index.json`
- `python3 -m pytest -q tests/report tests/visualization tests/ci/test_loop_report_gate.py`

## Anti-Regression Controls

- Do not edit `artifacts/phases/**`, `artifacts/gates/**`, or historical audit decisions.
- Do not use rendered report files as measured metric sources.
- Do not add `P14_SCALE_1000_OPTIN_DRYRUN`, `VSLAB_ALLOW_1000_DRYRUN`, `scripts/valkey_e2e_gate.py`, `scripts/fault_safety_gate.py`, or `scripts/fault_failover_gate.py` to static CI.
- Do not fabricate missing metric values; missing/skipped rows must keep reason text.
