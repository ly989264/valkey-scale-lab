# H06 Input

previous_stage: H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
previous_status: PASS
previous_commit: PENDING_COMMIT

## Carry Forward

Management matrix exact-scale claims now fail closed. H06 can rely on H05 semantics when validating workload benchmark evidence and its relationship to management/fault windows.

For H06 workload benchmark hardening, pay special attention to:

- workload benchmark rows must be exact-scale M1-format evidence, not legacy-only or generated summaries;
- skipped or missing core workload metrics must remain `BLOCKED_WITH_REASON`;
- QPS, latency, error, timeout, redirection, and window counts must be schema-valid numeric measurements with real workload windows;
- workload artifacts should trace to real Valkey 9.1.x evidence and command/audit records, not fixtures or static placeholder files;
- blocked workload claims must include explicit reasons rather than weak non-empty checks.

Required H05 artifacts:

- `runs/m1-hardening/H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING/artifacts/gates/assert_management_exact_scale.json`
- `runs/m1-hardening/H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING/handoff/REVIEW.md`
- `runs/m1-hardening/evidence_manifest.json`
