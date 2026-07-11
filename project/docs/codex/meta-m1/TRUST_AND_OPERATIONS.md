# Trust and Operations

## Threat Boundary

This is a strong engineering harness, not a Byzantine security system. It
resists context drift, accidental state edits, completion pressure, unchanged
retries, skipped levels, shallow evidence, and unbounded review. It cannot prove
honesty against an administrator who rewrites the repository, Git, CI, and all
evidence together.

V3 separates three trust domains:

- Goal Contract: immutable scope, dependencies, levels, and 50/200 completion
  gates.
- Controller Kernel: immutable scheduling, state, budgets, command runner, and
  real-gate launcher.
- Evidence Evaluator: versioned semantic parser that may be strengthened only
  through a reproduced `EVALUATOR_GAP` and controlled repair.

The state store provides atomic single-writer updates, a hash-chained event
journal, and a latest-event seal over objectives, cache, migration, and active
work. Reviewer-added tests are content-anchored for the rest of the run, so a
Worker cannot turn their failure into a pass by weakening the reproduction.
Product, evaluator, kernel, and control digests are independent. An evaluator
upgrade invalidates admission results but does not by itself invalidate or
rerun raw real-cluster evidence.

## Operating Rules

- V2 state/evidence is read-only. V3 migration verifies the v2 state hash,
  event-chain tail, and evidence manifest before importing progress.
- New Reviewer checks and newly reached gates receive their own attempt/replan
  budget. Editing code while the same gate still fails never replenishes it. An
  unchanged cached failure routes to replan early instead of consuming repeated
  Worker turns.
- Candidate objective completion runs the full non-real regression floor before
  review or a real gate; unchanged results are reused by input digest.
- Repository tests are hermetic. Checks over current-run evidence belong in the
  versioned evaluator.
- Raw real evidence uses a unique v3 run root. Real-gate execution fails if it
  changes historical `loop_evidence/artifacts`.
- JSON and JSONL artifacts are parsed and cross-checked; hashes alone are not
  admission evidence.
- `BLOCKED` is an honest outcome for exhausted product approaches or external
  resource failure. It is not used for a repairable evaluator omission.

Protect the immutable Kernel and Goal Contract with required CI and branch
protection. Evaluator changes require adversarial evaluator tests and an evented
repair transition.

## Completion Boundary

The meta implementation is ready when migration, controlled evaluator repair,
gap-scoped budgets, cached-failure routing, closure regression, digest
separation, evidence semantics, output isolation, and hermetic reviewer checks
all have executable coverage. Hypothetical attacks beyond the stated threat
boundary do not expand the controller.
