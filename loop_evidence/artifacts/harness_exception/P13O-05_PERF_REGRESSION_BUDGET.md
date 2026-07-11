# Harness Exception: P13O-05_PERF_REGRESSION_BUDGET

## Defect

The P13 optimization loop defines `P13O-05_PERF_REGRESSION_BUDGET`, but the phase currently has only a minimal manifest entry and no machine-readable startup comparison schema or artifact validator. Without this harness extension, the loop cannot prove soft performance budgets for P13 scale_50/scale_100 startup while preserving real Valkey evidence.

## Patch

P13O-05 changes protected harness files only to add stronger verification:

- expand the P13O-05 manifest entry with focused tests, required 50/100 real Valkey gates, cleanup checks, and artifact validation;
- add a `p13_startup_optimization_comparison` schema;
- extend `scripts/p13_optimization_gate.py` to produce and validate soft budget results, with optional strict failure through `VSLAB_STRICT_PERF_BUDGET=1`;
- add unit coverage for default warning mode and strict fail mode.

## Before / After

Before: P13O-05 could not run as a complete phase because there were no gates, required artifacts, schema, or validation path.

After: P13O-05 records real 50/100 gate durations, startup sub-timings, wrapper probe time, cleanup time, unattributed time, and budget decisions in versioned artifacts while keeping real evidence in `scripts/valkey_e2e_gate.py`.
