# CONTEXT_RELOAD - P38_CROSS_SCALE_ANALYSIS_REGRESSION

## Stage

- Stage ID: `P38_CROSS_SCALE_ANALYSIS_REGRESSION`
- Current branch: `codex/valkey-scale-lab-loop`
- Current commit: `8e4ccf3`
- Harness next output: `P38_CROSS_SCALE_ANALYSIS_REGRESSION`
- `git status --short`: clean

## Required Documents Reread

1. `AGENTS.md`
2. `CODEX_START_HERE.md`
3. `CODEX_GOAL_LOOP_START.md`
4. `CODEX_STRICT_MATRIX_LOOP_START.md`
5. `docs/codex/goal-loop/00_INDEX.md`
6. `docs/codex/goal-loop/01_GOAL_CONTRACT.md`
7. `docs/codex/goal-loop/02_STAGE_MANIFEST.md`
8. `docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md`
9. `docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md`
10. `docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md`
11. `docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md`
12. `docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md`
13. `docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md`
14. `docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md`
15. `docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md`
16. `docs/codex/goal-loop-strict/00_INDEX.md`
17. `docs/codex/goal-loop-strict/01_STRICT_GOAL_CONTRACT.md`
18. `docs/codex/goal-loop-strict/02_STRICT_STAGE_MANIFEST.md`
19. `docs/codex/goal-loop-strict/03_MAIN_SUBAGENT_LOOP_PROTOCOL.md`
20. `docs/codex/goal-loop-strict/04_CONTEXT_LEDGER_PROTOCOL.md`
21. `docs/codex/goal-loop-strict/05_FAIL_CLOSED_HARNESS_CONTRACT.md`
22. `docs/codex/goal-loop-strict/06_COVERAGE_REGISTRY_SPEC.md`
23. `docs/codex/goal-loop-strict/07_QUANTIFICATION_DATA_CONTRACT.md`
24. `docs/codex/goal-loop-strict/08_MANAGEMENT_OPERATION_MATRIX_SPEC.md`
25. `docs/codex/goal-loop-strict/09_FAULT_FAILOVER_MATRIX_SPEC.md`
26. `docs/codex/goal-loop-strict/10_SCALE_EXECUTION_POLICY.md`
27. `docs/codex/goal-loop-strict/11_ANALYSIS_VISUAL_REPORT_SPEC.md`
28. `docs/codex/goal-loop-strict/12_AUDIT_COMMIT_NO_BYPASS_POLICY.md`
29. `docs/codex/goal-loop-strict/stages/P38_CROSS_SCALE_ANALYSIS_REGRESSION.md`
30. `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md`

## Stage Contract Summary

P38 is an analysis and regression stage. It must not start new large clusters or mutate runtime/network state. It must consume only validated artifacts from P30 through P37 plus `artifacts/coverage/strict_coverage_registry.json`.

Required stage-doc outputs include cross-scale summary JSON, coverage heatmap CSV, management latency/convergence CSVs, failover curve CSV, fault impact CSV, workload window CSV, resource usage CSV, cleanup CSV, missing-data CSV, analysis provenance JSON, regression baseline JSON, quant summary JSON, and phase summary JSON. Manifest-required artifacts are `phase_summary.json`, `analysis_provenance.json`, `regression_baseline.json`, and `quant_summary.json`; the stage document is stricter and controls the implementation scope.

P38 passes only when every real 50/100/200 row is represented in analysis outputs, every >200 row is represented as dry-run-only, source provenance exists for every derived value, missing data is encoded with reasons, percentile/delta methods are declared, and no `NaN`, `null`, `undefined`, fake metric, or unvalidated-log-derived final value appears.

## Prior Stage Journal Summary

P30-P32 completed exact-scale management rows for 50, 100, and 200 nodes. P33-P35 completed exact-scale fault/failover rows for 50, 100, and 200 nodes. P36 completed lifecycle/full-flow rows for all three real scales. P37 completed all 40 >200 dry-run rows for 201, 250, 300, 500, and 1000 with no-runtime proof. P38 must aggregate these validated artifacts and prepare P39/P40 report/regression inputs.

## Known Blockers

None known at reload time. The stage must block if source artifacts are absent, not PASS, unvalidated, missing provenance, or if analysis tables omit required scale/row coverage.

## Assumptions And 待验证

- 待验证: current `scripts/assert_analysis_provenance.py` and `scripts/assert_quant_completeness.py --category analysis` requirements must be inspected before worker implementation.
- 待验证: whether existing analysis/report modules can be reused or whether a P38-specific deterministic generator is the smallest safe path.
- 待验证: P38 may need to strengthen assertions if existing gates do not validate the full stage-doc table set.
