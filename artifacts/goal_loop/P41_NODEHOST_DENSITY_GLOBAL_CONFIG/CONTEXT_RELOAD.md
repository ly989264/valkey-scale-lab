# CONTEXT_RELOAD — P41_NODEHOST_DENSITY_GLOBAL_CONFIG

## Stage identity

- Stage ID: P41_NODEHOST_DENSITY_GLOBAL_CONFIG
- Branch: codex/valkey-scale-lab-loop
- Date/time: 2026-07-06T14:05:18Z
- Current harness next output: COMPLETE_AUTOMATIC_PHASES
- Git status summary:

```text
## codex/valkey-scale-lab-loop...origin/codex/valkey-scale-lab-loop
?? artifacts/gates/P14_SCALE_1000_OPTIN_DRYRUN/
?? artifacts/harness_exception/P41_NODEHOST_DENSITY_GLOBAL_CONFIG.md
?? artifacts/phases/P14_SCALE_1000_OPTIN_DRYRUN/
?? docs/codex/goal-loop/stages/P41_NODEHOST_DENSITY_GLOBAL_CONFIG.md
```

## Documents reread

| Document | Read? | Notes |
|---|---:|---|
| AGENTS.md | yes | Strict safety, document reload, real evidence, and strong harness rules apply. |
| CODEX_START_HERE.md | yes | Preserve CLI contract and gate sequence; P14 remains opt-in. |
| CODEX_GOAL_LOOP_START.md | yes | Real evidence and project-scoped Docker operations only. |
| docs/codex/02_PHASES.md | yes | Phase plan requires schema/artifact-first gates. |
| docs/codex/04_AUDITOR.md | yes | Fresh-context review must inspect artifacts and diff. |
| docs/codex/goal-loop/00_INDEX.md | yes | Required read order confirmed. |
| docs/codex/goal-loop/01_GOAL_CONTRACT.md | yes | No fake real evidence; missing values encoded explicitly. |
| docs/codex/goal-loop/02_STAGE_MANIFEST.md | yes | Common stage artifacts/gates inform P41 harness additions. |
| docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md | yes | Design, worker, and review handoffs required. |
| docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md | yes | Markdown handoff artifacts are required. |
| docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md | yes | Assertions must fail closed. |
| docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md | yes | Artifacts must encode missing/skipped values, never invent metrics. |
| docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md | yes | Management rows must keep workload/topology refs. |
| docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md | yes | Fault/failover coverage must remain real at 30/50/100/200 and dry-run-only above 200. |
| docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md | yes | 200 is bounded; >200 remains dry-run unless future resource policy allows real. |
| docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md | yes | No commit before gates, review, postcheck, mark-complete. |
| docs/codex/goal-loop/stages/P41_NODEHOST_DENSITY_GLOBAL_CONFIG.md | yes | Added from the user-provided stage contract because it was absent. |

## Current stage contract summary

- Required implementation: Add global nodehost density config and shared config merge; use density-limited nodehost planning in planner/runtime/resource preflight/fake/real/dry-run paths; emit nodehost density evidence into run state, cluster plan, resource preflight, cleanup, phase/report artifacts.
- Required gates: unit/integration coverage, schema validation, new fail-closed nodehost assertion scripts, and small real smoke when Docker resources permit; 30/50/100/200 real evidence must be checked from real artifacts, not faked.
- Required artifacts: `phase_summary.json`, `nodehost_density_plan.json`, `resource_preflight.json`, `run_state.json`, `cluster_plan.json`, `coverage_ledger.json`, `analysis_summary.json`, `report_index.json`, plus handoff/review/audit artifacts.
- Explicit non-goals: no host network mutation, no default >100 scale increase, no >200 real execution enablement, no downshift from 200 to 100, no dry-run evidence presented as real.

## Risks and assumptions

- Safety risks: nodehost container count increases for 100/200; preflight must fail closed on max nodehost, memory, FD, and port checks.
- Resource risks: local Docker may not be able to run all 30/50/100/200 real gates in this turn; if unavailable, artifacts must encode blocked/skipped reason rather than fake real evidence.
- `待验证` items: exact harness manifest integration for P41, whether Docker is available locally, and how many existing committed real artifacts need regeneration versus validator compatibility checks.

## Handoff to design subagent

- Design prompt path: docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md
- Stage doc path: docs/codex/goal-loop/stages/P41_NODEHOST_DENSITY_GLOBAL_CONFIG.md
- Notes: P41 was absent from the goal-loop stage directory; `artifacts/harness_exception/P41_NODEHOST_DENSITY_GLOBAL_CONFIG.md` records the harness defect and strengthening patch.
