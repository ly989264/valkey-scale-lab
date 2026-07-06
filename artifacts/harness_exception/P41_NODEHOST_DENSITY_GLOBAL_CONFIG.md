# Harness Exception — P41_NODEHOST_DENSITY_GLOBAL_CONFIG

## Defect

The user requested `P41_NODEHOST_DENSITY_GLOBAL_CONFIG`, but the repository did not contain a stage document under `docs/codex/goal-loop/stages/`. `AGENTS.md` requires the current stage document to exist and be reread before implementation.

## Patch

Added `docs/codex/goal-loop/stages/P41_NODEHOST_DENSITY_GLOBAL_CONFIG.md` by transcribing the user-provided phase requirements into a fail-closed stage contract. This strengthens the harness by making P41 explicit instead of relying on chat memory.

## Before / After

Before: P41 could not satisfy the required document reload rule because the stage document was absent.

After: P41 has an authoritative stage document that requires global nodehost config, density-limited runtime planning, resource preflight, coverage assertions, artifacts, and tests.
