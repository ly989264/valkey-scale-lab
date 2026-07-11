# H07 Input

previous_stage: H06_WORKLOAD_BENCHMARK_HARDENING
previous_status: PASS
previous_commit: PENDING_COMMIT

## Carry Forward

Workload benchmark exact-scale claims now fail closed. H07 can rely on H06 semantics when validating fault/failover workload impact references and timeline evidence.

For H07 fault/failover timeline hardening, pay special attention to:

- fake or partial fault timelines must never promote a real fault/failover PASS;
- fault/failover claims need real event timelines, latency samples, workload-window refs, cleanup refs, and Valkey 9.1.x evidence in one coherent exact-scale bundle;
- fault-period workload impact must cite H06-strength workload windows or remain blocked;
- split-brain, cluster-down, promotion, failover, recovery, clear, and cleanup metrics must be numeric or explicitly blocked with reasons;
- blocked fault claims must include explicit missing timeline, metric, workload, cleanup, and rerun reasons.

Required H06 artifacts:

- `runs/m1-hardening/H06_WORKLOAD_BENCHMARK_HARDENING/artifacts/gates/assert_workload_benchmark_strength.json`
- `runs/m1-hardening/H06_WORKLOAD_BENCHMARK_HARDENING/handoff/REVIEW.md`
- `runs/m1-hardening/evidence_manifest.json`
