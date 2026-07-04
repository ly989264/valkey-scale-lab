# DESIGN_BRIEF - P38_CROSS_SCALE_ANALYSIS_REGRESSION

## Stage Objective

P38 aggregates validated P30-P37 artifacts into cross-scale analysis tables and a current regression baseline. It is analysis-only: no new Valkey cluster execution, no workload execution, no fault injection, no Docker/container runtime mutation, and no host network changes.

## Current Repo Facts

- Stage doc: `docs/codex/goal-loop-strict/stages/P38_CROSS_SCALE_ANALYSIS_REGRESSION.md`.
- Required context reload exists at `artifacts/goal_loop_strict/P38_CROSS_SCALE_ANALYSIS_REGRESSION/CONTEXT_RELOAD.md`.
- P38 manifest gates include `assert_analysis_provenance.py`, `assert_quant_completeness.py --category analysis`, `assert_coverage_registry.py --require-final-real-scales`, and `assert_no_bypass.py`.
- Existing `scripts/assert_analysis_provenance.py` only checks non-empty `source_artifacts`, path existence, and `invented_values_present=false`; this is likely too weak for P38 stage-doc pass criteria.
- Existing `scripts/assert_quant_completeness.py` has specific handling for P29-P36; analysis-category P38 semantics are 待验证 and likely need strengthening.
- P30-P32 management stages expose `management_ops_matrix.json`, `management_operation_results.jsonl`, `management_workload_impact.json`, `workload_windows.json`, `resource_preflight.json`, `cleanup_report.json`, `quant_summary.json`, and `coverage_ledger.json`.
- P33-P35 fault stages expose `fault_matrix_report.json`, `fault_operation_results.jsonl`, `failover_samples.jsonl`, `failover_latency_curve.json`, `partition_report.json`, `split_brain_report.json`, `fault_workload_impact.json`, `workload_windows.json`, `resource_preflight.json`, `cleanup_report.json`, `quant_summary.json`, and `coverage_ledger.json`.
- P36 exposes lifecycle/full-flow aggregate artifacts including `full_flow_matrix.json`, `full_flow_results.jsonl`, `workload_windows.json`, `cleanup_report.json`, `quant_summary.json`, and `coverage_ledger.json`.
- P37 exposes dry-run-only artifacts including `dry_run_results.jsonl`, per-target `resource_estimate_*.json`, `placement_schedule_*.json`, `no_runtime_created_proof*.json`, report projections, `quant_summary.json`, and `coverage_ledger.json`.
- Coverage registry exists at `artifacts/coverage/strict_coverage_registry.json` with 145 rows. Commit SHA fields may still contain pending placeholders 待验证.

## Exact Implementation Plan

1. Add a deterministic P38 artifact builder that reads only P30-P37 phase artifacts and `artifacts/coverage/strict_coverage_registry.json`.
2. Validate every source stage before using it: required artifact presence, source stage `status=PASS` where real, dry-run status for P37, coverage ledger/registry rows, and existing validation/gate references.
3. Generate CSV tables from machine-readable JSON/JSONL only:
   - coverage heatmap from the strict coverage registry.
   - management latency and convergence from P30-P32 `management_operation_results.jsonl`.
   - failover curves from P33-P35 `failover_latency_curve.json` and/or `failover_samples.jsonl`.
   - fault impact from P33-P35 `fault_workload_impact.json` plus fault operation rows.
   - workload windows from P30-P36 `workload_windows.json`.
   - resource usage from P30-P37 `resource_preflight.json` / P37 resource estimates.
   - cleanup from P30-P36 `cleanup_report.json` and P37 no-runtime cleanup proof.
   - missing data from all encountered `MISSING`, `SKIPPED_WITH_REASON`, or `UNSUPPORTED_WITH_REASON` values with reasons.
4. Emit `cross_scale_analysis_summary.json`, `analysis_provenance.json`, `regression_baseline.json`, `quant_summary.json`, and `phase_summary.json`.
5. Every derived row must carry `coverage_id`, source stage, source artifact path, and preferably JSON pointer/line identifier. Derived percentiles and deltas must declare method.
6. Strengthen assertions so P38 fails if any required table is missing/empty, any real 50/100/200 row is omitted, any >200 row is not dry-run-only, provenance is missing, or forbidden values appear.

## Exact Files Likely To Change

- `src/valkey_scale_lab/analysis/cross_scale.py` or similar new module.
- `src/valkey_scale_lab/analysis/__init__.py`.
- `src/valkey_scale_lab/cli.py` if exposing `python3 -m valkey_scale_lab.cli analyze --kind cross-scale` or equivalent.
- `scripts/p38_cross_scale_analysis.py` or equivalent small wrapper if existing CLI shape is inconvenient.
- `scripts/assert_analysis_provenance.py`.
- `scripts/assert_quant_completeness.py`.
- Possibly `schemas/artifact/strict_generic_report.schema.json` only if stronger schema is needed; prefer adding specific schemas instead of weakening generic schema.
- New schemas likely: `schemas/artifact/cross_scale_analysis_summary.schema.json`, `schemas/artifact/analysis_provenance.schema.json`, `schemas/artifact/regression_baseline.schema.json` 待验证.
- Tests likely: `tests/analysis/test_p38_cross_scale_analysis.py`, `tests/unit/test_assert_analysis_provenance.py`, `tests/unit/test_assert_quant_completeness_analysis.py` 待验证.
- P38 output artifacts under `artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/`.

