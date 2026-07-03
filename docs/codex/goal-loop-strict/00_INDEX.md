# 00_INDEX.md — Strict Goal Loop Index

This directory is the source of truth for the strict matrix loop P27-P40. The main agent must read this index at every stage start.

## Required read order at every stage start

```text
1. AGENTS.md
2. CODEX_START_HERE.md
3. CODEX_GOAL_LOOP_START.md
4. CODEX_STRICT_MATRIX_LOOP_START.md
5. docs/codex/goal-loop/00_INDEX.md
6. docs/codex/goal-loop/01_GOAL_CONTRACT.md
7. docs/codex/goal-loop/02_STAGE_MANIFEST.md
8. docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md
9. docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md
10. docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md
11. docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md
12. docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md
13. docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md
14. docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md
15. docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md
16. docs/codex/goal-loop-strict/00_INDEX.md
17. docs/codex/goal-loop-strict/01_STRICT_GOAL_CONTRACT.md
18. docs/codex/goal-loop-strict/02_STRICT_STAGE_MANIFEST.md
19. docs/codex/goal-loop-strict/03_MAIN_SUBAGENT_LOOP_PROTOCOL.md
20. docs/codex/goal-loop-strict/04_CONTEXT_LEDGER_PROTOCOL.md
21. docs/codex/goal-loop-strict/05_FAIL_CLOSED_HARNESS_CONTRACT.md
22. docs/codex/goal-loop-strict/06_COVERAGE_REGISTRY_SPEC.md
23. docs/codex/goal-loop-strict/07_QUANTIFICATION_DATA_CONTRACT.md
24. docs/codex/goal-loop-strict/08_MANAGEMENT_OPERATION_MATRIX_SPEC.md
25. docs/codex/goal-loop-strict/09_FAULT_FAILOVER_MATRIX_SPEC.md
26. docs/codex/goal-loop-strict/10_SCALE_EXECUTION_POLICY.md
27. docs/codex/goal-loop-strict/11_ANALYSIS_VISUAL_REPORT_SPEC.md
28. docs/codex/goal-loop-strict/12_AUDIT_COMMIT_NO_BYPASS_POLICY.md
29. docs/codex/goal-loop-strict/stages/<CURRENT_STAGE>.md
30. artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md if it exists
```

If any required document is absent, the stage is blocked. Do not continue from memory.

## Core documents

- `01_STRICT_GOAL_CONTRACT.md`: non-negotiable clarified user goal.
- `02_STRICT_STAGE_MANIFEST.md`: authoritative P27-P40 stage design.
- `03_MAIN_SUBAGENT_LOOP_PROTOCOL.md`: mandatory main/design/worker/review pattern.
- `04_CONTEXT_LEDGER_PROTOCOL.md`: Markdown state handoff that survives compaction.
- `05_FAIL_CLOSED_HARNESS_CONTRACT.md`: harness and anti-bypass requirements.
- `06_COVERAGE_REGISTRY_SPEC.md`: exact coverage matrix and coverage IDs.
- `07_QUANTIFICATION_DATA_CONTRACT.md`: all metrics and artifact families.
- `08_MANAGEMENT_OPERATION_MATRIX_SPEC.md`: management rows and semantics.
- `09_FAULT_FAILOVER_MATRIX_SPEC.md`: fault/failover/partition/split-brain rows and semantics.
- `10_SCALE_EXECUTION_POLICY.md`: real 50/100/200 and >200 dry-run-only policy.
- `11_ANALYSIS_VISUAL_REPORT_SPEC.md`: analysis and visual report quality gates.
- `12_AUDIT_COMMIT_NO_BYPASS_POLICY.md`: review, commit, push, and blocked-stage policy.

## Stage documents

Each document in `stages/` is authoritative for one stage. A stage is incomplete until the main agent writes `artifacts/goal_loop_strict/<STAGE_ID>/CONTEXT_RELOAD.md` showing that this index, the strict core docs, and the current stage doc were reread.

## Prompt documents

The main agent must use the prompt files under `prompts/` for Codex App subagents. It may add stage-specific details, but it must not weaken or omit constraints from those prompt files.

## Template documents

The Markdown templates under `templates/` define the minimum structured handoff artifacts required for every stage. Additional JSON/JSONL artifacts are required by the harness, but they do not replace the Markdown handoff artifacts.
