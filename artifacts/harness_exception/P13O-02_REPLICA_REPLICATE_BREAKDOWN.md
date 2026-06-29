# Harness Exception: P13O-02_REPLICA_REPLICATE_BREAKDOWN

## Defect

The P13O-02 manifest entry only declared the phase identity and did not include
phase-specific gates, required artifacts, audit paths, or a schema-backed
validator. The runtime also recorded `replica_replicate` as a single aggregate
duration with no required breakdown fields or per-replica diagnostics.

## Patch Scope

- Add P13O-02 manifest gates and required artifacts.
- Add a schema for the replica replication breakdown artifact.
- Extend `scripts/p13_optimization_gate.py` to validate P13O-02 evidence and
  generate the required machine-readable artifacts.
- Add runtime timing details for bounded replica replication sub-steps without
  weakening role-count, full membership, data-path, or cleanup proof.
- Keep default node scale capped at 100 and keep P14 opt-in only.

## Before/After Behavior

Before this patch, P13O-02 could not independently prove its stated timing
breakdown requirements through postcheck. After this patch, postcheck requires
real Valkey 50/100 evidence, schema-valid breakdown artifacts, slowest-replica
diagnostics, explicit bounded parallelism, cleanup evidence, and a fresh audit.
