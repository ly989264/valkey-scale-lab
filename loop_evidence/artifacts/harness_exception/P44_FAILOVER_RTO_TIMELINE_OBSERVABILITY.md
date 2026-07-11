# Harness Exception - P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY

## Defect

The user requested `P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY`, but the repository manifest and goal-loop stage documents ended at P43. The required stage document for P44 was absent, so the normal stage reload would otherwise be blocked.

## Patch Direction

Create a P44 stage document from the user-supplied contract and append a P44 manifest entry with stricter timeline, RTO, real-evidence, schema, and partial-coverage gates. This strengthens the harness by making the new requested phase machine-checkable instead of relying on chat memory.

## Before/After Behavior

Before: `docs/codex/goal-loop/stages/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY.md` did not exist and `scripts/codex_gate.py precheck --phase P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY` could not resolve the phase.

After: P44 is an explicit stage with required artifacts and fail-closed assertions for timeline completeness, metric semantics, and real scale coverage.
