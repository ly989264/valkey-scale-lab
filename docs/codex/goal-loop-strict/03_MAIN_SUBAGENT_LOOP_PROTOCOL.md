# 03_MAIN_SUBAGENT_LOOP_PROTOCOL.md — Strict Multi-Agent Stage Loop

## Purpose

The strict loop is intentionally too large for a single mutable context. Every stage uses a main agent plus read-only design, write-limited worker, and fresh-context review subagents. This separation is a harness requirement, not a style preference.

## Main agent responsibilities

The main agent must:

1. determine the current stage from the manifest and state;
2. reread all required docs and current stage doc;
3. write `CONTEXT_RELOAD.md` before any implementation work;
4. launch the design subagent with the strict design prompt;
5. convert the design into a bounded worker request;
6. launch the worker subagent;
7. run gates and inspect artifacts directly;
8. launch the review subagent with fresh context;
9. fix only current-stage findings;
10. rerun gates and review after fixes;
11. run postcheck and mark-complete only after review passes;
12. commit and push one stage at a time.

The main agent must not let a worker implement future stages, rewrite history to hide failure, or rely on a previous stage's memory.

## Design subagent

Mode: read-only.

Required output:

```text
artifacts/goal_loop_strict/<STAGE_ID>/DESIGN_BRIEF.md
```

The design subagent must include:

```text
stage contract summary
current repository findings
exact files to change
expected schemas and artifacts
commands/gates to run
risks and safety constraints
items marked 待验证 when evidence is incomplete
```

The design subagent must not edit source code or mark a stage complete.

## Worker subagent

Mode: write allowed, limited to current stage.

Required output:

```text
artifacts/goal_loop_strict/<STAGE_ID>/WORKER_SUMMARY.md
```

The worker must:

```text
implement only current-stage requirements
create/modify tests and assertion scripts
produce real evidence through harness gates where required
record commands and outputs by path
record artifacts by path and schema
record cleanup status
record deviations from design
```

The worker must not commit, push, mark complete, edit gate results, or edit phase state.

## Review subagent

Mode: fresh-context read-only unless asked for patch suggestions.

Required output:

```text
artifacts/goal_loop_strict/<STAGE_ID>/REVIEW.md
audit/<STAGE_ID>/AUDIT.md
audit/<STAGE_ID>/audit_decision.json
```

The review subagent must inspect:

```text
required docs
current stage doc
design brief
worker summary
git diff
gate logs
gate result checksum
schema files
stage artifacts
source code paths touched by the worker
cleanup reports
```

The review decision vocabulary is exactly:

```text
Decision: PASS
Decision: FAIL
```

`PASS_WITH_WARNINGS`, `mostly pass`, and similar terms are invalid.

## Required sequence

```text
[main: docs reload + CONTEXT_RELOAD.md]
        |
        v
[design subagent: read-only DESIGN_BRIEF.md]
        |
        v
[main: bounded worker prompt]
        |
        v
[worker subagent: implementation + WORKER_SUMMARY.md]
        |
        v
[main: gates + artifact inspection]
        |
        v
[review subagent: fresh-context REVIEW.md]
        |
        v
[main: fix current-stage findings if any]
        |
        v
[postcheck -> mark-complete -> commit -> push -> COMPLETION.md]
```

## Prohibited shortcuts

```text
no design subagent skip
no worker-only stage completion
no review based only on summary
no gate result hand-editing
no phase state hand-editing
no fake evidence for real scales
no combining multiple stages into one commit
no continuing after blocked stage as if it passed
```
