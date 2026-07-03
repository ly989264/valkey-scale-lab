# CONTEXT_RELOAD - P24_PARTITION_SPLIT_BRAIN_MATRIX

## Stage identity

- Stage ID: P24_PARTITION_SPLIT_BRAIN_MATRIX
- Branch: codex/valkey-scale-lab-loop
- Date/time: 2026-07-03 09:39:15 +0800
- Current harness next output: P24_PARTITION_SPLIT_BRAIN_MATRIX
- Git status summary: clean before creating this context reload artifact

## Documents reread

| Document | Read? | Notes |
|---|---:|---|
| AGENTS.md | yes | Real Valkey proof, no host network mutation, and strict stage loop remain controlling. |
| CODEX_START_HERE.md | yes | Continue the next incomplete automatic stage and use codex_gate sequence. |
| CODEX_GOAL_LOOP_START.md | yes | User requires partition, minority/majority, split-brain window, and workload impact. |
| docs/codex/02_PHASES.md | yes | P24 pass criteria require explicit partition groups and detector-backed split-brain reporting. |
| docs/codex/04_AUDITOR.md | yes | Fresh-context review/audit must inspect gates, artifacts, schemas, and diffs. |
| docs/codex/goal-loop/00_INDEX.md | yes | Required read order and Markdown handoff artifacts. |
| docs/codex/goal-loop/01_GOAL_CONTRACT.md | yes | Completion requires all P15-P26 stages through P26, review PASS, mark-complete, commit, and push. |
| docs/codex/goal-loop/02_STAGE_MANIFEST.md | yes | P24 is real-Valkey, automatic, max 100 nodes, depends on P23. |
| docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md | yes | Must run design, worker, and review subagents; close each after use. |
| docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md | yes | This context reload must precede design. |
| docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md | yes | Split-brain window may be zero only when detectors actually ran. |
| docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md | yes | Fault rows need canonical timing, workload windows, events, metrics, and missing-data semantics. |
| docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md | yes | Management scope is non-goal for P24 except preserving prior behavior. |
| docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md | yes | P24 rows are network partition, minority/majority partition, and split-brain window. |
| docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md | yes | Default cap remains 100; no 1000-node path; safe degradation cannot replace real Valkey. |
| docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md | yes | No commit until run, review, postcheck, and mark-complete pass. |
| docs/codex/goal-loop/stages/P24_PARTITION_SPLIT_BRAIN_MATRIX.md | yes | Stage-specific contract for partition report, split-brain report, topology snapshots, workload impact, and cleanup. |
| artifacts/goal_loop/STAGE_JOURNAL.md | yes | P23 handoff says P24 should build on sandbox proxy and command-log safety checks. |

## Current stage contract summary

- Required implementation: partition group planner from live topology/roles/slots/AZs/hosts; traffic block between explicit groups while preserving within-group traffic; probes from both sides where feasible; minority/majority availability measurement; split-brain detectors from the fault matrix spec; workload windows; partition clear/recovery timing; cleanup verification.
- Required gates: manifest precheck, safety scan, compile, unit/integration tests, goal-loop assertion, real `scripts/fault_safety_gate.py` wrapper, quant assertion, fault matrix assertion, split-brain assertion, workload impact assertion, cleanup report check, fresh-context review, postcheck, mark-complete.
- Required artifacts: `phase_summary.json`, `valkey_e2e_evidence.json`, `cleanup_report.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `quant_summary.json`, `partition_report.json`, `split_brain_report.json`, `fault_results.jsonl`, `fault_topology_snapshots.jsonl`, and `workload_impact_report.json`.
- Explicit non-goals: do not reimplement P23 delay/loss/flap as the P24 deliverable; do not claim `split_brain_window_ms=0` unless detectors ran; do not use host firewall, global routing, PF, nftables, iptables, host interfaces, sudo network mutation, or fake-only evidence.

## Risks and assumptions

- Safety risks: partition behavior must be implemented through owned container namespaces or a project-owned sandbox/proxy layer, never through physical host network mutation.
- Resource risks: real evidence should be bounded to local safe node counts unless resource preflight supports larger optional rows; any required real gate failure must block rather than pass with fake data.
- `待验证` items: whether existing P23 sandbox proxy can express bidirectional group partition semantics; how to probe both partition sides in a single-controller local run; which detectors can be fully run and which, if any, must be recorded as `MISSING` with reason.

## Handoff to design subagent

- Design prompt path: docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md
- Stage doc path: docs/codex/goal-loop/stages/P24_PARTITION_SPLIT_BRAIN_MATRIX.md
- Notes: Focus the design on explicit group partition evidence, detector-backed split-brain measurement, workload impact, and cleanup, while preserving P23 command-log safety and avoiding host network mutation.
