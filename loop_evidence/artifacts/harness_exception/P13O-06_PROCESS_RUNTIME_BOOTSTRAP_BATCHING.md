# Harness Exception — P13O-06_PROCESS_RUNTIME_BOOTSTRAP_BATCHING

## Defect

The post-P13 optimization harness ended at `P13O-05_PERF_REGRESSION_BUDGET`, so it had no manifest entry, artifact schema, artifact validator, or phase documentation for the requested `P13O-06_PROCESS_RUNTIME_BOOTSTRAP_BATCHING` optimization. Without extending the P13O harness, the phase could not be prechecked, gated, audited, postchecked, marked complete, or schema-validated.

## Patch

The patch preserves and strengthens the existing harness by adding only the P13O-06 phase contract:

- `codex/p13_optimization_manifest.json` now declares P13O-06 gates for focused tests, P13 scale_50/scale_100 real Valkey evidence, cleanup checks, and artifact validation.
- `docs/codex/05_P13_OPTIMIZATION_LOOP.md` now documents the P13O-06 objectives and pass criteria.
- `scripts/p13_optimization_gate.py` now validates and writes the P13O-06 batching artifact and phase summary.
- `schemas/artifact/p13_process_bootstrap_batching.schema.json` validates the new machine-readable artifact.

## Before/After Behavior

Before this patch, `python3 scripts/p13_optimization_gate.py next` returned `COMPLETE_P13_OPTIMIZATION_PHASES`, and `P13O-06_PROCESS_RUNTIME_BOOTSTRAP_BATCHING` was unknown to precheck/postcheck.

After this patch, `python3 scripts/p13_optimization_gate.py next` returns `P13O-06_PROCESS_RUNTIME_BOOTSTRAP_BATCHING`, and the phase must pass focused tests, P13 50/100 real Valkey gates with `--require-data-path`, cleanup checks, artifact schema validation, audit, postcheck, and mark-complete. The patch does not alter P14 opt-in behavior, default max nodes, or P13 real-evidence requirements.
