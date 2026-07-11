# WORKER_SUMMARY — P18_MANAGEMENT_RESHARD_REBALANCE

## Worker role

This worker-summary agent did not implement source changes. The main agent implemented the P18 runtime, assertion, test, harness exception, and evidence artifacts. This worker inspected the stage context, current diff, and generated evidence, then summarized/validated the completed work for review.

No Docker commands were run by this worker. No files were modified except this `WORKER_SUMMARY.md`.

## Implementation summary

P18 now executes the required real Valkey reshard/rebalance management matrix:

- `reshard_slot_range` on 6 nodes and 10 nodes
- `reshard_with_keys` on 6 nodes and 10 nodes
- `rebalance_after_imbalance` on 6 nodes and 10 nodes

The runtime dispatch in `src/valkey_scale_lab/runtime/docker_runtime.py` was extended for `P18_MANAGEMENT_RESHARD_REBALANCE` / `management_reshard_rebalance`. The implementation follows the P17 sidecar pattern and creates bounded real 6-node and 10-node sidecar rows. Each row records operation results, topology snapshots, command logs, workload windows, metrics, slot movement evidence, rebalance evidence, quant summary, and cleanup summaries.

Slot movement uses live Valkey cluster commands through owned Docker containers: `CLUSTER SETSLOT IMPORTING`, `CLUSTER SETSLOT MIGRATING`, optional `MIGRATE ... KEYS`, and `CLUSTER SETSLOT ... NODE`. It verifies clean cluster state, full slot coverage, source/target ownership, moved-key readability where required, and post-move writes.

The rebalance rows intentionally create an imbalance first, then move slots back to reduce the measured primary slot-count spread. No no-op rebalance is accepted as a pass condition.

## Files changed by the main agent

- `src/valkey_scale_lab/runtime/docker_runtime.py`
  - Added P18 scenario allow-list, expected outer node count, runtime dispatch, sidecar row execution, deterministic slot/key helpers, slot movement command logging, workload windows, topology snapshots, slot movement artifacts, rebalance summary, quant/phase summaries, and cleanup summaries.
- `scripts/assert_management_ops_coverage.py`
  - Strengthened P18 checks to require all exact 6-node and 10-node rows, positive slot movement, clean cluster state, full slot coverage, post-move writability, source/target node IDs, movement IDs, moved-key verification for keyed rows, and imbalance reduction for rebalance rows.
  - Validates `reshard_slot_movements.jsonl` and `rebalance_summary.json`.
- `tests/unit/test_goal_loop_assertions.py`
  - Added P18 assertion regression tests for missing 10-node coverage, zero slot movement, and no-op rebalance rejection.
- `artifacts/harness_exception/P18_MANAGEMENT_RESHARD_REBALANCE.md`
  - Documents the harness defect and strengthening patch.
- P18 gate and phase artifacts under:
  - `artifacts/gates/P18_MANAGEMENT_RESHARD_REBALANCE/`
  - `artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/`
  - `artifacts/goal_loop/P18_MANAGEMENT_RESHARD_REBALANCE/`

## Real-gate results

`artifacts/gates/P18_MANAGEMENT_RESHARD_REBALANCE/gate_result.json` reports `status: PASS`.

Required gate rows all passed:

- `harness_precheck`: PASS
- `safety_static_scan`: PASS
- `scripts_compile`: PASS
- `unit_integration_tests`: PASS
- `goal_loop_stage_assertion`: PASS
- `real_valkey_e2e`: PASS, duration 84.312478 seconds
- `quant_artifact_assertion`: PASS
- `management_ops_assertion`: PASS
- `workload_impact_assertion`: PASS
- `cleanup_report_check`: PASS

The real Valkey evidence reports:

- `real_valkey: true`
- `valkey_versions: ["9.1.0"]`
- `nodes_observed: 6`
- `cluster_state_observed: ok`
- `data_path_result: PASS`
- scenario `management_reshard_rebalance`

## Six-row evidence summary

| Operation ID | Node count | Status | Slots moved | Keys moved | Data-path proof | Slot coverage | Rebalance proof |
| --- | ---: | --- | ---: | ---: | --- | --- | --- |
| `reshard_slot_range-06` | 6 | PASS | 4 | 0 | `post_move_writable=true` | `slots_after=16384`, `cluster_state_after=ok` | N/A |
| `reshard_slot_range-10` | 10 | PASS | 4 | 0 | `post_move_writable=true` | `slots_after=16384`, `cluster_state_after=ok` | N/A |
| `reshard_with_keys-06` | 6 | PASS | 4 | 4 | `moved_keys_readable=true`, `post_move_writable=true` | `slots_after=16384`, `cluster_state_after=ok` | N/A |
| `reshard_with_keys-10` | 10 | PASS | 4 | 4 | `moved_keys_readable=true`, `post_move_writable=true` | `slots_after=16384`, `cluster_state_after=ok` | N/A |
| `rebalance_after_imbalance-06` | 6 | PASS | 5 | 0 | `post_move_writable=true` | `slots_after=16384`, `cluster_state_after=ok` | imbalance `19.0 -> 9.0` |
| `rebalance_after_imbalance-10` | 10 | PASS | 5 | 0 | `post_move_writable=true` | `slots_after=16384`, `cluster_state_after=ok` | imbalance `20.0 -> 10.0` |

