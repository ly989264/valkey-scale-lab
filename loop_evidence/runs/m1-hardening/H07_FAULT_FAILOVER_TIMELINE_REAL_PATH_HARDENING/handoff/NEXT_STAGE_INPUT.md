# H08 Input

previous_stage: H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING
previous_status: PASS
previous_commit: PENDING_COMMIT

## Carry Forward

Fault/failover timeline exact-scale claims now fail closed. H08 can rely on H07 semantics when validating real system metrics windows that overlap setup, workload, management, and fault periods.

For H08 system metrics real-window hardening, pay special attention to:

- system metrics PASS must require real observed windows at the exact claimed scale;
- core CPU, memory, disk, network, container, host, and Valkey process metrics must be schema-validated and tied to concrete time windows;
- claimed system metric windows must align with real phase windows rather than arbitrary non-empty timeseries rows;
- skipped or missing core metrics must remain blocked with explicit reasons;
- fake, fixture, partial, dry-run, legacy-only, or generated-only system metrics must never promote milestone1 PASS;
- H08 gates should reject manifest-only PASS claims and honest blocked evidence should remain acceptable.

Required H07 artifacts:

- `runs/m1-hardening/H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING/artifacts/gates/assert_fault_timeline_real.json`
- `runs/m1-hardening/H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING/handoff/REVIEW.md`
- `runs/m1-hardening/evidence_manifest.json`
