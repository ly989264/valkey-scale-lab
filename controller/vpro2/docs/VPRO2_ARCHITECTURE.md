# VPRO2 Architecture

## Purpose

VPRO2 is a goal-driven engineering controller. An external Milestone fixes the
destination and the trust boundary, but does not prescribe the route. The
controller evaluates the whole Milestone, derives the current gaps, chooses one
bounded temporary objective, observes the resulting Goal Delta through the
independent evaluators, and either retains or rolls back that path.

The framework is milestone-neutral. Product names, implementation phases,
dependency graphs, fixed development order, scale values, and domain-specific
acceptance thresholds must not appear in the kernel.

## Release Boundary

`controller/vpro/` is the frozen VPRO 1.0.0 release. VPRO2 is a separate
operator-governed successor rooted at `controller/vpro2/`. It does not modify
or reseal VPRO1, import VPRO1 state, or reinterpret a VPRO1 completion receipt.

VPRO2 has its own launcher, package namespace, manifest schema, receipt schema,
contract schema, state schema, and run root. A VPRO2 run always starts from a
fresh external Milestone contract and an empty controller-owned run root.

The final VPRO2 distribution is a fixed filesystem closure. Its embedded
manifest hashes every file below the declared release roots. An external
operator receipt authorizes the exact manifest digest. `VPRO2_LAUNCH.py` uses
only the Python standard library to verify the receipt, manifest, file hashes,
closure membership, protected paths, and symlink rules before adding `src/` to
`sys.path` or importing any `vpro2` module.

The runtime has no framework update, reseal, self-repair, or in-place migration
operation. Release drift fails closed and requires an operator-selected
successor release.

## Milestone Contract

The external `vpro-milestone-v2` document contains only:

- the immutable final goal and Milestone identity;
- atomic, required, executable success conditions;
- sealed independent evaluator definitions;
- explicit real-evidence and admission requirements;
- global product, context, write, authority, evidence, tool, capability, and
  forbidden-effect boundaries;
- total iteration, time, cost, context, write, evidence, capability, operator,
  transaction storage, and diagnostic budgets;
- fail-closed stagnation, environment, no-plan, integrity, budget, and operator
  termination policy.

The schema and semantic parser both reject `objectives`, `depends_on`,
`profiles`, `gates`, and `order` at every object depth. There is no
subset-completion profile. Every success condition is required for the single
Milestone success claim.

Contract, evaluator, evaluator-output schema, and authority paths are immutable
for a run. Worker-writable paths cannot overlap them or controller-owned state
and evidence roots. A changed contract or evaluator digest starts a new run; it
does not silently alter an active run.

## Authority Separation

VPRO2 recognizes exactly five authorities:

1. **Controller** owns scheduling, Goal State aggregation, Gap Graph creation,
   candidate ranking, work issuance, budget accounting, transactions, path
   history, rollback or promotion, and terminal state. It cannot provide an
   evaluator verdict or edit the Milestone.
2. **Worker** decides how to execute one issued temporary objective in its
   staged transaction and declared scope. It cannot select the next objective,
   modify an evaluator, write controller state, or declare success.
3. **Reviewer** audits a proposed Gap Graph and objective before execution and
   audits scope and integrity after work. It is read-only, cannot approve
   capabilities, and cannot broaden or weaken the Milestone.
4. **Evaluator** runs the exact sealed executable against the current candidate
   product and admitted raw evidence. It emits structured, digest-bound
   condition, evidence, and causal-fact results. It cannot schedule work or
   modify the product.
5. **Operator** selects and protects the release and Milestone, supplies keys
   and non-rollback state, approves a digest-bound costly capability, and may
   abort a run. It cannot waive a condition, substitute evidence, or write a
   success verdict.

Messages use `vpro2-authority-envelope-v1`: run ID, role, action, nonce,
issuance and expiry, payload, and an authentication tag. Every role has a
distinct key identity. A role label without a valid role-bound envelope has no
authority. Replay-protection state consumes accepted nonces.

## Goal State

Every complete iteration begins with a fresh Milestone-level evaluation. The
controller runs all declared evaluators and verifies their exact result shape,
run ID, evaluator ID, input digest, product digest, exit-code consistency, and
workspace non-mutation.

The resulting Goal State contains one current evaluation for every immutable
success condition plus current evaluator-backed causal facts. A proven PASS
requires all of the following:

- status `PASS` from every evaluator assigned to the condition;
- current input and product bindings;
- a sealed evaluator report digest;
- all linked evidence requirements admitted as current and trusted;
- no missing, stale, untrusted, substituted, or downscaled evidence.

Worker or Reviewer prose is never added to Goal State. A numeric planning score
is never completion evidence. Goal State and its evidence basis have canonical
digests so the next plan, authority envelope, transaction, and terminal receipt
can bind the exact observation used for the decision.

## Gap Graph

The controller creates a Gap Graph from the current Goal State. Every non-PASS
condition is a node. Only current, trusted evaluator `BLOCKS` facts may create
causal edges. Unsupported explanations remain hypotheses and cannot change
completion or reset stagnation.

Strongly connected components are collapsed before root analysis. Roots are
ranked deterministically by their reachable required-condition impact, then by
bounded risk and cost criteria. Ranking decides where to investigate; it does
not turn partial work into success.

