# CONTEXT_RELOAD — P32_MANAGEMENT_MATRIX_200_REAL

Reloaded at: 2026-07-04 03:48:51 +0800
Workspace: `/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab`
Current commit before P32 work: `ec4bd12d1a81f7956ce74779cd0a7eff670dc131`
Current stage from `python3 scripts/codex_gate.py next`: `P32_MANAGEMENT_MATRIX_200_REAL`

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
29. `docs/codex/goal-loop-strict/stages/P32_MANAGEMENT_MATRIX_200_REAL.md`
30. `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md`

No required document was absent during reload.

## Stage Contract Summary

P32 must execute the complete strict management matrix on exactly 200 real Valkey 9.1.x nodes. A 100-node or dry-run substitute is a failure. The user-required 200-node bounded exception applies only if resource preflight passes, and it does not alter the normal 100-node development default.

Required management rows:

- `create_cluster`
- `meet_nodes`
- `add_replica`
- `remove_replica`
- `remove_primary_drained_or_safe_replaced`
- `remove_failed_node`
- `reshard_slot_range`
- `reshard_with_keys`
- `rebalance_after_imbalance`
- `rolling_restart_replica_first`
- `rolling_restart_primary_safe`

Each row may update the strict coverage registry to `PASS` only when it is backed by exact-scale real Valkey evidence, row artifacts, workload impact, telemetry, and cleanup.

## Required P32 Artifacts

The stage must produce and validate:

- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/phase_summary.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/valkey_e2e_evidence.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/resource_preflight.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/cluster_plan.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/run_state.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/cleanup_report.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/events.jsonl`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/metrics_timeseries.jsonl`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/workload_windows.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/quant_summary.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/coverage_ledger.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/management_ops_matrix.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/management_operation_results.jsonl`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/management_topology_snapshots.jsonl`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/management_command_log.jsonl`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/management_workload_impact.json`

## Required Gates

P32 required gates include:

- `python3 scripts/assert_exact_scale_real_evidence.py --phase P32_MANAGEMENT_MATRIX_200_REAL --nodes 200`
- `python3 scripts/assert_management_matrix_strict.py --phase P32_MANAGEMENT_MATRIX_200_REAL --scale 200 --require-all-rows`
- `python3 scripts/assert_quant_completeness.py --phase P32_MANAGEMENT_MATRIX_200_REAL --category management --scale 200`
- `python3 scripts/assert_coverage_registry.py --phase P32_MANAGEMENT_MATRIX_200_REAL --scale 200 --category management`
- `python3 scripts/assert_no_bypass.py --phase P32_MANAGEMENT_MATRIX_200_REAL`
- `python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/cleanup_report.json`

The manifest gate run, postcheck, and mark-complete must pass before any P32 commit.

## Safety And Blocking Rules

- Do not fake real Valkey evidence.
- Do not downshift P32 from 200 nodes.
- Do not run real clusters above 200 nodes.
- Do not mutate host network configuration.
- Do not manually edit gate results or phase state to force pass.
- If resource preflight reports `can_run=false`, write `BLOCKED.md`, do not mark complete, do not create a passing commit, and stop the loop.
- Missing values must be represented as `MISSING` or `SKIPPED_WITH_REASON` with a reason where allowed; required P32 real rows cannot pass as skipped.

## Subagent Sequence Required

For P32, the main agent must:

1. Write this `CONTEXT_RELOAD.md`.
2. Launch a design subagent with `docs/codex/goal-loop-strict/prompts/DESIGN_SUBAGENT_PROMPT.md`.
3. Launch a worker subagent with `docs/codex/goal-loop-strict/prompts/WORKER_SUBAGENT_PROMPT.md`.
4. Run gates and inspect artifacts.
5. Launch a review subagent with `docs/codex/goal-loop-strict/prompts/REVIEW_SUBAGENT_PROMPT.md`.
6. Close each subagent before stage commit and push.
7. Run postcheck and mark-complete only after review passes.
8. Commit exactly P32, push, then update completion/journal as required by the strict loop.

## Prior Strict Journal Handoff

P31 completed exact 100-node real management coverage with 11 PASS management rows, exact-scale Valkey 9.1.0 evidence, 154 events, 1452 metrics, 66 workload windows, cleanup PASS, and gate result SHA `0cddf5b1855fe156e41f85d92abeae8f4534bac069c6a37a153a1ca2106bc8cb`. P32 must carry those operation semantics to exactly 200 nodes after resource preflight passes.
