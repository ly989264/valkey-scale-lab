# CONTEXT_RELOAD - P31_MANAGEMENT_MATRIX_100_REAL

## Stage

- Stage ID: P31_MANAGEMENT_MATRIX_100_REAL
- Stage title: Real 100-node management matrix
- Branch: codex/valkey-scale-lab-loop
- Current commit: db0771400faea7a22bdabd39c6f3506316e55c09
- Date/time: 2026-07-04 01:08:22 +0800

## Harness status

```text
python3 scripts/codex_gate.py next
P31_MANAGEMENT_MATRIX_100_REAL
```

## Git status

```text
git status --short
```

The working tree was clean before this context reload artifact was written.

## Documents Reread

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
- [x] docs/codex/goal-loop-strict/stages/P31_MANAGEMENT_MATRIX_100_REAL.md
- [x] artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md

## Current Stage Contract Summary

P31 must execute and quantify the complete management operation matrix on exactly 100 real Valkey 9.1.x nodes. It must not downshift. Resource preflight must report `can_run=true`, and the stage must block rather than pass if 100 nodes cannot be supported.

Required management rows are `create_cluster`, `meet_nodes`, `add_replica`, `remove_replica`, `remove_primary_drained_or_safe_replaced`, `remove_failed_node`, `reshard_slot_range`, `reshard_with_keys`, `rebalance_after_imbalance`, `rolling_restart_replica_first`, and `rolling_restart_primary_safe`. Required rows cannot be skipped in a passing stage.

Required artifacts include the common real-stage artifact family plus `management_ops_matrix.json`, `management_operation_results.jsonl`, `management_topology_snapshots.jsonl`, `management_command_log.jsonl`, and `management_workload_impact.json` under `artifacts/phases/P31_MANAGEMENT_MATRIX_100_REAL/`.

Required gates include exact-scale real evidence for 100 nodes, strict management matrix validation, management quant completeness, coverage registry validation, anti-bypass, and cleanup validation. Review must be fresh-context and record `Decision: PASS` before postcheck and mark-complete.

## Prior-Stage Handoff Summary

P30 proved the exact 50-node management matrix using real Valkey 9.1.0 and produced 11 PASS management operation rows, 154 events, 1452 metric samples, 66 workload windows, exact-scale e2e evidence with 50 observed nodes, and cleanup PASS. P31 should carry forward P30's operation semantics, telemetry schema, null-free missing-data encoding, coverage ledger shape, and stricter validation behavior while scaling to exactly 100 nodes.

## Known Blockers

None known at reload time. The stage remains subject to resource preflight and Docker/runtime availability when the real 100-node gate runs.

## Assumptions and 待验证 Items

- 待验证: the P30 process-runtime management matrix can be generalized to the P31 scenario without weakening exact-scale checks.
- 待验证: local Docker/runtime resources can support exactly 100 Valkey nodes with a low but non-zero workload.
- 待验证: P31 manifest/gate entries already include the necessary strict management assertions or can be strengthened without weakening harness controls.
