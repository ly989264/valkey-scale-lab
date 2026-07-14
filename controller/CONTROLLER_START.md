# Controller Start

The controller is the active goal-driven release rooted directly at
`controller/`.

## Production Preconditions

Before a trusted run, an external Operator must provide:

- an extracted, read-only controller release;
- the release's embedded `codex/framework_manifest.json`;
- an external read-only `controller-framework-receipt-v1` authorizing that exact
  manifest digest;
- an external immutable `controller-milestone-v2` contract;
- a project root inside an isolated Worker workspace;
- a new empty controller run root outside the Worker workspace;
- five distinct role credentials plus a distinct state-seal key;
- protected evaluator and tool executables;
- non-rollback or append-only controller storage;
- OS, container, or service separation that prevents the Worker UID from
  reading keys or changing the release, receipt, contract, evaluators, or run
  root.

The repository's eventual release receipt is a development/distribution
receipt. Copy it outside the Worker workspace and protect it before a real run.

## Launch

Always use an operator-selected absolute Python path and isolated flags:

```bash
export CONTROLLER_FRAMEWORK_RECEIPT=/operator/controller/framework_receipt.json

/operator/python3 -I -S -B /operator/controller/CONTROLLER_LAUNCH.py --help
```

The launcher refuses relative or missing receipt paths. It verifies the
external receipt, embedded manifest, complete file closure, launcher, and
protected paths before importing `controller`. Direct `PYTHONPATH=src python -m
controller` startup is not trusted.

Runtime commands also require protected key files:

```text
CONTROLLER_STATE_HMAC_KEY_FILE
CONTROLLER_CONTROLLER_HMAC_KEY_FILE
CONTROLLER_WORKER_HMAC_KEY_FILE
CONTROLLER_REVIEWER_HMAC_KEY_FILE
CONTROLLER_EVALUATOR_HMAC_KEY_FILE
CONTROLLER_OPERATOR_HMAC_KEY_FILE
```

Each file must be absolute, single-link, mode `0600` or stricter, contain at
least 32 bytes, and remain outside the framework, Worker, and run roots. The
keys must be distinct. The controller deliberately has no signing command; each role's
protected service signs its own canonical authority envelope.

There is no runtime command to update or reseal the framework, repair its
evaluators, import retired controller state, edit a Milestone, or manufacture a role
signature.

## Author A Milestone

Start from `templates/milestone.template.json` outside the Worker
workspace. Replace every `REPLACE` value and provide real independent evaluator
executables and output schemas.

The contract may define final goal, success conditions, evaluators, evidence,
safety, budgets, and termination only. It must not define objectives,
dependencies, profiles, gates, implementation order, or a reduced completion
claim.

A required real-evidence entry must retain:

```json
{
  "capture_class": "REAL",
  "provenance_required": true,
  "freshness": {
    "max_age_seconds": 86400,
    "bind_to_product_digest": true,
    "bind_to_run_id": true
  },
  "substitution_policy": "FORBIDDEN"
}
```

## Run Discipline

The first action after bind is a full Milestone evaluation, not a Worker task.
The controller then repeats this closed loop:

```text
evaluate Milestone
  -> seal Goal State
  -> build and review Gap Graph
  -> generate, review, and reserve one temporary objective
  -> obtain operator capability approval when required
  -> execute Worker changes in a staged transaction
  -> audit scope and integrity
  -> re-evaluate independent Milestone evaluators
  -> compute Goal Delta
  -> retain material progress or roll back
  -> record or eliminate the path
```

Only a new current evaluator-proven success-condition PASS without regression
is material progress. New diagnostic information may guide the next plan but
does not retain product changes or reset stagnation. An equivalent eliminated
path remains blocked until new trusted evaluator evidence changes its basis.

Do not run unchanged expensive evaluators, real capture, Worker commands, or
capability-bearing operations outside the controller. Do not hand-edit state,
events, budgets, Goal States, evidence admission, or terminal receipts.

The CLI lifecycle is:

```text
milestone-validate
bind-challenge -> external Operator signs BIND -> bind
evaluate
submit-plan -> review-plan -> optional approve-objective
worker-result -> review-change -> evaluate
status | audit | verify-terminal
```

All runtime commands take explicit `--project-root`, `--workspace-root`,
`--contract`, and `--run-root` arguments. `bind` and `bind-challenge` also take
`--run-id`; authority-bearing commands take `--envelope` and reject the wrong
role, action, run, expiry, binding, or a reused nonce.

## Terminal Result

Success requires a final fresh full evaluation in which every required success
condition and linked real-evidence requirement is current and independently
proven. Stagnation, persistent environment blocking, no legal plan, exhausted
budget, integrity anomaly, or authenticated Operator abort produces an explicit
failure receipt instead.

Both terminal outcomes are audited and sealed. Preserve the exact framework
receipt, Milestone contract, run root, evaluator reports, evidence references,
and terminal receipt together.

See `docs/ARCHITECTURE.md` and `docs/SECURITY.md` before production deployment.
