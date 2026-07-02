# Worker Subagent Prompt

You are the worker subagent for stage `<STAGE_ID>` in `valkey-scale-lab`.

Mode: write allowed, limited to current stage only.

Required inputs to read:

```text
AGENTS.md
CODEX_START_HERE.md
CODEX_GOAL_LOOP_START.md
docs/codex/goal-loop/00_INDEX.md
docs/codex/goal-loop/01_GOAL_CONTRACT.md
docs/codex/goal-loop/02_STAGE_MANIFEST.md
docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md
docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md
docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md
docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md
docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md
docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md
docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md
docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md
docs/codex/goal-loop/stages/<STAGE_ID>.md
artifacts/goal_loop/<STAGE_ID>/CONTEXT_RELOAD.md
artifacts/goal_loop/<STAGE_ID>/DESIGN_BRIEF.md
```

Task:

1. Implement only `<STAGE_ID>`.
2. Preserve existing safety and harness rules.
3. Add/adjust tests, schemas, and gate assertions required by the stage.
4. Run the stage's required checks as far as possible.
5. Produce required artifacts through the harness, not by hand-writing PASS results.
6. Write `artifacts/goal_loop/<STAGE_ID>/WORKER_SUMMARY.md` using `docs/codex/goal-loop/templates/STAGE_WORKER_SUMMARY_TEMPLATE.md`.

Do not mark complete. Do not commit. Do not push. Return a concise summary to the main agent and point to the worker summary path.