All six rows have `real_execution_verified=true`, `cluster_state_before=ok`, `cluster_state_after=ok`, `slots_before=16384`, `slots_after=16384`, `slot_coverage_complete=true`, and operation status `PASS`.

## Slot movement, key verification, and rebalance evidence

`artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/reshard_slot_movements.jsonl` contains six PASS movement rows:

- `reshard_slot_range-06-reshard_slot_range-5461-5464`: 4 slots moved.
- `reshard_slot_range-10-reshard_slot_range-6553-6556`: 4 slots moved.
- `reshard_with_keys-06-reshard_with_keys-5473-5476`: 4 slots moved, 4 keys moved.
- `reshard_with_keys-10-reshard_with_keys-6565-6568`: 4 slots moved, 4 keys moved.
- `rebalance_after_imbalance-06-rebalance_after_imbalance-10922-10926`: 5 slots moved.
- `rebalance_after_imbalance-10-rebalance_after_imbalance-9830-9834`: 5 slots moved.

`artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/rebalance_summary.json` reports `status: PASS` and includes both rebalance rows. The aggregate imbalance summary is `20.0 -> 9.0`; per-row evidence is:

- 6-node rebalance: imbalance `19.0 -> 9.0`, with per-primary slot counts before and after.
- 10-node rebalance: imbalance `20.0 -> 10.0`, with per-primary slot counts before and after.

`artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/management_command_log.jsonl` contains 284 PASS command rows:

- 46 `cluster_setslot_importing`
- 46 `cluster_setslot_migrating`
- 184 `cluster_setslot_node`
- 8 `cluster_migrate_keys`

`artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/management_topology_snapshots.jsonl` contains 24 snapshots, four per required row.

## Quantification and cleanup evidence

`artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/quant_summary.json` reports `status: PASS` with:

- `operation_count: 6`
- `six_node_operation_count: 3`
- `ten_node_operation_count: 3`
- `slot_movement_count: 6`
- `rebalance_operation_count: 2`
- `workload_window_count: 36`
- `metric_count: 720`
- `event_count: 74`
- `topology_snapshot_count: 24`
- `command_log_count: 284`

`artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/workload_windows.json` reports `status: PASS` with 36 workload windows. Windows include QPS, latency percentiles, sample count, timeout count, MOVED/ASK redirects, connection errors, cluster-down errors, readonly errors, tryagain errors, unknown errors, and error rate. `management_workload_impact.json` reports `status: PASS`.

`artifacts/phases/P18_MANAGEMENT_RESHARD_REBALANCE/cleanup_report.json` reports `status: PASS` and `resources_remaining: []`. Per-row cleanup summaries in `quant_summary.json` are PASS for all six operation IDs, with no resources remaining.

## Harness exception summary

`artifacts/harness_exception/P18_MANAGEMENT_RESHARD_REBALANCE.md` records a strengthening exception. The defect was that the previous management assertion could accept P18 operation-name coverage without enforcing exact 6-node/10-node rows, positive slot movement, moved-key verification, or non-noop rebalance evidence.

The patch strengthens `scripts/assert_management_ops_coverage.py` so P18 now fails closed unless all six required rows pass with real execution, positive slot movement, full slot coverage, post-move writability, keyed-row readability, and measured rebalance improvement. It also validates `reshard_slot_movements.jsonl` and `rebalance_summary.json`.

## Residual risks for review

- P18 deliberately uses small bounded slot batches, 4 slots for reshard rows and 5 slots for rebalance rows, to keep local real gates deterministic. This proves the operation path and artifact contract, but not large reshard throughput.
- `bytes_migrated` is encoded as `MISSING` with a reason because the Valkey command path does not expose migrated byte counts.
- `management_workload_impact.json` aggregates canonical workload windows, while the full per-operation canonical fields are in `workload_windows.json`.
- The main e2e gate observes the outer 6-node scenario; the 10-node rows are produced by the P18 sidecar matrix and enforced by the strengthened management assertion and artifacts.
