# DESIGN_BRIEF — P18_MANAGEMENT_RESHARD_REBALANCE

## Objective

Implement real Valkey 9.1.x reshard and rebalance management rows for both 6-node and 10-node clusters. P18 must not pass on placeholder artifacts, operation-name-only coverage, empty slot movement, or no-op rebalance. The six required rows are fixed:

- `reshard_slot_range` on 6 nodes
- `reshard_slot_range` on 10 nodes
- `reshard_with_keys` on 6 nodes
- `reshard_with_keys` on 10 nodes
- `rebalance_after_imbalance` on 6 nodes
- `rebalance_after_imbalance` on 10 nodes

## Current Repository Findings

- `src/valkey_scale_lab/runtime/docker_runtime.py` has the P17 sidecar management matrix pattern, but P18 is not yet whitelisted in `create_scenario()`, not present in `_scenario_node_count_allowed()`, and not dispatched after cluster setup. The current P18 real gate would fail before producing P18 artifacts.
- P17 already proves the practical pattern: a 6-node outer wrapper can launch bounded real 6-node and 10-node sidecar rows, then assertions enforce exact row coverage and semantics.
- `templates/configs/local_az_3x2.yaml` provides 6 nodes; `templates/configs/scale_10.yaml` provides 10 nodes. P18 `max_nodes` is 10, so no resource downscope is justified from the files inspected.
- `scripts/assert_management_ops_coverage.py` currently knows P18 operation names, but it does not require the six exact P18 `(operation_name, node_count)` rows and does not verify moved slots, moved keys, slot ownership, post-move data path, or imbalance reduction.
- `schemas/artifact/slot_movement.schema.json` is present and is the schema wired in `codex/phase_manifest.json` for `reshard_slot_movements.jsonl`. `schemas/artifact/reshard_slot_movement.schema.json` is not present. The existing schema is permissive; P18-specific correctness must be enforced in assertions unless the worker intentionally adds a stronger schema and updates the manifest/lock through a harness-strengthening exception.
- `schemas/artifact/rebalance_summary.schema.json` exists, but only requires top-level imbalance before/after. Assertions must require per-row and per-primary detail to reject no-op rebalance.

No hard resource blocker is evident from the repository state. There is a real implementation blocker: P18 runtime dispatch and assertions are incomplete today.

## Minimal Implementation Path

1. Add P18 scenario support in `src/valkey_scale_lab/runtime/docker_runtime.py`:
   - allow `("P18_MANAGEMENT_RESHARD_REBALANCE", "management_reshard_rebalance")`;
   - allow expected node count `{6}` for the outer wrapper, matching the P17 pattern;
   - dispatch `write_p18_management_reshard_rebalance_artifacts(...)` after cluster creation.
2. Reuse the P17 sidecar structure:
   - create fresh isolated sidecar clusters per required row;
   - use `local_az_3x2.yaml` for 6-node rows and `scale_10.yaml` for 10-node rows;
   - use deterministic port bases outside P17's range, deterministic operation IDs, owned Docker labels, state files, and cleanup reports.
3. Add P18 row helpers alongside P17 helpers rather than refactoring P17 during this stage:
   - topology parser that maps primary node IDs to slot ranges and slot counts;
   - deterministic source/target primary selection from live `CLUSTER NODES`;
   - key generator that loops over candidate keys and uses `CLUSTER KEYSLOT` until a key maps to the selected slot;
   - slot movement primitive that records one `reshard_slot_movements.jsonl` row per moved range or per moved slot batch;
   - rebalance planner that moves slots from most-loaded primary to least-loaded primary until the declared imbalance metric is reduced.
4. Reuse `TelemetryRun`, `workload_metrics`, P17 workload-window shape, topology JSONL, command log JSONL, cleanup summaries, and aggregate workload impact helpers. P18 should improve aggregation to retain all canonical workload metrics, including p90, p999, connection errors, cluster-down, readonly, tryagain, unknown error, and sample count.

## Six-Row Evidence Plan

Each row should run on a fresh cluster so earlier movements cannot mask later failures.

- `reshard_slot_range`: select two primaries and move a deterministic explicit range, for example 8-32 slots wholly owned by the source primary. The row may start without seeded keys, but it must still verify that writes and reads to moved slots succeed after convergence.
- `reshard_with_keys`: select a deterministic slot range and seed at least one known key per moved slot, or a documented bounded subset if the range is larger. Verify every seeded key is readable after the move and at least one write per moved slot succeeds after convergence.
- `rebalance_after_imbalance`: first create a measurable imbalance by moving a deterministic batch from one primary to another. Record this as setup, not as the rebalance result. Then run the rebalance operation by moving slots from the most-loaded primary to the least-loaded primary until `max(primary_slot_count) - min(primary_slot_count)` is lower than before. The row passes only if the measured imbalance decreases and slot coverage/data path still pass.

