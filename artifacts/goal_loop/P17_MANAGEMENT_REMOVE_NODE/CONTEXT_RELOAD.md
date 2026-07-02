# CONTEXT_RELOAD — P17_MANAGEMENT_REMOVE_NODE

## Stage identity

- Stage ID: P17_MANAGEMENT_REMOVE_NODE
- Branch: codex/valkey-scale-lab-loop
- Date/time: 2026-07-02T16:24:27Z
- Current harness next output: `P17_MANAGEMENT_REMOVE_NODE`
- Git status summary: clean worktree, branch synced with `origin/codex/valkey-scale-lab-loop`
- Current stage reason: `codex/status/phase_state.json` includes P15 and P16; `python3 scripts/codex_gate.py next` returns P17.

## Documents reread

| Document | Read? | Notes |
|---|---:|---|
| AGENTS.md | yes | Safety rules, real evidence requirement, stage reload and subagent loop. |
| CODEX_START_HERE.md | yes | Execute only next incomplete automatic stage and commit/push per stage. |
| CODEX_GOAL_LOOP_START.md | yes | Management matrix and no-downscope requirements. |
| docs/codex/02_PHASES.md | yes | P17 summary follows P16 telemetry foundation. |
| docs/codex/04_AUDITOR.md | yes | Review and legacy audit required for P15-P26. |
| docs/codex/goal-loop/00_INDEX.md | yes | Required read order and stage doc authority. |
| docs/codex/goal-loop/01_GOAL_CONTRACT.md | yes | Remove-node management coverage is a required capability; fake-only evidence cannot pass. |
| docs/codex/goal-loop/02_STAGE_MANIFEST.md | yes | P17 is real-Valkey, max 10 nodes, and depends on P16 telemetry. |
| docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md | yes | Design, worker, gates, review, postcheck, mark-complete, commit/push. |
| docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md | yes | Required P17 Markdown handoff artifacts. |
| docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md | yes | Management rows must fail closed on missing files, fake PASS, missing timing, or invalid cleanup. |
| docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md | yes | P17 must emit canonical events, metrics, workload windows, operation timings, and missing-data reasons. |
| docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md | yes | Remove replica, remove primary with slot drain/safe path, and remove failed node semantics. |
| docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md | yes | Failed-node removal may use project-owned fault/runtime controls; no host mutation. |
| docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md | yes | P17 max 10 nodes; if 10-node execution is blocked by resources, write BLOCKED.md and stop. |
| docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md | yes | Review PASS, postcheck PASS, mark-complete PASS before commit/push. |
| docs/codex/goal-loop/stages/P17_MANAGEMENT_REMOVE_NODE.md | yes | Current stage requires six real operation rows at 6 and 10 nodes. |
| artifacts/goal_loop/STAGE_JOURNAL.md | yes | P16 handoff provides canonical telemetry helpers and workload windows. |

## Current stage contract summary

- Required implementation: safe target selection for replicas and primaries; remove-replica, remove-primary-drained/safe path, and remove-failed-node rows at 6 and 10 nodes; topology snapshots before/during/after; workload windows; command log; cleanup of removed resources; management operation JSONL rows.
- Required operation rows: `remove_replica` on 6 and 10 nodes, `remove_primary_drained` on 6 and 10 nodes, `remove_failed_node` on 6 and 10 nodes.
- Required artifacts: common real artifacts plus `management_ops_matrix.json`, `management_operation_results.jsonl`, `management_workload_impact.json`, `management_topology_snapshots.jsonl`, `management_command_log.jsonl`, `events.jsonl`, `metrics_timeseries.jsonl`, and `quant_summary.json`.
- Required assertions: removed node absent from converged cluster views, full slot coverage after safe removals, workload windows per row, classified errors, no unsupported PASS, cleanup verifies removed resources.
- Explicit non-goals: do not implement P18 reshard/rebalance rows beyond what is required as a safe primary removal path, do not implement rolling restart, failover curves, network faults, partitions, split-brain, 200-node, or 1000-node behavior.

## Risks and assumptions

- Safety risks: primary removal must not be a simple kill plus fake success; failed-node removal must use owned project runtime/fault controls only.
- Resource risks: P17 requires real 6-node and 10-node Valkey execution. If 10-node execution cannot run due to resources, the stage is blocked and cannot pass.
- `待验证` items: existing runtime support for safe node removal and slot draining, available 10-node config or need for a bounded template, whether `scripts/valkey_e2e_gate.py` has a management scenario path for P17, and whether P16 telemetry helpers are reusable without broad runtime refactor.

## Handoff to design subagent

- Design prompt path: `docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md`
- Stage doc path: `docs/codex/goal-loop/stages/P17_MANAGEMENT_REMOVE_NODE.md`
- Notes: design must inspect existing cluster management, fault/runtime controls, telemetry helpers, management assertion script, and real gate wrappers to propose the smallest P17-only implementation that covers all six required rows.
