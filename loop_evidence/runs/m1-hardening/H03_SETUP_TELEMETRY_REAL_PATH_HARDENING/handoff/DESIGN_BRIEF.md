# H03 Design Brief

role: design
agent_invocation: real_subagent
stage_id: H03_SETUP_TELEMETRY_REAL_PATH_HARDENING
source_commit_before: 65089a70901e8ccb7be4af89bf0bee92ad4e2016

## Summary

Keep setup telemetry exact-scale claims blocked unless they are backed by a real exact-scale M1-format `setup_telemetry.json` with numeric C06 core metrics and complete per-node sample fields. The current repo has legacy exact-scale timing/e2e evidence, but no exact-scale M1 setup telemetry artifact, so H03 should prove fail-closed behavior rather than promote any setup claim.

## Key Recommendations

- Make setup claim semantics inspect `setup_telemetry.json`; do not let `runtime_timing_breakdown*.json` alone set `setup_core_metrics_present` or `m1_format_fields_complete`.
- Require these C06 core metrics to be numeric for exact-scale PASS: `nodehost_start_ms`, `node_config_generate_ms`, `node_config_distribute_ms`, `process_start_ms`, `process_ready_wait_ms`, `cluster_meet_ms`, `cluster_slots_assign_ms`, `replica_replicate_ms`, `cluster_convergence_probe_ms`, `full_cluster_probe_ms`, `cleanup_ms`, `total_setup_ms`.
- Require `per_node_samples` length at least the target scale, with each sample carrying non-missing node id, role, nodehost id, pid, numeric ready metric, cluster state, and known-node count.
- Treat `MISSING` and `SKIPPED_WITH_REASON` as valid encodings for blocked/dry-run/fixture/small-smoke artifacts only; any such value in C06 core metrics or required per-node fields must block/fail exact-scale PASS.
- Convert `assert_setup_core_metrics.py` into a setup hardening gate that exits 0 when unsafe PASS promotion is impossible. Its gate artifact should be `PASS` for the hardening check while reporting setup claims as blocked with explicit per-scale reasons.
- Extend H03 stage-exit requirements to include `assert_setup_core_metrics` plus the common no-fixture, no-legacy, taxonomy, manifest, and real-subagent gates.

## Expected Current Outcome

The setup claims should remain blocked:

- scale 30: no promotable exact-scale M1 setup telemetry
- scale 50/100/200: legacy real evidence exists, but not M1-format `setup_telemetry.json` with C06 numeric core metrics and complete per-node samples

H03 should pass only if those blocked states are explicit and no fixture, legacy timing file, non-empty artifact, skipped metric, or small-smoke artifact can become a setup telemetry PASS.
