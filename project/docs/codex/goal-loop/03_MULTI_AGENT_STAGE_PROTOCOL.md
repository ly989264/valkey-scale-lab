# 03_MULTI_AGENT_STAGE_PROTOCOL.md — Mandatory Main/Subagent Stage Loop

## Purpose

The goal loop is large enough that a single context can drift. Each stage must use a main agent plus three subagents to force design, implementation, and review separation.

## Agent roles

### Main agent

Responsibilities:

- reload documents at the start of every stage;
- decide exact current stage;
- spawn the design subagent;
- convert the design brief into a constrained worker prompt;
- spawn the worker subagent;
- run gates and inspect artifacts;
- spawn the review subagent;
- fix only current-stage review findings;
- run postcheck and mark-complete;
- commit and push after the stage passes.

The main agent must keep the stage bounded. It must not let the worker implement a future stage.

### Design subagent

Mode: read-only.

Responsibilities:

- reread the required docs and current stage doc;
- inspect relevant code/tests/schemas/harness files;
- write a design brief with exact files to change, new tests/gates, artifact schemas, and risk list;
- identify any current-repo uncertainty as `待验证`.

Output: `artifacts/goal_loop/<STAGE_ID>/DESIGN_BRIEF.md`.

### Worker subagent

Mode: write allowed, but limited to the current stage.

Responsibilities:

- implement only the current stage design;
- add/adjust tests and schemas;
- produce real evidence artifacts through the harness;
- fix current-stage gate failures;
- write a worker summary with changed files, commands, evidence, and remaining risks.

Output: `artifacts/goal_loop/<STAGE_ID>/WORKER_SUMMARY.md`.

### Review subagent

Mode: fresh-context, read-only unless explicitly asked to propose patch snippets. It must not mark a stage pass based on trust in the worker summary.

Responsibilities:

- reread `AGENTS.md`, goal-loop docs, current stage doc, design brief, worker summary, gate logs, artifact schemas, and diff;
- verify code behavior, safety boundaries, evidence quality, schema validation, and cleanup;
- run or request focused checks when necessary;
- write `Decision: PASS` only when all stage criteria are satisfied.

Output: `artifacts/goal_loop/<STAGE_ID>/REVIEW.md` and, if the existing audit machinery requires it, `audit/<STAGE_ID>/AUDIT.md` plus `audit/<STAGE_ID>/audit_decision.json`.

## Required sequencing

```text
[main reload docs]
      |
      v
[design subagent: read-only]
      |
      v
[main creates worker prompt]
      |
      v
[worker subagent: current-stage implementation]
      |
      v
[main runs gates and fixes only current-stage failures]
      |
      v
[review subagent: fresh-context audit]
      |
      v
[main fixes review findings if any]
      |
      v
[postcheck -> mark complete -> commit -> push]
```

## Prohibited shortcuts

- Do not skip the design subagent because the stage looks obvious.
- Do not let the worker commit.
- Do not accept review without a written `Decision: PASS`.
- Do not summarize raw logs into the main thread without storing the full log path.
- Do not use subagent output as proof when the harness can independently verify.
- Do not combine multiple stages into one commit.

## Subagent prompt rule

Use the prompt files under `docs/codex/goal-loop/prompts/`. The main agent may add stage-specific context, but must not remove the constraints in those prompts.

## Parallelism rule

Design and review are read-only. Worker is the only write-heavy subagent. Do not run two write-heavy subagents at the same time because that creates conflicts and weakens stage accountability.