For all six rows, operation results and matrix rows must include `operation_status=PASS`, `real_execution_verified=true`, non-MISSING timing, `cluster_state_before=ok`, `cluster_state_after=ok`, `slots_before=16384`, `slots_after=16384`, `errors_by_type`, and `workload_window_ref`.

## Safe Valkey Slot-Movement Strategy

Use direct Valkey cluster commands with command-log evidence. Avoid host networking changes and avoid `sudo`.

For each slot:

1. Discover source/target primary node IDs from live `CLUSTER NODES`, and target container IP/port from owned runtime state.
2. If keys are required, generate deterministic keys by probing `CLUSTER KEYSLOT <candidate>` until the candidate maps to the chosen slot, then `SET` the key before movement.
3. Count keys with `CLUSTER COUNTKEYSINSLOT <slot>` and enumerate with `CLUSTER GETKEYSINSLOT <slot> <count>`.
4. Put the slot into migration state:
   - on target: `CLUSTER SETSLOT <slot> IMPORTING <source_node_id>`;
   - on source: `CLUSTER SETSLOT <slot> MIGRATING <target_node_id>`.
5. If keys exist, run `MIGRATE <target_ip> 6379 "" 0 <timeout_ms> KEYS <key...>` from the source. Batch keys per slot with a bounded timeout. Record `keys_moved`; record `bytes_migrated` as `MISSING` with a reason unless measured.
6. Finalize ownership by broadcasting `CLUSTER SETSLOT <slot> NODE <target_node_id>` to all primaries, preferably all nodes, then wait for `CLUSTER INFO` state `ok`, `cluster_slots_assigned=16384`, `cluster_slots_ok=16384`, and no fail slots.
7. Verify ownership and data path:
   - `CLUSTER NODES`/slot parser shows target owns the moved slots;
   - seeded keys are readable after movement;
   - new writes to moved slots succeed after convergence;
   - source no longer owns the slot;
   - cluster-aware workload records MOVED/ASK/error counts during the event window.

This direct command path is safer than relying on `valkey-cli --cluster rebalance` for P18 because it makes slot count, key movement, ownership, and no-op risk observable in artifacts. The command log can still label grouped calls as `cluster_setslot_importing`, `cluster_setslot_migrating`, `cluster_migrate_keys`, `cluster_setslot_node`, and `rebalance_slot_move`.

## Required Artifacts

P18 must emit all manifest and stage artifacts:

- `phase_summary.json`
- `valkey_e2e_evidence.json`
- `cleanup_report.json`
- `events.jsonl`
- `metrics_timeseries.jsonl`
- `workload_windows.json`
- `quant_summary.json`
- `management_ops_matrix.json`
- `management_operation_results.jsonl`
- `management_workload_impact.json`
- `management_topology_snapshots.jsonl`
- `management_command_log.jsonl`
- `reshard_slot_movements.jsonl`
- `rebalance_summary.json`

`quant_summary.json` and `phase_summary.json` must cite the P18-specific slot movement and rebalance artifacts. Missing values, such as `bytes_migrated`, must be encoded as `MISSING` with a reason, never omitted or invented.

## Assertion Strengthening Needed

Strengthen `scripts/assert_management_ops_coverage.py` for P18:

- require the exact six required `(operation_name, node_count)` pairs in both `management_ops_matrix.json` and `management_operation_results.jsonl`;
- require every required P18 row to be `PASS` and `real_execution_verified=true`;
- reject `PASS_NOOP_VERIFIED`, `SKIPPED_WITH_REASON`, `MISSING`, or `UNSUPPORTED_WITH_REASON` for required P18 rows;
- require `slots_moved > 0`;
- require `slot_coverage_complete=true`, `slots_before=16384`, `slots_after=16384`, `cluster_state_before=ok`, and `cluster_state_after=ok`;
- for `reshard_with_keys`, require `keys_moved > 0`, `moved_keys_readable=true`, and `post_move_writable=true`;
- for `reshard_slot_range`, require explicit `slot_start`, `slot_end`, source and target node IDs, owner-before/source and owner-after/target proof, plus post-move write verification;
- for `rebalance_after_imbalance`, require `imbalance_before > imbalance_after`, per-primary slot counts before/after, and at least one rebalance slot movement.

Strengthen workload and quant assertions where practical:

