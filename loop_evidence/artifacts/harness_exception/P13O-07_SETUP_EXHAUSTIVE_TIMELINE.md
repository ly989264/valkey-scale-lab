# Harness Exception: P13O-07_SETUP_EXHAUSTIVE_TIMELINE

## Reason

P13O-07 adds a new automatic optimization gate for the existing P13 50/100-node real Valkey scale ladder. The phase requires new machine-readable setup timeline validation, so the P13O harness had to be extended instead of bypassed.

Protected harness-style files changed:

- `scripts/p13_optimization_gate.py`
- `schemas/artifact/p13_setup_exhaustive_timeline.schema.json`
- `docs/codex/05_P13_OPTIMIZATION_LOOP.md`

Related P13O control files changed:

- `codex/p13_optimization_manifest.json`
- `codex/status/p13_optimization_state.json`

## Defect Or Missing Harness Coverage

Before this phase, P13 setup had timing entries and wrapper-level `setup_command_wall`, but no harness-enforced artifact that proved the setup subprocess was covered by a sequential, non-overlapping, explicit-gap timeline. P13O postcheck also had no stale-source check tying a timeline artifact to the exact P13 timing and real Valkey evidence artifacts that produced it.

## Patch

The patch strengthens the harness by adding:

- a P13O-07 manifest phase that is automatic, real-Valkey-required, capped at 100 nodes, and runs both `scale_50` and `scale_100` with `--require-data-path`;
- a JSON schema for `p13_setup_exhaustive_timeline`;
- P13O artifact validation that requires both source setup timelines, the aggregate P13O timeline, phase summary, real Valkey evidence, cleanup evidence, source freshness hashes, required segment coverage, parent/child non-double-counting, and `setup_timeline_unexplained_seconds <= 2.0`;
- postcheck behavior that fails on missing or stale setup timeline artifacts instead of silently passing;
- documentation of P13O-07 requirements and pass criteria.

## Before And After Behavior

Before:

- `setup_command_wall` was recorded only by the outer wrapper.
- setup subprocess timings were partial and could leave large unexplained differences.
- parent timings and child timings were not represented in an explicit hierarchy with exclusive duration semantics.
- no schema or P13O validator enforced exhaustive setup timeline coverage.

After:

- `valkey_scale_lab.cli gate scenario` emits a setup timeline for P13 `scale_50` and `scale_100`.
- timeline segments are ordered and non-overlapping; gaps are explicit `kind: "gap"` segments.
- parent phases are hierarchy-only aggregates with `inclusive_duration_seconds`, `exclusive_duration_seconds`, and `children`.
- P13 timing artifacts reference the setup timeline path.
- P13O-07 validator requires real 50/100-node Valkey evidence, data-path proof, cleanup proof, schema validation, and stale-source detection.
- P14 remains opt-in only and no default gate exceeds 100 nodes.

## Safety

This exception does not loosen safety rules. It does not modify host networking, firewall, routing, interfaces, or global OS services. It does not add `sudo`. It does not remove real Valkey gates or replace them with mocks. The new phase preserves the default maximum of 100 nodes and does not execute P14.
