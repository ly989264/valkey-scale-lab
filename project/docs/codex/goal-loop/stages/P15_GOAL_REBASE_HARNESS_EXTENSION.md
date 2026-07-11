# P15_GOAL_REBASE_HARNESS_EXTENSION — Goal-Loop Harness Extension

## Stage objective

Append the goal-loop stages P15-P26 to the existing harness without claiming management/fault runtime behavior.

## Required document reload

Read all required docs listed in `AGENTS.md`, then write `artifacts/goal_loop/P15_GOAL_REBASE_HARNESS_EXTENSION/CONTEXT_RELOAD.md`.

## Design subagent focus

The design subagent must inspect:

```text
codex/phase_manifest.json
codex/gate_lock.json
scripts/codex_gate.py
scripts/safety_scan.py
scripts/validate_json_schema.py
schemas/artifact/**/*.json
docs/codex/02_PHASES.md
docs/codex/04_AUDITOR.md
templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md
tests/**/*
```

It must propose the exact manifest additions, schemas, assertion scripts, tests, and audit hooks required for P15-P26.

## Worker implementation requirements

Implement the harness only:

- append P15-P26 manifest entries;
- set `automatic_stop_after` to `P26_FINAL_REPORT_REGRESSION`;
- preserve P14 as non-automatic opt-in dry-run;
- add schema files for quant, management, failover, fault, partition, split-brain, and workload impact artifacts;
- add assertion scripts that fail closed;
- add tests for assertion scripts and status taxonomy;
- update `docs/codex/02_PHASES.md` with P15-P26 summaries;
- update audit templates if needed so review artifacts are required;
- update harness lock only if necessary and explain why in the worker summary.

P15 may not implement runtime management/fault behavior except minimal stubs needed for tests. Do not claim real Valkey coverage in P15.

## Required gates

At minimum:

```bash
python3 scripts/codex_gate.py precheck --phase P15_GOAL_REBASE_HARNESS_EXTENSION
python3 scripts/safety_scan.py
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
python3 scripts/assert_goal_loop_stage.py --phase P15_GOAL_REBASE_HARNESS_EXTENSION
python3 scripts/codex_gate.py run --phase P15_GOAL_REBASE_HARNESS_EXTENSION
python3 scripts/codex_gate.py postcheck --phase P15_GOAL_REBASE_HARNESS_EXTENSION
```

If `precheck` cannot run before P15 exists in the manifest, first add the manifest entry and then run precheck before any completion claim.

## Required artifacts

```text
artifacts/phases/P15_GOAL_REBASE_HARNESS_EXTENSION/phase_summary.json
artifacts/phases/P15_GOAL_REBASE_HARNESS_EXTENSION/quant_summary.json
artifacts/goal_loop/P15_GOAL_REBASE_HARNESS_EXTENSION/CONTEXT_RELOAD.md
artifacts/goal_loop/P15_GOAL_REBASE_HARNESS_EXTENSION/DESIGN_BRIEF.md
artifacts/goal_loop/P15_GOAL_REBASE_HARNESS_EXTENSION/WORKER_SUMMARY.md
artifacts/goal_loop/P15_GOAL_REBASE_HARNESS_EXTENSION/REVIEW.md
artifacts/goal_loop/P15_GOAL_REBASE_HARNESS_EXTENSION/COMPLETION.md
```

## Review focus

The review subagent must verify that P15-P26 cannot pass without their required artifacts and that no existing safety rule was weakened.