- require P18 workload impact to include all canonical metrics from `06_QUANTIFICATION_SPEC.md`, not only the current subset in `assert_workload_impact.py`;
- require `reshard_slot_movements.jsonl` to validate against `slot_movement.schema.json` and include P18 extra fields inspected by assertions;
- require `rebalance_summary.json` status `PASS`, numeric imbalance before/after, and references to operation IDs and movement IDs;
- add unit tests that fail on missing 10-node rows, `slots_moved=0`, moved-key read failure, missing post-move write proof, and no-op rebalance.

If the worker chooses to introduce a stricter `reshard_slot_movement.schema.json`, treat it as a harness-strengthening change: document any harness exception, update `codex/phase_manifest.json`, refresh `codex/gate_lock.json`, and add tests. The minimal path is to keep the existing manifest schema and enforce P18 semantics in assertions.

## Risks

- Valkey slot migration command correctness is the main risk. The `IMPORTING`/`MIGRATING`/`MIGRATE`/`NODE` sequence must be ordered correctly and applied to the right nodes. A partial failure can leave slots in transitional state, so cleanup must tear down the whole owned sidecar cluster on error.
- `MIGRATE` requires the source container to reach the target container IP and port inside the owned Docker network. Use container IPs from runtime state, not host ports.
- Key generation must prove the selected key maps to the selected slot with `CLUSTER KEYSLOT`; do not assume a key string maps to the intended slot.
- Rebalance may become a no-op if the cluster starts balanced. The row must intentionally create a measured imbalance first, then prove reduction. A clean cluster plus `PASS_NOOP_VERIFIED` is not acceptable for P18.
- Slot ranges parsed from `CLUSTER NODES` can appear in different order from different nodes. Assertions should rely on normalized slot ownership and counts, not raw string order.
- Running six sidecar clusters serially can be slower than P17. Keep node counts capped at 6/10, keep slot batches small, and never downscope required rows unless a real resource preflight failure is recorded as blocked.
- Workload redirection counts may be zero after a clean fast move. That is acceptable if the counters are measured and present; do not invent MOVED/ASK counts.

## Review Checklist For PASS/FAIL

PASS only if all of these are true:

- P18 real gate result is PASS and proves live Valkey 9.1.x for the outer scenario.
- `management_operation_results.jsonl` and `management_ops_matrix.json` contain all six exact required rows, all `PASS`.
- Each required row has `real_execution_verified=true`, non-MISSING timing, clean before/after cluster state, full slot coverage, workload ref, and zero command errors.
- `reshard_slot_movements.jsonl` contains positive slot movement evidence tied to the P18 operation IDs.
- `reshard_with_keys` rows prove seeded moved-slot keys are readable after movement and moved-slot writes succeed after convergence.
- `rebalance_after_imbalance` rows prove numeric imbalance reduction on both 6-node and 10-node clusters.
- `management_command_log.jsonl` shows real Valkey slot commands and no host network/firewall/route mutation.
- `management_topology_snapshots.jsonl` includes before, during, and after snapshots with normalized slot ownership.
- `management_workload_impact.json` and `workload_windows.json` contain canonical windows for every row with measured QPS, latency, error, timeout, MOVED, and ASK fields.
- `cleanup_report.json` and every sidecar cleanup summary are PASS with `resources_remaining=[]`.
- `scripts/assert_management_ops_coverage.py`, `scripts/assert_workload_impact.py`, `scripts/assert_quant_artifacts.py`, and unit tests fail closed for missing rows or fake/no-op P18 evidence.

FAIL if any required row is skipped, no-op, lacks key/data-path verification where required, lacks 10-node evidence, reports `slots_moved=0`, leaves slot coverage incomplete, has cleanup leftovers, or relies on fabricated metrics.

## Recommended Implementation Sequence

1. Add P18 runtime allow-list, node-count policy, and dispatch.
2. Copy the P17 sidecar matrix skeleton into P18-specific helpers with fresh operation IDs, ports, state files, cleanup files, and artifact writers.
3. Implement topology normalization, primary selection, key generation by `CLUSTER KEYSLOT`, and the direct slot movement primitive.
4. Implement `reshard_slot_range` and `reshard_with_keys` for 6-node rows, then 10-node rows.
5. Implement imbalance creation plus deterministic rebalance for 6-node and 10-node rows.
6. Write all P18 artifacts, including slot movement and rebalance summaries, then run schema validation.
7. Strengthen assertion scripts and unit tests before trusting a PASS gate.
8. Run the full P18 gate, inspect artifacts manually, then request fresh-context review.
