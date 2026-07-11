# AGENTS.md - Valkey Scale Lab

This `project/` directory is the runnable repository root. Historical evidence
lives in `../loop_evidence/`; never rewrite historical runs.

## Mission

Build `valkey-scale-lab`, a local-first Mac/Linux harness for real Valkey 9.1.x
cluster experiments. Machine-readable artifacts are the product; analysis and
reports are derived views over validated artifacts.

## Milestone 1 Goal Mode

New Codex App Goal-mode work for Milestone 1 starts at `META_M1_START.md` and is
scheduled only by:

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop next
```

The four authorities are deliberately separate:

- Codex owns how to solve the current objective. It may inspect, design, edit,
  test, and refactor freely within the frozen Milestone 1 scope.
- The controller owns what happens next, the current objective, attempt counts,
  stagnation routing, review budgets, and validation level ordering.
- Executable program checks own pass/fail. Prose, self-reported success, and
  hand-edited state are never completion evidence.
- A fresh reviewer looks only for a requirement gap not covered by the current
  program checks. A blocking finding must cite an exact frozen clause and add
  one level 0-2 check that demonstrably fails before the fix. Review may not
  broaden Milestone 1 or fail work for taste.

The Controller Kernel and Goal Contract are immutable in a run. The evidence
evaluator is separately versioned: a reproduced `EVALUATOR_GAP` must use the
controller-owned `EVALUATOR_REPAIR` transition. Direct evaluator edits are
rejected. Product and evaluator digests are separate, so strengthening an
evaluator does not by itself force another real cluster run.

Do not recreate the historical design/worker/review ceremony for each stage.
Do not manually edit controller state. Do not rerun unchanged failing or
expensive commands outside the controller. Follow the work item returned by
`next`, then use `evaluate` or `review` as instructed.

Repository regression tests must be hermetic and must not read current
`loop_evidence/meta_runs` data. Dynamic real-evidence checks belong in the
versioned evaluator. A real gate must not modify historical `loop_evidence/artifacts`.

The old P/M1-S/H stage documents and evidence remain useful product history,
but their fixed stage order, mandatory document reload, per-stage subagents,
and per-stage commit protocol are not the current Milestone 1 controller.

## Frozen Scale Contract

- Provide an exact-node trigger for every requested size from 30 through 2000.
- The required real completion gates are exactly 50 and 200 nodes.
- Keep 30 and 100 runnable, but do not require them as completion gates.
- Never silently downscale.
- Real runs above 200 are never automatic. They require explicit operator
  opt-in, resource preflight, and cost acknowledgement.
- Normal development remains capped at 100 nodes. The required 200-node gate is
  a preflight-gated bounded exception.

## Safety Rules

1. Never modify host networking, firewall, routing, interfaces, or unrelated
   host processes.
2. Fault injection must stay inside owned containers, namespaces, processes, or
   a project-owned sandbox proxy.
3. Every started resource needs deterministic ownership and cleanup.
4. Ports, directories, PIDs, container names, and run IDs must be collision
   checked and attributable.
5. Fake tests are useful development checks but are never real Valkey evidence.
6. Missing data is `MISSING`, `SKIPPED_WITH_REASON`, or
   `UNSUPPORTED_WITH_REASON` with a reason; never invent values.
7. A resource-preflight failure blocks a real gate. It never converts a smaller
   run, fixture, or dry run into success.

## Product Interface

Preserve the importable `valkey_scale_lab` package and these established CLI
families:

```text
python3 -m valkey_scale_lab.cli config validate ...
python3 -m valkey_scale_lab.cli plan ...
python3 -m valkey_scale_lab.cli gate scenario ...
python3 -m valkey_scale_lab.cli gate cleanup ...
python3 -m valkey_scale_lab.cli fault apply ...
python3 -m valkey_scale_lab.cli fault clear ...
python3 -m valkey_scale_lab.cli analyze ...
python3 -m valkey_scale_lab.cli report ...
```

Existing commands remain backward compatible. New commands may be added when
they improve the exact-node trigger or full lifecycle.

## Evidence Contract

Real admission must include independently observed Valkey 9.1.x versions,
exact requested and observed node counts, cluster and slot health, lifecycle
sub-stage timing, management and fault matrices, workload windows, resource
telemetry, command logs, cleanup, provenance, analysis, and report references.

Schema/provenance checks must reject incomplete, fixture-derived, stale, or
fabricated evidence. Full logs stay on disk; Goal-mode context receives only a
bounded failure excerpt and paths/digests.

## Engineering Rules

- Read the relevant code and tests before changing behavior.
- Prefer existing patterns and structured parsers over new frameworks or ad hoc
  text processing.
- Keep edits scoped to the active objective and preserve unrelated user work.
- Add focused tests proportional to the behavioral risk.
- Run cheap/impacted checks before real or full-regression checks.
- Never weaken or delete a failing check to obtain a pass. A missing evaluator
  check must use `EVALUATOR_GAP` and the controlled repair transition; Goal
  Contract or Kernel defects require a new controller version.
