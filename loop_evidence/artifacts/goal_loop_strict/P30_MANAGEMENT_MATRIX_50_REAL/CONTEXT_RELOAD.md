# CONTEXT_RELOAD - P30_MANAGEMENT_MATRIX_50_REAL

## Stage

- Stage ID: P30_MANAGEMENT_MATRIX_50_REAL
- Stage title: Real 50-node management matrix
- Branch: codex/valkey-scale-lab-loop
- Current commit: a6e5f44
- Date/time: 2026-07-03

## Harness status

```text
python3 scripts/codex_gate.py next
P30_MANAGEMENT_MATRIX_50_REAL
```

P30 is current because P29 was postchecked, marked complete, committed, and pushed. The worktree was clean before this context reload was written.

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
- [x] docs/codex/goal-loop-strict/stages/P30_MANAGEMENT_MATRIX_50_REAL.md
- [x] artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md

## Current stage contract summary

P30 must execute the complete management matrix on exactly 50 real Valkey nodes. It must not downshift. If resource preflight cannot support 50 nodes, the stage must write `BLOCKED.md` and stop without passing.

Required rows are `create_cluster`, `meet_nodes`, `add_replica`, `remove_replica`, `remove_primary_drained_or_safe_replaced`, `remove_failed_node`, `reshard_slot_range`, `reshard_with_keys`, `rebalance_after_imbalance`, `rolling_restart_replica_first`, and `rolling_restart_primary_safe`. Each row can be `PASS` only with real 50-node execution, row source artifacts, verification checks, workload impact, telemetry, and cleanup.

Required artifacts include real evidence, resource preflight, cluster plan, run state, cleanup, strict telemetry JSONL/windows, quant summary, coverage ledger, management operation matrix, operation results JSONL, topology snapshots, command log, and workload impact report. Required gates include exact 50-node evidence, strict management matrix coverage, quant completeness, coverage registry update for `50.management.*`, no-bypass, and cleanup.

## Prior-stage handoff summary

P28 created the strict registry and scenario plan. P29 hardened telemetry with a 6-node real proof and left all strict registry rows `PENDING`. P30 must now update only the `50.management.*` rows to `PASS` after real execution at exactly 50 nodes, while preserving no host-network mutation and deterministic cleanup.

## Known blockers

- None confirmed yet. P30 may block if resource preflight cannot run exactly 50 nodes on the current Docker/runtime environment.

## Assumptions and 待验证 items

- 待验证: whether existing runtime management operation helpers already support every strict 50-node row or need current-stage strengthening.
- 待验证: whether `scripts/valkey_e2e_gate.py` plus runtime scenario `strict_management_matrix_50` already emits all P30 management artifacts.
- 待验证: whether the current machine can pass resource preflight for exactly 50 real Valkey nodes without downshifting.
