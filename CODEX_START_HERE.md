# CODEX_START_HERE.md — Autonomous Build Entry Point

This file is the start prompt for Codex App. Read `AGENTS.md` first, then execute the automatic phase loop without waiting for human intervention.

## Target repository

Create a production-quality project named `valkey-scale-lab` that can run Valkey 9.1.x cluster experiments locally on Mac/Linux Docker and can later distribute work across multiple Mac/Linux hosts. The system must test and analyze:

- cluster management performance metrics;
- management operation matrix behavior;
- failover effectiveness;
- split-brain and minority/majority behavior;
- stability and soak behavior;
- workload impact under normal, failure, and recovery periods;
- artifact-first analysis and reporting.

## First action

Run:

```bash
python3 scripts/codex_gate.py next
```

Then implement the returned phase only.

## Completion condition

The automatic loop is complete when all automatic phases through `P13_SCALE_LADDER_50_100` pass postcheck and are marked complete.

`P14_SCALE_1000_OPTIN_DRYRUN` is intentionally not automatic. It may only be run when the user explicitly opts in and sets:

```bash
export VSLAB_ALLOW_1000_DRYRUN=I_UNDERSTAND_THIS_IS_NOT_A_DEFAULT_GATE
```

## Required command sequence per phase

```bash
python3 scripts/codex_gate.py precheck --phase <PHASE_ID>
python3 scripts/codex_gate.py run --phase <PHASE_ID>
# create/verify artifacts and run fresh-context audit
python3 scripts/codex_gate.py postcheck --phase <PHASE_ID>
python3 scripts/codex_gate.py mark-complete --phase <PHASE_ID>
```

Do not write `PASS` manually into any gate result. Gate results must be produced by `scripts/codex_gate.py run`.

## Required implementation shape

Use this package and CLI contract:

```text
src/valkey_scale_lab/
  cli.py
  config/
  planner/
  runtime/
  valkey/
  workload/
  metrics/
  fault/
  analysis/
  report/
  orchestrator/
  artifacts/
```

Expose:

```bash
python3 -m valkey_scale_lab.cli config validate ...
python3 -m valkey_scale_lab.cli plan ...
python3 -m valkey_scale_lab.cli gate scenario ...
python3 -m valkey_scale_lab.cli gate cleanup ...
python3 -m valkey_scale_lab.cli fault apply ...
python3 -m valkey_scale_lab.cli fault clear ...
python3 -m valkey_scale_lab.cli analyze ...
python3 -m valkey_scale_lab.cli report ...
```

## Development constraints

- P00-P02 may use fakes for bootstrapping but must not claim the project is operational.
- P03 introduces real Valkey Docker e2e gates.
- P06 and later require a real Valkey e2e proof for every capability.
- Scale phases must execute real 10/30/50/100-node gates.
- 1000-node behavior is opt-in dry-run/resource-check only.

## Artifact discipline

Every run must produce machine-readable artifacts under `artifacts/`. The report layer may read artifacts but must not be the source of truth. Missing data must be encoded explicitly and must never be fabricated.