## Expected P38 Outputs

- `phase_summary.json`
- `cross_scale_analysis_summary.json`
- `coverage_heatmap_table.csv`
- `management_latency_table.csv`
- `management_convergence_table.csv`
- `failover_curve_table.csv`
- `fault_impact_table.csv`
- `workload_window_table.csv`
- `resource_usage_table.csv`
- `cleanup_table.csv`
- `missing_data_table.csv`
- `analysis_provenance.json`
- `regression_baseline.json`
- `quant_summary.json`

## Source Artifact Families P30-P37

- P30-P32: management matrix, management operation results, topology snapshots, command logs, workload impact, workload windows, metrics/events, resource preflight, cleanup, quant summary, coverage ledger, real Valkey evidence.
- P33-P35: fault matrix, fault operation results, failover samples, failover latency curves, partition report, split-brain report, fault workload impact, topology snapshots, command logs, workload windows, metrics/events, resource preflight, cleanup, quant summary, coverage ledger, real Valkey evidence.
- P36: full-flow matrix/results, lifecycle workload windows, metrics/events, cleanup, quant summary, coverage ledger, per-scale evidence/report references.
- P37: dry-run results, dry-run plans, placement schedules, resource estimates, collision checks, artifact projections, report projections, no-runtime-created proofs, quant summary, coverage ledger.
- Registry: `artifacts/coverage/strict_coverage_registry.json`.

## Provenance Requirements

- No analysis value may be emitted without source path and coverage ID.
- Include source artifact sha256 and current commit for P38-produced provenance.
- For JSONL-derived rows, include source line number where practical.
- For table-level derived values, record formula/method, such as nearest-rank percentile from source samples or `event - baseline` delta.
- Do not read raw logs as final data unless already represented by schema-validated artifacts.
- Do not invent missing values; encode as `MISSING`, `SKIPPED_WITH_REASON`, or `UNSUPPORTED_WITH_REASON` with reason.

## Assertion And Gate Strengthening Needed

- `assert_analysis_provenance.py`: require all P38 output tables, row-level provenance, existing source paths, no invented values, no unvalidated logs, no fake/dry-run mixing into real metrics, and method declarations for percentiles/deltas.
- `assert_quant_completeness.py --category analysis`: add P38-specific checks for required output artifacts, non-empty tables, forbidden value scan, missing-data reasons, coverage row totals, and artifact refs matching generated files.
- Keep `assert_coverage_registry.py --require-final-real-scales` unchanged unless it fails to verify final real PASS rows; do not weaken it.
- `assert_no_bypass.py` should continue to reject host network mutation, fake gates, manual PASS writes, real execution above 200, and placeholders.

## Commands To Run

- `python3 -m compileall -q scripts src`
- `python3 -m pytest -q tests/unit tests/integration`
- P38 builder command 待验证, likely `python3 scripts/p38_cross_scale_analysis.py --phase P38_CROSS_SCALE_ANALYSIS_REGRESSION`
- `python3 scripts/assert_analysis_provenance.py --phase P38_CROSS_SCALE_ANALYSIS_REGRESSION`
- `python3 scripts/assert_quant_completeness.py --phase P38_CROSS_SCALE_ANALYSIS_REGRESSION --category analysis`
- `python3 scripts/assert_coverage_registry.py --phase P38_CROSS_SCALE_ANALYSIS_REGRESSION --require-final-real-scales`
- `python3 scripts/assert_no_bypass.py --phase P38_CROSS_SCALE_ANALYSIS_REGRESSION`
- Full manifest gate via `python3 scripts/codex_gate.py run --phase P38_CROSS_SCALE_ANALYSIS_REGRESSION` only from main/worker loop, not design subagent.

## Safety Constraints

- Do not start clusters, containers, workloads, or fault injection.
- Do not run real Valkey gates for P38.
- Do not mutate host firewall, routing, PF, nftables, iptables, interfaces, or OS network services.
- Do not use `sudo` for network or runtime operations.
- Do not treat P37 dry-run projections as real 50/100/200 metrics.
- Do not mark P38 complete unless gates, artifacts, and review pass.

## Blocked Conditions

- Any P30-P37 required source artifact is absent, malformed, not PASS where required, or not dry-run-only for P37.
- Coverage registry omits required real rows or >200 dry-run rows.
- Analysis table omits any required 50/100/200 row or omits >200 dry-run representation.
- Any output contains `null`, `NaN`, `Infinity`, `undefined`, empty placeholder values, or invented zero placeholders.
- Any derived value lacks source provenance.
- Fake or dry-run data is mixed into real metrics.
- Missing data appears without a reason.

## Review Focus Points

- Verify P38 is strictly bounded to analysis/regression and did not create runtime evidence.
- Check every required P38 output exists and is populated from P30-P37/coverage registry only.
- Spot-check row provenance from each CSV back to source artifacts and coverage IDs.
- Confirm all real 50/100/200 management, fault, and lifecycle rows are represented.
- Confirm all >200 rows are explicitly dry-run-only.
- Confirm assertion scripts fail closed and were strengthened rather than weakened.
- Confirm missing-data handling uses allowed states with reasons and no invented values.
