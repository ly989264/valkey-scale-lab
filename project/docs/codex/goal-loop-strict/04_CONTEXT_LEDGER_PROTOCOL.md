# 04_CONTEXT_LEDGER_PROTOCOL.md — Context and Ledger Protocol

## Purpose

Codex context can compact. The loop must survive compaction by writing structured Markdown state at every stage and by keeping a cross-stage journal.

## Required stage directory

```text
artifacts/goal_loop_strict/<STAGE_ID>/
  CONTEXT_RELOAD.md
  DESIGN_BRIEF.md
  WORKER_SUMMARY.md
  REVIEW.md
  FIX_LOG.md
  COMPLETION.md
  BLOCKED.md
```

`COMPLETION.md` and `BLOCKED.md` are mutually exclusive for a stage.

## CONTEXT_RELOAD.md

Written by the main agent before design.

Minimum content:

```text
stage ID
branch
current commit
git status --short
output of python3 scripts/codex_gate.py next
required docs read
current stage contract summary
prior-stage journal entries read
known blockers
assumptions and 待验证 items
```

## DESIGN_BRIEF.md

Written by the design subagent before worker edits.

Minimum content:

```text
objective
current repository facts
scope boundaries
implementation plan
harness plan
schema/artifact plan
test plan
risk list
blocked conditions
```

## WORKER_SUMMARY.md

Written by the worker after implementation and before review.

Minimum content:

```text
changed files
commands run
exit codes
artifact paths
schema validation status
gate result path
real Valkey evidence path when required
cleanup report path when required
coverage rows satisfied
missing-data entries with reasons
deviations from design
remaining risks
```

## REVIEW.md

Written by fresh-context review.

Minimum content:

```text
Fresh Context: YES
scope reviewed
diff summary
gate result path and sha256
artifact paths reviewed
schema validation summary
coverage matrix summary
safety review
report quality review when applicable
blocking findings
Decision: PASS or Decision: FAIL
```

## STRICT_STAGE_JOURNAL.md

After each passed stage, update:

```text
artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md
```

Each stage entry must include:

```text
stage ID
commit hash
pushed branch
artifact directory
gate result path and sha
coverage rows added
known limitations
next-stage handoff
```

The next stage must read the journal during context reload.

## Compaction recovery rule

After compaction or context loss, the main agent must reconstruct state only from repository files, artifacts, gate logs, and this ledger. It must not infer completion from memory.
