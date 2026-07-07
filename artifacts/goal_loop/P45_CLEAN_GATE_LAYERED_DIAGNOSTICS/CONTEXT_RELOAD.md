# CONTEXT_RELOAD — P45_CLEAN_GATE_LAYERED_DIAGNOSTICS

## Stage identity

- Stage ID: P45_CLEAN_GATE_LAYERED_DIAGNOSTICS
- Branch: codex/valkey-scale-lab-loop
- Date/time: 2026-07-07T06:38:24Z
- Current harness next output: `COMPLETE_AUTOMATIC_PHASES`; P45 was explicitly requested by the user and was not yet represented in the manifest.
- Git status summary: one new stage document before this reload; this reload also records the harness exception for the missing P45 document.

## Documents reread

| Document | Read? | Notes |
|---|---:|---|
| AGENTS.md | yes | Governs safety, stage reload, multi-agent loop, real Valkey evidence, and no-bypass rules. |
| CODEX_START_HERE.md | yes | Requires `codex_gate.py next`, stage-specific precheck/run/postcheck/mark-complete, and per-stage commit/push. |
| CODEX_GOAL_LOOP_START.md | yes | Restates user goal and operator approvals; forbids host network mutation and 1000-node execution. |
| docs/codex/02_PHASES.md | yes | Manifest is authoritative; phases require postcheck, schema artifacts, real Valkey evidence where applicable. |
| docs/codex/04_AUDITOR.md | yes | Fresh-context review must inspect gate logs, artifacts, schemas, and diff before PASS. |
| docs/codex/goal-loop/00_INDEX.md | yes | Lists required read order and mandatory stage document. |
| docs/codex/goal-loop/01_GOAL_CONTRACT.md | yes | Completion requires runnable code, schema-validated artifacts, real evidence, and review. |
| docs/codex/goal-loop/02_STAGE_MANIFEST.md | yes | Describes P15-P26 common gates/artifacts; P45 extends the already completed loop. |
| docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md | yes | Requires design subagent, worker subagent, gates, review subagent, postcheck, mark-complete, commit, push. |
| docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md | yes | Requires CONTEXT_RELOAD, DESIGN_BRIEF, WORKER_SUMMARY, REVIEW, COMPLETION/BLOCKED, and stage journal updates. |
| docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md | yes | Assertions must fail closed; real gates must independently verify Valkey/version/topology/data path/cleanup. |
| docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md | yes | Metrics must be event/timestamp based; missing data must be `MISSING` or `SKIPPED_WITH_REASON` with reasons. |
| docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md | yes | Management paths using clean-gates must preserve real operations, workload windows, convergence, and cleanup semantics. |
| docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md | yes | Failover/fault evidence must be real at required scales and include workload impact and recovery timing. |
| docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md | yes | 30/50/100/200 real evidence requires resource preflight; greater-than-200 remains dry-run only. |
| docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md | yes | No commit before precheck/run/assertions/artifacts/review/postcheck/mark-complete. |
| docs/codex/goal-loop/stages/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS.md | yes | Added because the requested stage document was absent; this is a strengthening harness fix, not completion evidence. |

## Current stage contract summary

- Required implementation: separate Level 1 observer recovery, Level 2 client recovery, and Level 3 clean snapshot endpoints; keep clean-gate as final stability/PASS while adding diagnostics and per-round probe records.
- Required gates: new fail-closed clean-gate diagnostics, layered recovery semantics, no RTO conflation, and no partial coverage assertions; schema validation for new artifacts; real failover gate for smoke plus 30/50/100/200.
- Required artifacts: common phase artifacts plus `clean_gate_diagnostics.json`, `clean_gate_probe_rounds.jsonl`, `layered_recovery_summary.json`, `recovery_endpoint_summary.json`, updated observer and failover timeline JSONL files, and dry-run greater-than-200 projection.
- Explicit non-goals: do not delete/relax clean-gate, do not count clean snapshot as Level 1, do not claim fake/dry-run evidence as real, do not hardcode 200 as a runtime ceiling, and do not modify host networking.

## Risks and assumptions

- Safety risks: fault handling must remain confined to owned Docker/process controls; no host network mutation is allowed.
- Resource risks: full real 30/50/100/200 gate may take significant time and can block if Docker/resource preflight fails.
- `待验证` items: exact clean-gate call sites in runtime and failover gates; current artifact schemas; whether `codex_gate.py` can accept P45 without manifest changes; whether existing P44 timeline artifacts can be generated as P45 without static copying.

## Handoff to design subagent

- Design prompt path: `docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md`
- Stage doc path: `docs/codex/goal-loop/stages/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS.md`
- Notes: Design must treat the missing P45 stage doc/manifest as a harness-start defect and plan a strengthening fix; implementation must be runtime-sourced, not report-only.
