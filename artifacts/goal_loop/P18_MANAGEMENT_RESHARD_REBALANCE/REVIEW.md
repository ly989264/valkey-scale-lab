# REVIEW — P18_MANAGEMENT_RESHARD_REBALANCE

## Scope

Fresh-context review of P18 reshard/rebalance implementation and generated evidence. I inspected the controlling context, P18 stage spec, audit prompt, stage reload/design/worker artifacts, current diff, gate result, lock update, and P18 phase artifacts. I did not run Docker and did not modify source, tests, manifests, schemas, gate lock, phase artifacts, or audit files.

## Gate Evidence

- `artifacts/gates/P18_MANAGEMENT_RESHARD_REBALANCE/gate_result.json` reports `status: PASS`.
- Gate result SHA256: `c405ed4f5356dbf91b16a1cc023c4b55de98787019e0fc84f276420d3f794e2d`.
- All manifest gates are present and PASS: `harness_precheck`, `safety_static_scan`, `scripts_compile`, `unit_integration_tests`, `goal_loop_stage_assertion`, `real_valkey_e2e`, `quant_artifact_assertion`, `management_ops_assertion`, `workload_impact_assertion`, and `cleanup_report_check`.
- Gate command text matches the P18 manifest entry in `codex/phase_manifest.json`.
- Stored stdout/stderr SHA256 values match the log files. Representative hash: `management_ops_assertion` stdout `4a2f854a7cd95cd30c1b0dfaf30d6b4ec5803b5c0410a1ce5792a9cb755ae7e0`; all stderr logs are empty-hash `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- `valkey_e2e_evidence.json` reports `real_valkey: true`, `valkey_versions: ["9.1.0"]`, `nodes_observed: 6`, `cluster_state_observed: ok`, and `data_path_result: PASS`.

## Required Artifact Citations

- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/phase_summary.json`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/valkey_e2e_evidence.json`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/cleanup_report.json`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/events.jsonl`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/metrics_timeseries.jsonl`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/workload_windows.json`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/quant_summary.json`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/management_ops_matrix.json`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/management_operation_results.jsonl`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/management_workload_impact.json`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/management_topology_snapshots.jsonl`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/management_command_log.jsonl`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/reshard_slot_movements.jsonl`
- `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/rebalance_summary.json`

## Findings

No blocking findings.

The six required rows are present in both `management_ops_matrix.json` and `management_operation_results.jsonl`, all with `operation_status: PASS`, `real_execution_verified: true`, clean before/after cluster state, `slots_before: 16384`, `slots_after: 16384`, `slot_coverage_complete: true`, workload refs, zero command errors, and sidecar cleanup PASS:

- `reshard_slot_range-06`: 6 nodes, 4 slots moved.
- `reshard_slot_range-10`: 10 nodes, 4 slots moved.
- `reshard_with_keys-06`: 6 nodes, 4 slots moved, 4 keys moved, moved keys readable, post-move writes pass.
- `reshard_with_keys-10`: 10 nodes, 4 slots moved, 4 keys moved, moved keys readable, post-move writes pass.
- `rebalance_after_imbalance-06`: 6 nodes, 5 slots moved, imbalance `19.0 -> 9.0`.
- `rebalance_after_imbalance-10`: 10 nodes, 5 slots moved, imbalance `20.0 -> 10.0`.

10-node sidecar evidence is present and asserted. The 10-node sidecar state files contain 10 nodes with 5 primaries and 5 replicas, and topology snapshots for all 10-node rows show `known_nodes: 10`, `primary_count: 5`, `replica_count: 5`, `assigned: 16384`, `ok: 16384`, `fail: 0`, and `cluster_state: ok`. `scripts/assert_management_ops_coverage.py` now requires the exact P18 `(operation_name, node_count)` rows and the gate log shows `PASS management operation coverage phase=P18_MANAGEMENT_RESHARD_REBALANCE`.

Slot movement is positive and tied to real Valkey commands. `reshard_slot_movements.jsonl` contains six PASS movement rows with positive `slot_count`, source/target node IDs, operation IDs, and `bytes_migrated: MISSING` with a reason. `management_command_log.jsonl` contains PASS `CLUSTER SETSLOT ... IMPORTING`, `CLUSTER SETSLOT ... MIGRATING`, `CLUSTER SETSLOT ... NODE`, and keyed `MIGRATE ... KEYS ...` entries. The keyed rows include 8 total `cluster_migrate_keys` commands, 4 for each `reshard_with_keys` row.

Rebalance is not a no-op. `rebalance_summary.json` is PASS, includes per-row movement IDs and primary slot-count maps, and shows numeric imbalance reduction for both 6-node and 10-node rows. The implementation also creates a setup imbalance before the measured rebalance movement.

Workload, topology, command logs, and cleanup are adequate for P18. `workload_windows.json` contains 36 PASS windows across all six operations with QPS, latency percentiles, sample counts, timeout, MOVED/ASK, connection, cluster-down, readonly, tryagain, unknown error, and error-rate fields. `management_topology_snapshots.jsonl` contains 24 snapshots, four per operation (`before`, `during_before_command`, `during_after_command`, `after`). `cleanup_report.json` and every sidecar cleanup report are PASS with `resources_remaining: []`.

Safety evidence is adequate. `safety_static_scan` passed, and targeted review of the P18 diff and command log found no host firewall, routing, interface, global network service, privileged-container, `NET_ADMIN`, or sudo network mutation path. Runtime changes are scoped to owned Docker containers/networks with deterministic names and bounded 6/10-node execution.

The harness exception strengthens requirements. `artifacts/harness_exception/P18_MANAGEMENT_RESHARD_REBALANCE.md` documents the prior assertion gap and the patch strengthens `scripts/assert_management_ops_coverage.py` to reject missing 10-node rows, zero movement, missing keyed data-path proof, and no-op rebalance. The refreshed `codex/gate_lock.json` hash for that script matches the current file: `ce0b266fa62ee5fa75d17a413fdae7766c332a5348074a67e0d63262af71b632`.

## Residual Risk

P18 proves bounded small-batch slot movement, not large reshard throughput. That is acceptable for this stage because the required rows, real command path, data-path checks, workload measurements, and artifact contracts are satisfied.

Decision: PASS
