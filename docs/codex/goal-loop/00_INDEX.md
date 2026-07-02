# 00_INDEX.md — Goal Loop Document Index

This directory contains the source of truth for the management/fault/quantification goal loop.

## Required read order at every stage start

```text
1. AGENTS.md
2. CODEX_START_HERE.md
3. CODEX_GOAL_LOOP_START.md
4. docs/codex/goal-loop/00_INDEX.md
5. docs/codex/goal-loop/01_GOAL_CONTRACT.md
6. docs/codex/goal-loop/02_STAGE_MANIFEST.md
7. docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md
8. docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md
9. docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md
10. docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md
11. docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md
12. docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md
13. docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md
14. docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md
15. docs/codex/goal-loop/stages/<CURRENT_STAGE>.md
```

## Core documents

- `01_GOAL_CONTRACT.md`: non-negotiable user goal and completion definition.
- `02_STAGE_MANIFEST.md`: stage list P15-P26 and stage-to-artifact mapping.
- `03_MULTI_AGENT_STAGE_PROTOCOL.md`: mandatory design/worker/review subagent flow.
- `04_CONTEXT_TRANSFER_PROTOCOL.md`: Markdown handoff artifacts that survive compaction.
- `05_STRONG_HARNESS_GATE_SPEC.md`: required manifest, schema, scripts, and gate behavior.
- `06_QUANTIFICATION_SPEC.md`: canonical metrics, event timeline, and missing-data policy.
- `07_MANAGEMENT_OPS_SPEC.md`: remove/reshard/rebalance/rolling restart matrix.
- `08_FAULT_MATRIX_SPEC.md`: failover, network fault, partition, split-brain, workload-impact matrix.
- `09_SCALE_AND_RESOURCE_POLICY.md`: safe resource preflight and 200-node bounded exception.
- `10_AUDIT_AND_COMMIT_POLICY.md`: review, postcheck, mark-complete, commit, push rules.

## Stage documents

Each stage document under `stages/` is authoritative for that stage. A stage is incomplete if its stage document has not been read and reflected in `artifacts/goal_loop/<STAGE_ID>/CONTEXT_RELOAD.md`.

## Prompt documents

Prompt files under `prompts/` are intended to be copied into Codex App subagent requests. The main agent must not substitute a vague prompt for them.

## Template documents

Template files under `templates/` define the Markdown artifacts that carry state between agents and stages. The final implementation may additionally create JSON artifacts, but these Markdown templates are mandatory for loop governance.
