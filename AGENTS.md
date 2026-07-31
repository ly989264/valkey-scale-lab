# Valkey Scale Lab refactor rules

## Product purpose

This repository is a Valkey cluster experiment harness.

The refactor must improve the correctness and maintainability of the
currently used product paths. Optimize for direct, understandable code
and reproducible behavior.

## Current-stage rule

Work only on the active stage in REFACTOR.md.

The active stage is the complete scope. Do not add adjacent cleanup,
future features, speculative extensibility, or unrelated improvements.

## Mandatory implementation rules

1. Read this file and the complete active stage before editing.
2. Trace the real production call path before changing code.
3. Implement every completion condition in the active stage.
4. Update all affected production call sites, tests, and active documentation.
5. Use the smallest change that completely solves the stage.
6. Prefer deleting, moving, or directly calling existing code.
7. Preserve behavior during extraction-only stages.
8. Run the stage verification commands before reporting completion.
9. A partial implementation must be reported as BLOCKED, not COMPLETE.
10. Tests must exercise the real implementation path.

## Prohibited design

Unless the active stage explicitly requires it, do not add:

- controllers;
- orchestration frameworks;
- generic engines;
- plugin systems;
- registries;
- dependency-injection layers;
- state machines;
- new artifact layers;
- new status enums;
- new schemas;
- locks or leases;
- identity or authorization protocols;
- fallbacks;
- compatibility layers;
- future extension points;
- abstractions for future ECS or 2000-node work.

Do not create an abstraction for a single implementation.

Do not add defensive handling for hypothetical adversarial agents,
data tampering, identity theft, PID TOCTOU, malicious paths, hostile
multi-tenancy, or other scenarios that are not part of the active stage
and are not demonstrated by an existing reproducible failure.

Preserve existing safeguards unless the active stage explicitly removes one.
Do not expand their scope.

## Completeness rules

Before reporting COMPLETE:

- search for all callers of every changed function or field;
- search for duplicated implementations;
- verify the active CLI and Gate paths;
- verify that old and new code are not both active;
- map every stage completion condition to code and a test;
- inspect the complete diff from the stage base SHA.

Passing one unit test is not proof of stage completion.

## Test rules

Do not:

- hard-code expected outputs only for tests;
- replace real execution with fixtures;
- weaken assertions to obtain PASS;
- mark a step PASS without executing it;
- treat missing evidence as successful evidence;
- silently skip required behavior.

## Role rules

### Goal controller

The Goal controller coordinates only.

It may:

- read files;
- start worker and reviewer sessions;
- run verification commands;
- update REFACTOR.md stage status;
- commit and push a passed stage.

It must not edit product code.

### Worker

The worker edits product code for exactly one stage.

It must not:

- commit;
- push;
- change stage scope;
- mark the stage PASS;
- edit the REFACTOR.md status table.

### Reviewer

The reviewer is read-only.

It reviews the complete stage diff from the original stage base SHA.
It must report all blocking findings in one review.
It must not propose unrelated redesign or future hardening.

## Worker response

Return exactly:

STATUS: COMPLETE | BLOCKED

IMPLEMENTED:
- completion condition -> files/functions

TESTS:
- command -> result

REMAINING:
- none, or exact blocker

## Reviewer response

Return exactly:

VERDICT: PASS | FAIL

BLOCKERS:
- CATEGORY | stage requirement | file/function | concrete reason

CATEGORY must be one of:

- WRONG_DIRECTION
- OVERDESIGN
- INCOMPLETE
- REGRESSION

When there are no blockers, write:

BLOCKERS:
- none