The kernel checks that every non-PASS condition is represented, every edge
cites current evaluator evidence, required blockers are not hidden by optional
work, and the ranking is reproducible. A fresh Reviewer then accepts or rejects
the selected proposal in an envelope bound to the sealed Goal State and Gap
Graph digests.

## Dynamic Objectives

Objectives are temporary controller-owned records, never Milestone inputs. A
candidate objective binds:

- the source Goal State and Gap Graph digests;
- one selected root blocker and a stable strategy key;
- the expected success-condition transitions and evaluators that will measure
  them;
- bounded context, write paths, tools, capabilities, time, bytes, and cost;
- the product baseline, staging transaction, and rollback reference;
- the relevant path-history fingerprint and evidence basis.

Before execution, the Reviewer must accept the proposal as traceable,
measurable, in-scope, affordable, capability-safe, and non-equivalent to an
already eliminated path under unchanged evidence. Rejected candidates consume
planning budget but never reach the Worker. If all candidates are illegal for
the configured number of planning rounds, the run terminates
`FAILED_NO_LEGAL_PLAN`.

Operator approval is required before a proposal using a declared restricted
capability can start. Approval binds the run, objective, strategy, contract,
product baseline, Goal State, capability, cost, nonce, and expiry. Approval is
authorization to attempt work, not acceptance evidence.

## Transaction And Evaluation Loop

The normative iteration is:

```text
BOUND
  -> MILESTONE_PRE_EVALUATE
  -> GOAL_STATE_SEALED
  -> SUCCESS_CHECK or GAP_GRAPH_BUILD
  -> GAP_AND_PLAN_REVIEW
  -> BUDGET_RESERVE
  -> optional OPERATOR_APPROVAL
  -> WORKSPACE_STAGE
  -> WORKER_EXECUTE
  -> SCOPE_AND_INTEGRITY_AUDIT
  -> MILESTONE_POST_EVALUATE
  -> GOAL_DELTA
  -> RETAIN_OR_ROLLBACK
  -> PATH_RECORD
  -> next MILESTONE_PRE_EVALUATE
```

Worker changes are made in a transaction derived from a sealed full-workspace
baseline. The work token authorizes only the objective's write subset, and the
controller rejects and fully restores out-of-scope changes before evaluating
them. Preventing the Worker process from attempting broader filesystem or host
effects requires the OS/container boundary described in `SECURITY.md`.
Evaluation runs against the staged candidate; the worker never promotes its
own output.

After every objective, all applicable independent evaluators run again. Raw
real-world capture need not be repeated merely because evaluator admission is
rerun, but the preserved capture must remain current under its configured
freshness, run, product, provenance, and no-substitution bindings.

## Goal Delta And Path Decisions

Goal Delta is a deterministic comparison between complete pre-work and
post-work Goal States:

- `MATERIAL_PROGRESS`: at least one required condition becomes a current,
  evaluator-proven PASS and no prior proven condition regresses;
- `REGRESSION`: any prior evaluator-proven PASS is lost, even if another
  condition improves;
- `INFORMATION_GAIN`: new trusted evaluator facts are learned without a new
  condition PASS;
- `NO_PROGRESS`: neither trusted goal progress nor new evaluator information
  appears.

Only `MATERIAL_PROGRESS` retains and promotes Worker changes. Regression,
information-only work, and no-progress work are rolled back. Information may
inform a later strategy, but it does not reset the consecutive material-
progress counter.

Path identity is deliberately fail-closed: root gap, write authority, and
capabilities define one causal action footprint. Renaming an objective or
strategy, changing prose or estimates, or reordering evaluators does not mint
a fresh path. A different tactic over the same footprint is deferred until new
trusted evaluator evidence reopens it. This conservative rule may eliminate
some legitimate same-filesystem alternatives, but it cannot turn relabeling
into repeated budget spend.

## Budgets And Failure

The Controller pessimistically charges objective reservations before issuance,
preflights a complete evaluator pass before execution, and checks observed
time, context, writes, transaction snapshots, reports, logs, and archived
evidence against the frozen limits and absolute wall deadline. Unused reservation is not refunded. Attempts cannot create a fresh
budget epoch by changing a failure message or objective title.

The run terminates with an authenticated failure receipt when any frozen policy
fires:

- consecutive complete iterations produce no material progress;
- the same environment class remains blocked for the configured limit;
- no legal executable objective survives review;
- any resource budget is exhausted or cannot cover the next required action;
- contract, evaluator, authority, state, transaction, or evidence integrity is
  anomalous;
- the Operator submits an authenticated abort.

An integrity anomaly is immediate failure. It is never converted to stagnation
or an opportunity for self-repair.

## Completion

Potential completion triggers one more fresh full evaluation. Success requires
every required condition to be current, trusted, and evaluator-proven, every
linked real-evidence requirement to be admitted, no active transaction or work
item, current contract/framework/evaluator/product digests, and valid authority
and event chains.

The terminal receipt binds the terminal status, reason, framework manifest,
Milestone, final Goal State and evidence basis, product and evaluator digests,
budget ledger, path history, state payload, and last event tag. Success and
failure use the same append-only audit discipline. `verify-terminal`
reconstructs the decision rather than trusting a stored status string.

## Genericity

Framework tests use unrelated synthetic Milestones and reject product names,
fixed objective IDs, hard-coded dependency graphs, domain-specific scales,
historical hashes, and implicit bundle paths in the kernel. No final-goal
meaning is inferred from prose; only sealed evaluator results carry acceptance
authority.
