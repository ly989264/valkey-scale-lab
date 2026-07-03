# CONTEXT_RELOAD - P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER

## Stage

- Stage ID: P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER
- Stage title: Coverage registry and scenario compiler
- Branch: codex/valkey-scale-lab-loop
- Current commit: eea19d2611ebbda9fe56572f61280ac65ec886f9
- Date/time: 2026-07-03

## Harness status

```text
python3 scripts/codex_gate.py next
P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER
```

P28 is current because P27 was postchecked, marked complete, committed, and pushed. `codex/status/phase_state.json` now includes `P27_STRICT_MATRIX_REBASE_HARNESS`.

## Git status

```text
git status --short
<clean before this CONTEXT_RELOAD.md was written>
```

## Documents reread

- [x] AGENTS.md
- [x] CODEX_START_HERE.md
- [x] CODEX_GOAL_LOOP_START.md
- [x] CODEX_STRICT_MATRIX_LOOP_START.md
- [x] docs/codex/goal-loop/00_INDEX.md
- [x] docs/codex/goal-loop/01_GOAL_CONTRACT.md
- [x] docs/codex/goal-loop/02_STAGE_MANIFEST.md
- [x] docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md
- [x] docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md
- [x] docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md
- [x] docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md
- [x] docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md
- [x] docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md
- [x] docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md
- [x] docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md
- [x] docs/codex/goal-loop-strict/00_INDEX.md
- [x] docs/codex/goal-loop-strict/01_STRICT_GOAL_CONTRACT.md
- [x] docs/codex/goal-loop-strict/02_STRICT_STAGE_MANIFEST.md
- [x] docs/codex/goal-loop-strict/03_MAIN_SUBAGENT_LOOP_PROTOCOL.md
- [x] docs/codex/goal-loop-strict/04_CONTEXT_LEDGER_PROTOCOL.md
- [x] docs/codex/goal-loop-strict/05_FAIL_CLOSED_HARNESS_CONTRACT.md
- [x] docs/codex/goal-loop-strict/06_COVERAGE_REGISTRY_SPEC.md
- [x] docs/codex/goal-loop-strict/07_QUANTIFICATION_DATA_CONTRACT.md
- [x] docs/codex/goal-loop-strict/08_MANAGEMENT_OPERATION_MATRIX_SPEC.md
- [x] docs/codex/goal-loop-strict/09_FAULT_FAILOVER_MATRIX_SPEC.md
- [x] docs/codex/goal-loop-strict/10_SCALE_EXECUTION_POLICY.md
- [x] docs/codex/goal-loop-strict/11_ANALYSIS_VISUAL_REPORT_SPEC.md
- [x] docs/codex/goal-loop-strict/12_AUDIT_COMMIT_NO_BYPASS_POLICY.md
- [x] docs/codex/goal-loop-strict/stages/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER.md
- [x] artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md

## Current stage contract summary

P28 must create the canonical strict coverage matrix and deterministic scenario plans for later stages. Required outputs are `artifacts/coverage/strict_coverage_registry.json`, `artifacts/coverage/strict_required_matrix.csv`, `artifacts/coverage/strict_scenario_plan.json`, `artifacts/phases/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER/coverage_registry_report.json`, `phase_summary.json`, and `quant_summary.json`.

The registry must contain every real 50/100/200 lifecycle, management, and fault row from the strict coverage, management, and fault specs. Real rows must start as `PENDING`, not `PASS`; no real evidence is claimed by P28. The registry must also include >200 dry-run rows for 201, 250, 300, 500, and 1000 with `execution_mode=dry_run`; no row may permit real >200 execution. Scenario plans must map rows to later stages and include node count, preflight, workload profile, operation/fault sequence, timeout policy, cleanup policy, expected artifacts, and coverage IDs.

## Prior-stage handoff summary

P27 added the strict P27-P40 manifest and fail-closed harness surface. The strict journal says P28 should materialize the coverage registry and deterministic scenario plan without claiming runtime coverage. P27 left all real 50/100/200 lifecycle, management, fault, telemetry, analysis, report, and cleanup matrix cells unsatisfied.

## Known blockers

- None yet. P28 is non-runtime and should not require Docker or live Valkey.
- If the required matrix cannot be generated deterministically from the strict specs, the stage must block rather than emit partial coverage.

## Assumptions and 待验证 items

- 待验证: whether P27's bootstrap `assert_coverage_registry.py` already has enough structure to validate full P28 registry outputs or needs strengthening.
- 待验证: whether the existing `strict_coverage_registry.schema.json` is sufficient for the final registry artifact or needs a richer schema.
- 待验证: exact scenario plan shape that best supports P30-P37 while staying deterministic and not over-claiming runtime readiness.
