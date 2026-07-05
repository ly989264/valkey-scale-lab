# DESIGN_BRIEF - P39_VISUAL_REPORT_QUALITY_GATE

## Stage Objective

Render the final human-facing Markdown and HTML report from P38 analysis outputs plus P30-P37 provenance. Strengthen report-quality/provenance gates so P39 fails closed on missing sections, broken assets, misleading empty displays, forbidden placeholders, missing source citations, or coverage/count drift. P39 must not start Valkey, Docker, workloads, or faults, and must not invent quantitative values.

## Current Repo Facts

- Stage doc: `docs/codex/goal-loop-strict/stages/P39_VISUAL_REPORT_QUALITY_GATE.md`.
- Context reload: `artifacts/goal_loop_strict/P39_VISUAL_REPORT_QUALITY_GATE/CONTEXT_RELOAD.md`.
- Existing report-quality gate: `scripts/assert_report_quality.py`; currently shallow and should be strengthened for P39-specific sections/charts/assets/table provenance.
- Existing provenance gate: `scripts/assert_analysis_provenance.py`; strong for P38, generic for later phases, so P39 needs report-index-aware checks.
- Existing report code likely to reuse or mirror: `src/valkey_scale_lab/report/final.py`, `src/valkey_scale_lab/report/render.py`, and CLI wiring in `src/valkey_scale_lab/cli.py` if a render command already exists or should be extended. Exact API shape: 待验证.
- Schemas available: `schemas/artifact/report_index.schema.json`, `schemas/artifact/final_report_index.schema.json`, `schemas/artifact/quant_summary.schema.json`, `schemas/artifact/phase_summary.schema.json`; whether `report_quality_report.json` and P39 `analysis_provenance.json` already have dedicated schemas: 待验证.
- P38 source stage is `P38_CROSS_SCALE_ANALYSIS_REGRESSION`, with tables named by `scripts/assert_analysis_provenance.py`: coverage, management latency/convergence, failover curves, fault impact, workload windows, resource usage, cleanup, and missing data.

## Exact Implementation Plan

1. Add a deterministic P39 renderer that reads only P38 tables/JSON plus P30-P37 source provenance declared through P38.
2. Emit required report sections in both `final_report.md` and `final_report.html`:
   - Executive summary
   - Strict coverage heatmap
   - Resource preflight and scale feasibility
   - Cluster lifecycle summary
   - Management operation matrix
   - Management latency and convergence charts
   - Fault/failover matrix
   - Failover latency curves for 50/100/200
   - Fault-period workload impact
   - Partition and split-brain findings
   - Telemetry completeness
   - Cleanup and leftover-resource summary
   - `>200` dry-run support summary
   - Missing-data and blocked-row appendix
   - Source artifact provenance index
3. Generate deterministic static SVG assets under `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/` for:
   - `coverage_heatmap`
   - `management_wall_ms_by_operation_and_scale`
   - `management_convergence_ms_by_operation_and_scale`
   - `failover_promotion_latency_curve_50_100_200`
   - `failover_cluster_recovery_latency_curve_50_100_200`
   - `workload_qps_ratio_by_fault_and_scale`
   - `workload_p99_delta_by_fault_and_scale`
   - `error_rate_delta_by_fault_and_scale`
   - `resource_usage_by_scale`
   - `cleanup_status_by_stage`
4. For unavailable values, render explicit `MISSING`, `SKIPPED_WITH_REASON`, or `UNSUPPORTED_WITH_REASON` with reason text from source artifacts; never calculate replacements.
5. Emit `report_index.json` with report paths, asset paths, chart IDs, section IDs, source artifact references, coverage row totals copied from P38, and provenance links.
6. Emit `analysis_provenance.json` for P39 declaring analysis/report-only mode, no runtime started, source artifacts, output artifacts, and source hash preservation.
7. Emit `report_quality_report.json` with PASS/FAIL, checked sections, checked charts, checked references, forbidden-token scan, missing-data reason audit, and visual QA findings.
8. Emit `visual_qa.md` documenting manual/static visual inspection scope and citing `report_quality_report.json`.
9. Emit `phase_summary.json` and `quant_summary.json` as schema-valid summaries of rendered outputs and source coverage, not new runtime metrics.

## Files Likely To Change

- `src/valkey_scale_lab/report/final.py`
- `src/valkey_scale_lab/report/render.py`
- `src/valkey_scale_lab/cli.py` if needed for a P39 render entrypoint
- `scripts/assert_report_quality.py`
- `scripts/assert_analysis_provenance.py`
- `schemas/artifact/report_index.schema.json`
- `schemas/artifact/final_report_index.schema.json` or new/updated schema for P39 index: 待验证
- schema for `report_quality_report.json`: 待验证
- `tests/report/test_report_rendering.py` or new P39-focused report tests
- `tests/ci/test_final_report_regression_gate.py` or new gate tests: 待验证

