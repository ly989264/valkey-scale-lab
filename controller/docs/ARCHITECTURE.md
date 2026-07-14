# Architecture

## Deployment Model

The Controller runs inside one Codex Goal session in one controlled
development environment. Planner, Worker, Reviewer, and Evaluator name logical
responsibilities, not separately deployed principals.

## Immutable Milestone

The Milestone defines only the final goal, required success conditions,
required evidence, and termination limits. Controller loads it once and checks
that its bytes remain unchanged before every full evaluation.

Evaluator wiring, allowed Worker paths, and protected paths are runtime inputs.
They cannot be selected or changed by an objective.

## Goal State

Evaluator returns one complete result covering every success condition and
evidence requirement. Controller validates exact coverage and derives every
gap directly from non-`PASS` results. Linked evidence remains fail-closed: a
functional condition is not complete while required evidence is missing,
stale, substituted, untrusted, blocked, or failed.

## Closed Loop

Each iteration is sequential:

```text
evaluate all
  -> derive Goal State and all gaps
  -> plan zero or one bounded objective
  -> validate target gaps and write paths
  -> record Git checkpoint
  -> run Worker
  -> inspect changed paths
  -> evaluate all
  -> compare Goal States
  -> commit material progress or roll back
  -> record failed path
```

Material progress means at least one new condition or evidence requirement is
`PASS`, no prior `PASS` regresses, and the candidate introduces no blocked
check. Diagnostic text alone does not retain a patch.

Failed-path equivalence uses the current Goal State plus normalized target
gaps, strategy, and write paths. Rewording an objective does not repeat the
same failed action. A changed Goal State may make the approach relevant again.

## Termination

- `SUCCESS`: the current complete evaluation passes every required condition
  and evidence requirement.
- `STAGNATED`: consecutive Worker attempts produce no retainable progress.
- `ENVIRONMENT_BLOCKED`: complete evaluation cannot proceed within its retry
  limit.
- `NO_LEGAL_PLAN`: Planner cannot supply a legal non-repeated objective within
  its limit.
- `BUDGET_EXHAUSTED`: iteration or wall-clock limit is exhausted.

State persistence is a normal atomically replaced JSON status file. Git owns
code checkpoints and rollback.
