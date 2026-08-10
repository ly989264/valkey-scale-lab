# AGENTS.md - Valkey Scale Lab Product

This directory is the runnable `valkey-scale-lab` product root. AI controller
kernels, policy, prompts, runtime state, and generated evidence are not product
components and must not be restored here. Historical controller artifacts in
the sibling `../loop_evidence/` tree are read-only.

## Mission

Build `valkey-scale-lab`, a local-first Mac/Linux harness for real Valkey 9.1.x
cluster experiments. Machine-readable experiment artifacts are product output;
analysis and reports are derived views over validated artifacts.

## Product Safety Contract

- Provide an exact-node trigger for every requested size from 30 through 2000.
- Never silently downscale.
- Real runs above 200 are never automatic. They require explicit operator
  opt-in, resource preflight, and cost acknowledgement.
- Completion scales, promotion chains, and required suites belong only in
  `milestones/`; they are not product-library policy.

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
python3 -m valkey_scale_lab.cli gate execute --definition ... --nodes ...
python3 -m valkey_scale_lab.cli gate cleanup ...
python3 -m valkey_scale_lab.cli analyze ...
python3 -m valkey_scale_lab.cli report ...
```

`fault apply` and `fault clear` were part of this list until 2026-08-10, when the
operator approved deleting them with the module behind them. Fault injection is
the runtime adapter's actuator, reached through the run lifecycle, and there is
no CLI surface for it; see `docs/fault_sandbox_decision_memo.md`.

All scenario, evidence, and analysis APIs receive their definition explicitly;
they must not load a milestone or controller context implicitly.

## Evidence Contract

Real admission must include independently observed Valkey 9.1.x versions,
exact requested and observed node counts, cluster and slot health, lifecycle
sub-stage timing, management and fault matrices, workload windows, resource
telemetry, command logs, cleanup, provenance, analysis, and report references.

Schema/provenance checks must reject incomplete, fixture-derived, stale, or
fabricated evidence. Full logs stay on disk; automated consumers receive only
a bounded failure excerpt and paths/digests.

## Engineering Rules

- Read the relevant code and tests before changing behavior.
- Prefer existing patterns and structured parsers over new frameworks or ad hoc
  text processing.
- Keep edits scoped to the active objective and preserve unrelated user work.
- Add focused tests proportional to the behavioral risk.
- Run cheap/impacted checks before real or full-regression checks.
- Never weaken or delete a failing check to obtain a pass.
- Keep product regression tests hermetic. They must not read current or
  historical controller state from `../loop_evidence/`.
- Product tests must not import milestones. Milestone/catalog contract tests
  belong under `verification/tests/`.
- Do not add AI controller packages, prompts, state machines, or controller
  output links to this product tree.
