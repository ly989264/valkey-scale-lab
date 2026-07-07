# Harness Exception: P45_CLEAN_GATE_LAYERED_DIAGNOSTICS

## Defect

The user requested stage `P45_CLEAN_GATE_LAYERED_DIAGNOSTICS`, but the repository had no stage document for it and `codex/phase_manifest.json` did not include a P45 entry. The stage reload protocol requires `docs/codex/goal-loop/stages/<CURRENT_STAGE>.md`; without that file the stage must fail closed.

## Patch

Added `docs/codex/goal-loop/stages/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS.md` from the user-supplied stage contract. The manifest entry, gates, schemas, and runtime implementation remain part of the stage work and must be verified before completion.

## Before/After Behavior

- Before: P45 could not start under the required document reload rule.
- After: P45 has an authoritative stage document so the normal context reload, design, worker, gate, and review loop can proceed.
