# CONTEXT_RELOAD - P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY

## Stage identity

- Stage ID: P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY
- Branch: codex/valkey-scale-lab-loop
- Date/time: 2026-07-07T02:24:58Z
- Current harness next output: COMPLETE_AUTOMATIC_PHASES; P44 is user-requested explicit work beyond the completed automatic loop.
- Git status summary: new P44 stage document and harness exception are present; no pre-existing dirty files were observed before this stage work.

## Documents reread

| Document | Read? | Notes |
|---|---:|---|
| AGENTS.md | yes | Controlling safety, strong harness, document reload, and multi-agent stage loop rules. |
| CODEX_START_HERE.md | yes | Requires harness status check, stage-only implementation, real evidence, review, postcheck, mark-complete, commit, and push. |
| CODEX_GOAL_LOOP_START.md | yes | Summarizes operator approvals and forbids host network mutation and fake evidence. |
| docs/codex/02_PHASES.md | yes | Existing phase intent and real Valkey evidence expectations. |
| docs/codex/04_AUDITOR.md | yes | Fresh-context auditor must inspect gates, artifacts, schemas, diffs, and review outputs. |
| docs/codex/goal-loop/00_INDEX.md | yes | Required read order and stage-doc authority. |
| docs/codex/goal-loop/01_GOAL_CONTRACT.md | yes | Completion requires runnable code, validated artifacts, real Valkey evidence for runtime stages, and no fabricated metrics. |
| docs/codex/goal-loop/02_STAGE_MANIFEST.md | yes | P15-P26 manifest model; P44 extends the same fail-closed pattern for explicit requested work. |
| docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md | yes | Requires design, worker, gates, review, postcheck, mark-complete, commit, and push. |
| docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md | yes | Requires CONTEXT_RELOAD, DESIGN_BRIEF, WORKER_SUMMARY, REVIEW, and completion/block files. |
| docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md | yes | Gates must verify capability independently; failover gates require raw sample coverage and real evidence. |
| docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md | yes | Canonical timestamps, workload windows, missing data policy, and failover metrics. |
| docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md | yes | Not directly in scope except preserving management coverage and reports. |
| docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md | yes | Primary stop failover at 30/50/100/200 must be real and sample-derived. |
| docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md | yes | Default max 100; 200 is bounded preflight exception; greater-than-200 remains dry-run projection unless explicitly changed. |
| docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md | yes | No mark-complete or commit before gates, artifacts, review, postcheck. |
| docs/codex/goal-loop/stages/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY.md | yes | Newly created from the user-supplied P44 contract because it was absent. |

## Current stage contract summary

- Required implementation: add a concurrent failover timeline observer, continuous SET/GET client recovery probe, separate PFAIL-to-cluster-OK recovery from client recovery and clean snapshot tail, and make the path scale-generic.
- Required gates: schema/unit/integration tests, real smoke, real 30/50/100/200 coverage checks, greater-than-200 dry-run projection validation, and three new fail-closed assertion scripts for completeness, RTO semantics, and partial coverage.
- Required artifacts: `failover_timeline_samples.jsonl`, `failover_rto_summary.json`, `client_recovery_samples.jsonl`, `observer_samples.jsonl`, common quant/event/metric/workload/report artifacts, real Valkey evidence, cleanup report, and dry-run projection.
- Explicit non-goals: no host network changes, no fake real evidence, no clean-gate substitution for `pfail_to_cluster_ok_ms`, no default >200 real execution, and no weakening existing fault matrix or cleanup gates.

## Risks and assumptions

- Safety risks: observer and client probe must use Valkey endpoints only; faulting remains through owned project fault APIs and cleanup.
- Resource risks: real 30/50/100/200 execution may be expensive and must remain under existing resource preflight and bounded 200-node policy.
- `待验证` items: exact integration point in `scripts/fault_failover_gate.py`; whether existing P20/P21/P33-P35 artifacts can be augmented only by rerunning real gates; whether Docker resources are available in this session.

## Handoff to design subagent

- Design prompt path: docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md
- Stage doc path: docs/codex/goal-loop/stages/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY.md
- Notes: P44 was absent from docs/manifest at turn start; see `artifacts/harness_exception/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY.md`. The implementation must strengthen, not bypass, the harness.
