# 04_CONTEXT_TRANSFER_PROTOCOL.md — Structured Markdown State Transfer

## Purpose

Codex context can be compacted. Stage and subagent state must be externalized into Markdown files so the next agent can reconstruct the task without relying on chat history.

## Required directory layout per stage

```text
artifacts/goal_loop/<STAGE_ID>/
  CONTEXT_RELOAD.md
  DESIGN_BRIEF.md
  WORKER_SUMMARY.md
  REVIEW.md
  FIX_LOG.md                  # required if review fails or gates fail after worker handoff
  COMPLETION.md
  BLOCKED.md                  # only when blocked; incompatible with mark-complete
```

## CONTEXT_RELOAD.md

The main agent writes this before spawning the design subagent.

Required content:

- current date/time and branch;
- output of `git status --short`;
- current stage ID and why it is current;
- list of required docs read;
- compact summary of the current stage contract;
- unresolved blockers or assumptions.

Use `templates/CONTEXT_RELOAD_TEMPLATE.md`.

## DESIGN_BRIEF.md

The design subagent writes this before any worker edits.

Required content:

- stage objective;
- current repository findings;
- exact implementation plan;
- harness changes;
- tests and gates;
- expected artifacts;
- safety concerns;
- `待验证` items.

Use `templates/STAGE_DESIGN_TEMPLATE.md`.

## WORKER_SUMMARY.md

The worker subagent writes this after implementation and before review.

Required content:

- changed files;
- commands run;
- gates passed/failed;
- artifact paths;
- metrics collected;
- cleanup status;
- deviations from design;
- remaining risks.

Use `templates/STAGE_WORKER_SUMMARY_TEMPLATE.md`.

## REVIEW.md

The review subagent writes this after independently inspecting diff, gates, and artifacts.

Required content:

- scope reviewed;
- gate result summary;
- artifact validation summary;
- safety review;
- correctness review;
- quantitative coverage review;
- blocking findings;
- `Decision: PASS` or `Decision: FAIL`.

Use `templates/STAGE_REVIEW_TEMPLATE.md`.

## COMPLETION.md

The main agent writes this immediately before mark-complete and commit.

Required content:

- stage ID;
- review decision path;
- postcheck command and result;
- mark-complete command and result;
- commit hash after commit;
- push result;
- next stage ID.

Use `templates/STAGE_COMPLETION_TEMPLATE.md`.

## BLOCKED.md

If the stage cannot complete, write this instead of `COMPLETION.md`. A blocked stage must not be marked complete.

Use `templates/BLOCKED_STAGE_TEMPLATE.md`.

## Cross-stage transfer

After each successful stage, update:

```text
artifacts/goal_loop/STAGE_JOURNAL.md
```

The journal must contain one compact paragraph per stage with:

- stage ID;
- commit hash;
- artifact directory;
- key capabilities added;
- known limitations;
- next-stage handoff.

The next stage must read the journal during context reload.
