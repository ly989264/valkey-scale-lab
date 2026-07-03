# CONTEXT_RELOAD - P23_FAULT_NETWORK_DELAY_LOSS_FLAP

## Stage identity

- Stage ID: P23_FAULT_NETWORK_DELAY_LOSS_FLAP
- Branch: codex/valkey-scale-lab-loop
- Date/time: 2026-07-03 09:02:53 +0800
- Current harness next output: P23_FAULT_NETWORK_DELAY_LOSS_FLAP
- Git status summary: clean before creating this context reload artifact

## Documents reread

| Document | Read? | Notes |
|---|---:|---|
| AGENTS.md | yes | Goal-loop harness rules, no host network mutation, real Valkey proof required. |
| CODEX_START_HERE.md | yes | Continue next incomplete automatic stage and use codex_gate sequence. |
| CODEX_GOAL_LOOP_START.md | yes | User requires delay/loss/flap plus workload impact under strong harness. |
| docs/codex/02_PHASES.md | yes | P23 pass criteria require sandboxed network faults and no host firewall/routing/interface mutation. |
| docs/codex/04_AUDITOR.md | yes | Fresh-context review/audit must inspect gates, artifacts, schemas, and diffs. |
| docs/codex/goal-loop/00_INDEX.md | yes | Required read order and mandatory Markdown handoff artifacts. |
| docs/codex/goal-loop/01_GOAL_CONTRACT.md | yes | Completion requires all P15-P26 stages through P26, review PASS, mark-complete, commit, and push. |
| docs/codex/goal-loop/02_STAGE_MANIFEST.md | yes | P23 is real-Valkey, automatic, max 100 nodes, depends on P22. |
| docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md | yes | Must run design, worker, and review subagents; close them after use. |
| docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md | yes | This file must externalize stage state before design. |
| docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md | yes | Network fault gate requires safe implementation path and fails host-level mutation. |
| docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md | yes | Fault rows need canonical timing, workload windows, events, metrics, and missing-data semantics. |
| docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md | yes | Management scope is non-goal for P23 except preserving prior behavior. |
| docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md | yes | P23 rows are network_delay, network_loss, and network_flap; partition/split-brain remain P24. |
| docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md | yes | Default cap remains 100; no 1000-node path; safe degradation cannot replace real Valkey. |
| docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md | yes | No commit until run, review, postcheck, and mark-complete pass. |
| docs/codex/goal-loop/stages/P23_FAULT_NETWORK_DELAY_LOSS_FLAP.md | yes | Stage-specific contract for delay/loss/flap artifacts and safety review. |
| artifacts/goal_loop/STAGE_JOURNAL.md | yes | P22 handoff says P23 must implement delay/loss/flap through container namespace or sandbox proxy only. |

## Current stage contract summary

- Required implementation: safe implementation path detection for container namespace `tc/netem` or a project-owned sandbox proxy; real network delay, packet loss, and flap rows; apply/clear lifecycle; workload windows; metrics/events; cleanup verification.
- Required gates: manifest precheck, safety scan, compile, unit/integration tests, goal-loop assertion, real `scripts/fault_safety_gate.py` wrapper, quant assertion, fault matrix assertion, workload impact assertion, cleanup report check, fresh-context review, postcheck, mark-complete.
- Required artifacts: `phase_summary.json`, `valkey_e2e_evidence.json`, `cleanup_report.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `quant_summary.json`, `network_fault_report.json`, `fault_results.jsonl`, `workload_impact_report.json`, and `network_fault_command_log.jsonl`.
- Explicit non-goals: do not implement P24 partition/minority/majority/split-brain matrix as the P23 deliverable; do not use host firewall, global routing, PF, nftables, iptables, host interfaces, sudo network mutation, or fake-only evidence.

## Risks and assumptions

- Safety risks: network impairment support must stay inside owned container namespaces or a project-owned proxy; command logs and source must not show host-level mutation.
- Resource risks: P23 may reuse bounded 6/10 and, when safe, 30+ evidence patterns; any required real gate failure from Docker/resource limits must block rather than pass.
- `待验证` items: whether the current Valkey container image has `tc`/netem and permissions inside owned namespaces; whether an existing sandbox proxy path already exists or must be introduced; how current assertions distinguish P23 delay/loss/flap from P24 partition rows.

## Handoff to design subagent

- Design prompt path: docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md
- Stage doc path: docs/codex/goal-loop/stages/P23_FAULT_NETWORK_DELAY_LOSS_FLAP.md
- Notes: Focus the design on the smallest safe real implementation path that exercises delay, loss, and flap while preserving P22 owned-runtime cleanup and not advancing P24 partition/split-brain scope.