## Expected Output Artifacts

- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/phase_summary.json`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_quality_report.json`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/final_report.md`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/final_report.html`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/*.svg`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/visual_qa.md`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/analysis_provenance.json`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/quant_summary.json`

## Source Artifacts

- P38 tables and JSON under `artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/`: exact existence/path set 待验证.
- P38 `analysis_provenance.json` source hashes for P30-P37 plus coverage registry.
- P30-P37 provenance artifacts only through declared P38 provenance; P39 should not scrape raw logs or unvalidated runtime output.

## Report Index / Provenance Shape

`report_index.json` should include at minimum:

- `phase`: `P39_VISUAL_REPORT_QUALITY_GATE`
- `reports`: Markdown and HTML paths
- `assets`: all generated asset paths
- `sections`: section IDs, titles, report anchors, source artifact references
- `charts`: chart IDs, asset paths, source table, row count, source artifact references
- `tables`: rendered table IDs, source table, row count, source artifact references
- `coverage_totals`: copied/derived from P38 coverage table with source reference
- `provenance`: path to P39 `analysis_provenance.json`

`analysis_provenance.json` should include source artifact objects with path, source stage, sha256, and output artifact objects for every P39 artifact; it must assert `invented_values_present=false`, `analysis_only=true`, and `runtime_started=false`.

## Gate Strengthening Needed

- `scripts/assert_report_quality.py` should validate required P39 sections, chart IDs, non-empty asset files, report/index cross references, forbidden strings including `NaN`, `Infinity`, `undefined`, `Traceback`, `TODO`, `PLACEHOLDER`, and broken image/link references.
- It should reject empty success tables and require every `MISSING`/`SKIPPED_WITH_REASON` display to include a reason.
- It should compare report/index coverage totals to P38 analysis totals.
- `scripts/assert_analysis_provenance.py` should validate P39 report-index source references and sha256s, and reject raw logs/unvalidated sources.

## Coverage IDs Targeted

All P30-P37 strict coverage rows summarized by P38, including management operations, failover/fault matrix rows, workload impact rows, resource feasibility rows, cleanup rows, and `>200` dry-run-only rows. Exact coverage ID list should be loaded from P38/coverage registry, not duplicated manually.

## Commands / Gates

- `python3 scripts/codex_gate.py precheck --phase P39_VISUAL_REPORT_QUALITY_GATE`
- `python3 scripts/safety_scan.py`
- `python3 -m compileall -q scripts src`
- `python3 -m pytest -q tests/unit tests/integration`
- `python3 scripts/assert_strict_stage_contract.py --phase P39_VISUAL_REPORT_QUALITY_GATE`
- `python3 scripts/assert_no_bypass.py --phase P39_VISUAL_REPORT_QUALITY_GATE`
- `python3 scripts/assert_report_quality.py --phase P39_VISUAL_REPORT_QUALITY_GATE --report-index artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json`
- `python3 scripts/assert_analysis_provenance.py --phase P39_VISUAL_REPORT_QUALITY_GATE --report-index artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json`
- `python3 scripts/codex_gate.py postcheck --phase P39_VISUAL_REPORT_QUALITY_GATE`
- `python3 scripts/codex_gate.py mark-complete --phase P39_VISUAL_REPORT_QUALITY_GATE`

## Safety Constraints

- Do not start clusters, Docker containers, workloads, faults, or network mutation.
- Do not use sudo or host network/firewall/route changes.
- Do not generate new real Valkey evidence.
- Do not present `>200` rows as real runtime evidence.
- Do not invent or interpolate missing quantitative values.
- Do not weaken harness controls or mark complete before gates and fresh review pass.

## Blocked Conditions

- Required P38 artifacts missing or schema-invalid.
- Required section/chart cannot be sourced from P38/P30-P37 provenance.
- Any report asset is missing, empty, or broken.
- Forbidden display strings appear in generated reports/assets/index.
- `MISSING`/`SKIPPED_WITH_REASON` appears without reason.
- Report coverage totals diverge from P38 analysis totals.
- Provenance lacks source path/hash, uses raw logs, or references nonexistent artifacts.

## Review Focus Points

- Confirm final Markdown/HTML structure includes every required section and chart.
- Inspect `report_quality_report.json` and ensure it proves the checks, not just claims PASS.
- Verify all charts/tables cite source artifacts and no values are invented.
- Verify missing/blocked rows are visibly labeled with reasons.
- Verify dry-run rows above 200 nodes are clearly dry-run-only.
- Verify strengthened gates fail closed for broken assets, omitted sections, bad tokens, and missing provenance.
