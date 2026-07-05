# CONTEXT_RELOAD - P39_VISUAL_REPORT_QUALITY_GATE

## Reload Result

- Current stage: `P39_VISUAL_REPORT_QUALITY_GATE`
- Current branch: `codex/valkey-scale-lab-loop`
- Current commit at stage start: `e0707c3`
- `python3 scripts/codex_gate.py next`: `P39_VISUAL_REPORT_QUALITY_GATE`
- Required documents from `docs/codex/goal-loop-strict/00_INDEX.md` were reread at stage start, including the legacy goal-loop contracts, strict contracts, `docs/codex/goal-loop-strict/stages/P39_VISUAL_REPORT_QUALITY_GATE.md`, and `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md`.
- Missing required docs: none observed.

## Stage Contract Summary

P39 is a report/visual-quality stage. It consumes P38 analysis artifacts and P30-P37 provenance artifacts, and must not invent new quantitative values. It must not start clusters, containers, workloads, real Valkey gates, or fault injection.

Required outputs:

- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/phase_summary.json`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_quality_report.json`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/final_report.md`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/final_report.html`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/*`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/visual_qa.md`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/analysis_provenance.json`
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/quant_summary.json`

Required report sections:

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
- >200 dry-run support summary
- Missing-data and blocked-row appendix
- Source artifact provenance index

Required charts/assets:

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

## Gate And Harness Summary

Manifest gates:

- `python3 scripts/codex_gate.py precheck --phase P39_VISUAL_REPORT_QUALITY_GATE`
- `python3 scripts/safety_scan.py`
- `python3 -m compileall -q scripts src`
- `python3 -m pytest -q tests/unit tests/integration`
- `python3 scripts/assert_strict_stage_contract.py --phase P39_VISUAL_REPORT_QUALITY_GATE`
- `python3 scripts/assert_no_bypass.py --phase P39_VISUAL_REPORT_QUALITY_GATE`
- `python3 scripts/assert_report_quality.py --phase P39_VISUAL_REPORT_QUALITY_GATE --report-index artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json`
- `python3 scripts/assert_analysis_provenance.py --phase P39_VISUAL_REPORT_QUALITY_GATE --report-index artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json`

The manifest-required schemas cover `phase_summary.json`, `report_index.json`, `report_quality_report.json`, `analysis_provenance.json`, and `quant_summary.json`. The stage document additionally requires final Markdown/HTML reports, assets, and visual QA.

## Source Artifact Handoff

P38 completed and pushed at commit `e0707c3`. P38 generated:

- 145 coverage rows in `coverage_heatmap_table.csv`
- 33 management latency rows
- 33 management convergence rows
- 6 failover curve rows
- 42 fault impact rows
- 279 workload window rows
- 14 resource usage rows
- 14 cleanup rows
- 1,687 missing-data rows
- `analysis_provenance.json` with source hashes for P30-P37 plus the strict coverage registry

P39 must render views from those versioned artifacts and preserve P38 source provenance. P39 should not scrape raw logs or derive quantitative values from rendered output.

## Implementation Notes For Subagents

- Existing `scripts/assert_report_quality.py` is currently shallow: it checks report index references and a small forbidden-token list plus `report_quality_report.status == PASS`. P39 likely needs a stronger P39-specific report quality gate for required sections, chart assets, non-empty assets, internal links, source citations, coverage totals, missing-data rendering, and table/chart count consistency.
- Existing `scripts/assert_analysis_provenance.py` has strong P38-specific checks but only generic checks for non-P38 phases. P39 likely needs report-index-aware provenance validation that required reports/assets exist and source artifacts are declared.
- Existing P26 report code under `src/valkey_scale_lab/report/final.py` may be useful as a pattern, but P39 must render from P38 strict analysis tables and meet the stricter P39 chart/section contract.
- P39 should write deterministic SVG or other static chart assets under `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/`; every asset referenced by `report_index.json` must exist and be non-empty.

## Safety Constraints

- No real Valkey runtime is required for P39.
- Do not start or mutate Docker/container runtime state.
- Do not perform host-level network mutation.
- Do not invent missing values; render `MISSING`, `SKIPPED_WITH_REASON`, or `UNSUPPORTED_WITH_REASON` only with reasons.
- Do not present dry-run rows above 200 nodes as real runtime evidence.
- Do not mark complete, commit, or push until design, worker, gates, fresh review, postcheck, and mark-complete pass.
