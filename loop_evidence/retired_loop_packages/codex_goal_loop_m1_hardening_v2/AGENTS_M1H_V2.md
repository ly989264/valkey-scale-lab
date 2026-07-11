# AGENTS_M1H_V2.md — hardening loop agent rules

## Read at every stage start

The main agent must reload these files at every stage boundary:

- `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md`
- `codex_goal_loop_m1_hardening_v2/docs/02_NON_NEGOTIABLE_CONTRACT.md`
- `codex_goal_loop_m1_hardening_v2/docs/03_EVIDENCE_TAXONOMY.md`
- `codex_goal_loop_m1_hardening_v2/docs/04_HARD_GATE_ARCHITECTURE.md`
- `codex_goal_loop_m1_hardening_v2/docs/09_NO_SHORTCUT_RULES.md`
- `codex_goal_loop_m1_hardening_v2/docs/10_ACCEPTANCE_MATRIX.md`
- the current stage file;
- the previous stage `CONTEXT_RELOAD.md`, `REVIEW.md`, `COMPLETION.md`, and machine gate results.

## Real multi-agent requirement

Each stage must use real subagents in this order:

```text
main agent reloads docs
  -> design subagent
  -> worker subagent
  -> review subagent
  -> main agent applies fixes if review fails
  -> review subagent re-runs or re-reviews
  -> commit
  -> push
  -> context handoff
```

Forbidden:

- “simulated design subagent”; 
- “simulated worker subagent”; 
- “simulated review subagent”; 
- “subagent unavailable, so I reviewed myself”; 
- moving forward with only a Markdown self-review.

If the platform cannot launch a subagent, write a structured `BLOCKED_WITH_REASON` stage artifact and stop. Do not commit a PASS.

## Completion rule

A stage is complete only if all are true:

1. required code gates exist and exit 0;
2. gate result artifacts exist under `runs/m1-hardening/<stage_id>/artifacts/`;
3. no forbidden shortcut pattern is present;
4. the review subagent decision is `PASS`;
5. the commit message contains the stage id;
6. push succeeds.

No Markdown statement can override a failing or missing executable gate.
