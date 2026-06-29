# Harness Exception: P13O-03_CLEANUP_OPTIMIZATION

## Defect

The P13O-03 manifest entry only declared phase identity and did not include
phase-specific gates, required artifacts, audit paths, or a schema-backed
validator. The cleanup report also recorded actions without the required
cleanup timing breakdown, and process termination / verification used serial
loops for large P13 runs.

## Patch Scope

- Add P13O-03 manifest gates and required artifacts.
- Add a schema for the cleanup optimization artifact.
- Extend cleanup reports with `cleanup_timing` fields required by P13O-03.
- Use bounded parallelism for Valkey process termination, process-exit
  verification, nodehost residual checks, and owned container cleanup.
- Preserve cleanup evidence: no owned containers, no owned networks, and no
  observable Valkey process remaining.

## Before/After Behavior

Before this patch, P13O-03 could not prove cleanup timing or bounded cleanup
behavior through postcheck. After this patch, postcheck requires real Valkey
50/100 evidence, schema-valid cleanup optimization artifacts, cleanup reports
with required timing fields, and a fresh audit.
