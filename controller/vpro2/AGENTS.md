# VPRO2 Development Authority

`controller/vpro2/` is an operator-governed successor project. It does not
modify, reseal, import state from, or replace the frozen
`controller/vpro/` 1.0.0 release in place.

## Kernel Rules

- Milestone contracts define only the immutable final goal, executable success
  conditions, independent evaluators, real evidence requirements, global
  safety boundaries, resource budgets, and failure policy.
- A contract must not define objectives, dependencies, profiles, gates, an
  implementation order, or a subset-completion claim.
- Goal State and Goal Delta are derived only from current evaluator results.
  Worker or Reviewer prose is never completion evidence.
- Temporary objectives, Gap Graphs, rankings, reservations, transactions, and
  path history are controller-owned runtime records.
- Controller, Worker, Reviewer, Evaluator, and Operator messages use distinct
  authority credentials. An actor label is not an identity.
- Worker writes are transactional and scope checked. A regression, ineffective
  path, or integrity anomaly is not retained as progress.
- Contract, evaluator, authority, state, and evidence paths never overlap
  Worker write authority.
- Missing, stale, simulated, downscaled, substituted, or unadmitted evidence
  never satisfies a required real-evidence condition.
- Success and failure both produce authenticated terminal receipts.

## Development Rules

- Keep the package milestone-neutral and dependency-free unless a new
  dependency is justified by an executable security or portability need.
- Add focused `unittest` coverage for every state transition and trust
  boundary. Tests must be hermetic and use unrelated synthetic milestones.
- Never weaken a validator or evaluator assertion to make a test pass.
- Do not edit `controller/vpro/**` while working in this successor project.
