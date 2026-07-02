# CONTEXT_RELOAD - P19_MANAGEMENT_ROLLING_RESTART

## Stage identity

- Stage ID: P19_MANAGEMENT_ROLLING_RESTART
- Branch: codex/valkey-scale-lab-loop
- Date/time: 2026-07-02T17:23:43Z
- Current harness next output: P19_MANAGEMENT_ROLLING_RESTART
- Git status summary: clean

## Documents reread

| Document | Read? | Notes |
|---|---:|---|
| AGENTS.md | yes | Controlling goal-loop, safety, real-evidence, and multi-agent instructions. |
| CODEX_START_HERE.md | yes | Confirms `codex_gate.py next`, per-stage gate sequence, and P15-P26 completion condition. |
| CODEX_GOAL_LOOP_START.md | yes | Confirms operator approvals and no host-network mutation boundary. |
| docs/codex/02_PHASES.md | yes | P19 requires deterministic rolling restart with health gates and workload measurement. |
| docs/codex/04_AUDITOR.md | yes | Fresh-context review/audit must inspect gates, artifacts, schemas, and diffs. |
| docs/codex/goal-loop/00_INDEX.md | yes | Confirms required read order and mandatory stage artifacts. |
| docs/codex/goal-loop/01_GOAL_CONTRACT.md | yes | Rolling restart is part of the required management matrix and must be real, not simulated. |
| docs/codex/goal-loop/02_STAGE_MANIFEST.md | yes | P19 is automatic, real-Valkey, max 10 nodes, after P18. |
| docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md | yes | Requires design, worker, gate, review, postcheck, mark-complete, commit, push. |
| docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md | yes | Defines context reload, design brief, worker summary, review, completion, and journal handoff. |
| docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md | yes | Assertions must fail closed and verify management rows, workload impact, cleanup, and real Valkey. |
| docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md | yes | Requires canonical event, metric, workload, management timing, and missing-data fields. |
| docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md | yes | Rolling restart requires deterministic order, one-at-a-time/safe batch, inter-node health gates, replica-first default, primary-safe unavailability/recovery, workload deltas, and cleanup. |
| docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md | yes | Fault matrix is future work; P19 must not drift into P20-P26. |
| docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md | yes | P19 remains max 10 nodes; no 1000-node run and no unrelated large-scale preflight required. |
| docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md | yes | Commit only after gates, review PASS, postcheck, mark-complete; push before next stage. |
| docs/codex/goal-loop/stages/P19_MANAGEMENT_ROLLING_RESTART.md | yes | Authoritative P19 rows and artifacts. |
| artifacts/goal_loop/STAGE_JOURNAL.md | yes | Journal currently records P15-P16; P17/P18/P19 completion entries must be restored before P19 commit. |

## Current stage contract summary

- Required implementation: implement and quantify real rolling restart behavior for `rolling_restart_replica_first` and `rolling_restart_primary_safe` on 6-node and 10-node Valkey clusters.
- Required behavior: deterministic restart order; one node at a time or explicitly safe batch; per-node restart events; health gate before the next node restarts; safe primary restart path with promotion/unavailability/recovery measurement if failover occurs; workload windows during restarts and whole operations; post-restart topology verification and cleanup.
- Required gates: precheck, safety static scan, script compile, unit/integration tests, goal-loop stage assertion, real Valkey e2e with `management_rolling_restart`, quant assertion, management ops assertion, workload impact assertion, cleanup assertion, review/audit, postcheck, mark-complete.
- Required artifacts: `phase_summary.json`, `valkey_e2e_evidence.json`, `cleanup_report.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `quant_summary.json`, `management_ops_matrix.json`, `management_operation_results.jsonl`, `management_workload_impact.json`, `management_topology_snapshots.jsonl`, `management_command_log.jsonl`, `rolling_restart_plan.json`, and `rolling_restart_results.jsonl`.
- Explicit non-goals: do not implement P20 failover latency curves, P21 200-node scale, P22-P24 fault matrix rows, P25 consolidation, or P26 reports; do not mutate host networking; do not run 1000 nodes.

## Risks and assumptions

- Safety risks: restart control must target only owned Docker containers/processes created by the runtime; no host process or host network mutation is allowed.
- Resource risks: P19 requires 6-node and 10-node real clusters; if Docker or ports are unavailable the stage is blocked rather than faked.
- `待验证` items: whether existing restart helpers provide deterministic container restart with stable endpoint recovery; whether schemas/assertions already validate `rolling_restart_plan.json` and `rolling_restart_results.jsonl`; whether current management assertions need P19-specific strengthening for inter-node health gates and operation rows; whether P17/P18 journal entries need reconstruction before P19 completion.

## Handoff to design subagent

- Design prompt path: docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md
- Stage doc path: docs/codex/goal-loop/stages/P19_MANAGEMENT_ROLLING_RESTART.md
- Notes: Design must inspect P17/P18 runtime patterns in `src/valkey_scale_lab/runtime/docker_runtime.py`, P19 manifest gates, existing rolling restart schemas, management coverage assertions, workload impact assertions, and unit tests before proposing changes.
