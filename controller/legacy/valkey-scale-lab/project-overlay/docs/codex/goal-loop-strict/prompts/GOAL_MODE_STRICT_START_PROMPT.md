# GOAL_MODE_STRICT_START_PROMPT.md

You are running in Codex App Goal mode inside `ly989264/valkey-scale-lab`.

Your goal is to execute the strict P27-P40 loop defined in `CODEX_STRICT_MATRIX_LOOP_START.md` and `docs/codex/goal-loop-strict/`.

First, read these files in order:

```text
AGENTS.md
CODEX_START_HERE.md
CODEX_GOAL_LOOP_START.md
CODEX_STRICT_MATRIX_LOOP_START.md
docs/codex/goal-loop-strict/00_INDEX.md
```

Then read every document required by `docs/codex/goal-loop-strict/00_INDEX.md`.

Do not stop if `python3 scripts/codex_gate.py next` reports `COMPLETE_AUTOMATIC_PHASES` before P27-P40 exist. That only means the older loop completed. Implement `P27_STRICT_MATRIX_REBASE_HARNESS` first.

For every stage, use this sequence exactly:

```text
1. main agent rereads required docs and writes CONTEXT_RELOAD.md
2. main agent launches design subagent with DESIGN_SUBAGENT_PROMPT.md
3. main agent launches worker subagent with WORKER_SUBAGENT_PROMPT.md
4. main agent runs gates and inspects artifacts
5. main agent launches review subagent with REVIEW_SUBAGENT_PROMPT.md
6. if review fails, fix current-stage issues only and rerun gates/review
7. postcheck
8. mark-complete
9. commit exactly this stage
10. push
11. update COMPLETION.md and strict stage journal
12. continue to next stage
```

Strict rules:

```text
Do not fake real Valkey evidence.
Do not downshift 200-node stages.
Do not run real clusters above 200 nodes.
Do not use host-level network mutation.
Do not manually edit gate results or phase state to force PASS.
Do not skip design/worker/review subagents.
Do not commit before postcheck and mark-complete.
Do not continue past a blocked stage.
```

The loop is complete only when P40 passes, is marked complete, committed, and pushed.
