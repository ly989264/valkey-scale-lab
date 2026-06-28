# CODE_REVIEW.md — Custom Codex Review Instructions

Review against the current phase in `codex/phase_manifest.json`.

Reject the change if:

- it weakens harness scripts, schemas, manifest, or templates;
- it marks fake-only tests as real Valkey evidence;
- a required artifact is missing or schema-invalid;
- cleanup is missing or non-deterministic;
- host-level network mutation is introduced;
- scale defaults exceed 100 nodes;
- missing metrics are silently filled with fabricated values;
- audit files do not cite gate result path and SHA256;
- real gates are skipped without phase failure.

Prefer small, deterministic, testable components. Do not accept large unreviewable changes that bypass phase boundaries.

