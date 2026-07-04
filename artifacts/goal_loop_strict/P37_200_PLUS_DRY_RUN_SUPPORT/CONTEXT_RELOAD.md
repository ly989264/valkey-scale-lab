# CONTEXT_RELOAD - P37_200_PLUS_DRY_RUN_SUPPORT

## Stage

- Stage ID: `P37_200_PLUS_DRY_RUN_SUPPORT`
- Current branch: `codex/valkey-scale-lab-loop`
- Current commit: `8c9d987fb822a66772b7ff34fe8bb47735e8ea42`
- Harness next output: `P37_200_PLUS_DRY_RUN_SUPPORT`
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
29. `docs/codex/goal-loop-strict/stages/P37_200_PLUS_DRY_RUN_SUPPORT.md`
30. `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md`

## Stage Contract Summary

P37 must support targets above 200 nodes through dry-run planning only. Required targets are `201`, `250`, `300`, `500`, and `1000`. For each target the stage must produce config validation, resource estimates, cluster plan, host/AZ placement schedule, port and directory collision checks, artifact schema projection, report projection, and no-runtime-created proof.

Every >200 artifact must use `execution_mode=dry_run` and clearly avoid real Valkey claims. P37 must prove no containers, live endpoints, or workloads were created above 200 by recording runtime inventory before and after dry-run execution. Coverage registry rows for >200 dry-run IDs must end in `DRY_RUN_PASS`, with source artifacts, validation artifacts, and no-runtime proof.

## Prior Stage Journal Summary

P27-P36 are complete and pushed through commit `8c9d987fb822a66772b7ff34fe8bb47735e8ea42`. P36 added all 36 lifecycle rows for 50/100/200 exact real clusters and handed off to P37 with a hard requirement to prove dry-run-only behavior for 201/250/300/500/1000.

## Known Blockers

None known at reload time. A blocker must be declared if any >200 target starts real containers, claims real Valkey evidence, lacks no-runtime proof, or is marked as real execution.

## Assumptions And 待验证

- 待验证: existing P37 harness dispatch and `assert_200_plus_dry_run.py` coverage semantics must be inspected before implementation.
- 待验证: planner/resource code must already reject real execution above 200; if not, P37 must strengthen the guard without weakening the 50/100/200 real stages.
- 待验证: runtime inventory proof should be deterministic and scoped to owned project resources so unrelated local containers do not affect the stage.
