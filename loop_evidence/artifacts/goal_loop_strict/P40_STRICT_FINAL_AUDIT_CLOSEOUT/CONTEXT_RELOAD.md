# CONTEXT_RELOAD - P40_STRICT_FINAL_AUDIT_CLOSEOUT

## Stage

- Stage ID: `P40_STRICT_FINAL_AUDIT_CLOSEOUT`
- Branch: `codex/valkey-scale-lab-loop`
- Current commit: `1c1d0d2`
- Reload time: `2026-07-05 09:14:18 +0800`
- `python3 scripts/codex_gate.py next`: `P40_STRICT_FINAL_AUDIT_CLOSEOUT`
- `git status --short`: clean before creating this context reload

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
29. `docs/codex/goal-loop-strict/stages/P40_STRICT_FINAL_AUDIT_CLOSEOUT.md`
30. `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md`

Prompt files also reread for subagent launch:

- `docs/codex/goal-loop-strict/prompts/DESIGN_SUBAGENT_PROMPT.md`
- `docs/codex/goal-loop-strict/prompts/WORKER_SUBAGENT_PROMPT.md`
- `docs/codex/goal-loop-strict/prompts/REVIEW_SUBAGENT_PROMPT.md`

## Current Stage Contract Summary

P40 is the final fail-closed audit closeout for the strict P27-P40 loop. It must inspect the manifest, phase state, strict coverage registry, strict journal, P27-P39 gate results, P30-P39 phase artifacts, P27-P39 audits, and P39 final report artifacts. P40 must produce the final audit report, final coverage verdict, artifact manifest, no-bypass report, report-quality verdict, quant summary, phase summary, and `FINAL_STRICT_SUMMARY.md`.

Required P40 gates:

- `python3 scripts/assert_final_strict_closeout.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT`
- `python3 scripts/assert_coverage_registry.py --require-final-real-scales --require-dry-run-200-plus`
- `python3 scripts/assert_no_bypass.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT --scan-all-strict-stages`
- `python3 scripts/assert_report_quality.py --report-index artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json`
- `python3 scripts/assert_analysis_provenance.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT`

P40 passes only if P27-P39 are complete, reviewed, audited, committed, pushed, and backed by PASS gate results; all 50/100/200 lifecycle, management, and fault coverage rows are PASS with exact-scale real evidence; all >200 coverage rows are dry-run-only with no runtime creation; report quality passes; no bypass is detected; and cleanup is PASS for every real execution stage.

## Prior-Stage Journal Summary

- P27 added strict P27-P40 manifest/harness recognition and `automatic_stop_after=P40_STRICT_FINAL_AUDIT_CLOSEOUT`.
- P28 created the 145-row strict coverage registry and deterministic scenario plan.
- P29 hardened telemetry with a bounded 6-node real smoke proof.
- P30, P31, and P32 completed exact 50/100/200 real management matrices.
- P33, P34, and P35 completed exact 50/100/200 real fault/failover matrices.
- P36 completed exact 50/100/200 real lifecycle/full-flow evidence.
- P37 completed dry-run-only support for 201/250/300/500/1000 with no-runtime proof.
- P38 produced cross-scale analysis/regression artifacts from validated sources.
- P39 rendered the final Markdown/HTML visual report and 10 SVG chart assets from P38 artifacts, with a report-quality gate PASS.

## Known Blockers

- None known at reload time.

## Assumptions and 待验证

- 待验证: whether the existing `scripts/assert_final_strict_closeout.py` already emits all required P40 artifacts or requires strengthening.
- 待验证: whether `scripts/assert_analysis_provenance.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT` currently accepts final closeout provenance inputs.
- 待验证: whether P27-P39 completion records include concrete commit/push evidence acceptable to the final closeout gate.
