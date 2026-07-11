# Trust and Operations

## Threat Boundary

This is a strong engineering harness, not a Byzantine security system. It is
designed to resist context drift, accidental state edits, completion pressure,
weak self-review, unchanged retries, skipped levels, fake-looking evidence, and
unbounded review. It cannot prove honesty against an administrator who can
rewrite the repository, controller, Git history, CI, and evidence together.

Within that boundary it provides:

- a control-block digest that freezes goal, checks, dependencies, and budgets;
- a controller/evaluator digest that rejects mid-run harness changes;
- atomic single-writer state and a hash-chained event journal;
- program-created pass/fail results with stored command logs;
- input/environment keyed caching, including unchanged failures;
- strict lower-level-before-expensive ordering;
- exact-scale semantic admission and artifact hashes;
- controller-owned real-gate launch and source-tree binding, so an old evidence
  bundle does not pass changed product code;
- reviewer findings that are accepted only after executable reproduction;
- bounded attempt, replan, review, context, and expensive-run budgets.

Protect the frozen paths with normal repository controls after this meta version
lands: required CI, branch protection, and review ownership. The repository CI
anchor should reject later product branches that change the control block,
controller package, or exact-scale evaluator relative to their base branch.

## Operating Rules

- Bootstrap once for a frozen control version. A legitimate controller repair
  starts a new run ID; it never mutates an in-flight run.
- Do not delete cache entries to gain another expensive attempt. Changed product
  or evidence inputs naturally produce a new digest.
- A reviewer may add a focused regression test, but not change product code,
  fixed control checks, validation levels, or real gate semantics.
- `BLOCKED` is a valid honest outcome for exhausted approaches or failed
  resources. Only a user or external environment change should restart it.
- Full evidence and logs remain in `../loop_evidence/meta_runs/milestone1-v2/`.
  Prompts receive summaries, hashes, and paths rather than raw history.

## Self-Audit Boundary

The meta implementation is complete when its frozen four-role separation,
level ordering, caching, retry/replan/review bounds, scope freeze, evidence
semantics, tamper evidence, and Goal-mode prompt are covered by executable
tests. Future hypothetical attacks outside the threat boundary are not reasons
to expand the controller. Reviewer effort belongs on product requirements the
program does not yet check.
