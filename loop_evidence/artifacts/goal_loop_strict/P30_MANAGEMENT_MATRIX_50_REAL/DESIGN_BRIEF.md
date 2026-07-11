# DESIGN_BRIEF - P30_MANAGEMENT_MATRIX_50_REAL

## Stage Objective

Execute and validate the full strict management operation matrix on exactly 50 real Valkey 9.1.x nodes, with resource preflight, exact-scale proof, per-row management telemetry, workload impact windows, coverage ledger updates for only `50.management.*`, cleanup proof, gates, and blocked-stage handling. No downshift is allowed.

## Current Repo Facts

- `docs/codex/goal-loop-strict/stages/P30_MANAGEMENT_MATRIX_50_REAL.md` requires exactly 50 real nodes, all 11 management rows as `PASS`, `resource_preflight.json`, `cluster_plan.json`, `run_state.json`, strict telemetry JSON/JSONL artifacts, management matrix artifacts, coverage ledger, and cleanup.
- `artifacts/coverage/strict_scenario_plan.json` defines scenario `management_matrix_50_real` with config `templates/configs/scale_50.yaml`, operation sequence of all 11 rows, and coverage IDs `50.management.*`.
- `templates/configs/scale_50.yaml` defines 25 shards with 1 replica each, Valkey image `valkey/valkey:9.1.0`, ports `7400-7449` and `17400-17449`, and workload enabled.
- `src/valkey_scale_lab/runtime/docker_runtime.py` currently implements P17/P18/P19 real management primitives for remove-node, reshard/rebalance, and rolling restart, but these are small sidecar row runs and do not satisfy exact 50-node P30 evidence.
- `src/valkey_scale_lab/runtime/docker_runtime.py` does not currently list `P30_MANAGEMENT_MATRIX_50_REAL/strict_management_matrix_50` in `create_scenario`, `_scenario_node_count_allowed`, or `_uses_docker_process_runtime`; this must be added for the manifest gate command to work.
- `src/valkey_scale_lab/resource.py` maps 50 nodes to older `P13_SCALE_LADDER_50_100`; P30 needs a stage-aware preflight artifact whose `phase_id` is `P30_MANAGEMENT_MATRIX_50_REAL` and whose fields satisfy the strict preflight contract.
- `scripts/valkey_e2e_gate.py` writes `state_<scenario>.json` and `valkey_e2e_evidence.json`; the P30 manifest also requires `run_state.json`. The wrapper or runtime should copy/write the same observed state to `run_state.json`.
- `scripts/assert_exact_scale_real_evidence.py` expects `nodes_requested` or `min_nodes_requested` to equal 50. Current `scripts/valkey_e2e_gate.py` evidence includes `nodes_observed` but not clearly `nodes_requested`; this is a likely P30 gate blocker unless strengthened.
- `scripts/assert_management_matrix_strict.py` currently checks required row names, exact row `node_count`, `operation_status=PASS`, and `real_execution_verified=true`; it does not yet enforce all field-level management spec requirements. Strengthening it is in-scope if it preserves/fails-closed.
- `schemas/artifact/management_operation_result.schema.json` and `schemas/artifact/management_ops_matrix.schema.json` are permissive enough for extra strict fields, so P30 can add required operation fields without a schema-breaking migration.

## Exact Implementation Plan

1. Add a P30 scenario path:
   - Register `(P30_MANAGEMENT_MATRIX_50_REAL, strict_management_matrix_50)` in `create_scenario`.
   - Permit exactly 50 nodes in `_scenario_node_count_allowed`.
   - Use the existing docker-process runtime for 50-node efficiency by including P30 in `_uses_docker_process_runtime`.
   - Reuse `_configure_process_cluster` / large-cluster helpers for initial create/meet/add-replica proof where possible.

2. Add stage-aware preflight and planning:
   - Produce `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/resource_preflight.json` before runtime starts.
   - Include host OS/arch, Docker availability/version, memory/disk/CPU, runtime limits, port ranges, per-node memory/disk/workload/metrics estimates, node distribution, `can_run`, and `phase_id=P30_MANAGEMENT_MATRIX_50_REAL`.
   - If `can_run=false`, write `artifacts/goal_loop_strict/P30_MANAGEMENT_MATRIX_50_REAL/BLOCKED.md` and fail the stage; do not fabricate runtime artifacts.
   - Produce `cluster_plan.json` with exact 50-node plan and P30 provenance. If reusing planner output, rewrite only stage identity/provenance fields needed for P30.

3. Execute the exact 50-node management matrix:
   - Start one real 50-node cluster from `templates/configs/scale_50.yaml`, probe live Valkey, and use operation IDs tied to coverage IDs, e.g. `p30-create-cluster-50`.
   - Required rows:
     `create_cluster`, `meet_nodes`, `add_replica`, `remove_replica`, `remove_primary_drained_or_safe_replaced`, `remove_failed_node`, `reshard_slot_range`, `reshard_with_keys`, `rebalance_after_imbalance`, `rolling_restart_replica_first`, `rolling_restart_primary_safe`.
   - For each row, record operation result fields from `08_MANAGEMENT_OPERATION_MATRIX_SPEC.md`: coverage ID, operation identity, scale/node count, status/reason, wall and monotonic timing, prepare/command/convergence/cleanup timings, before/after cluster state, known nodes, slot assignment/OK, slot balance, slots/keys moved, `bytes_migrated` as `MISSING` with reason when not available, workload window ref, errors by type, topology refs, command log refs, and source evidence refs.
   - Do not mark a row `SKIPPED_WITH_REASON`; if any row cannot run or verify, the stage fails or blocks.

4. Row semantics:
   - `create_cluster`, `meet_nodes`, `add_replica`: derive proof from the real 50-node cluster setup operations and snapshots; record command log entries and timing from runtime setup.
   - `remove_replica`: choose a deterministic replica, prove role before, stop/remove/forget through owned controls, verify absent from `CLUSTER NODES`, slot coverage complete, workload read/write remains valid, and cleanup of removed runtime resources.
   - `remove_primary_drained_or_safe_replaced`: choose a deterministic primary, move/drain slots or trigger a safe replacement path before removal, verify no orphaned slots, convergence, and workload impact.
   - `remove_failed_node`: apply failure through owned Docker/process controls only, verify target failure visible, safely forget/remove metadata, clear or intentionally remove target, and verify cleanup.
   - `reshard_slot_range`: choose deterministic source/target primaries and explicit slot range, move >0 slots, record before/after owners and MOVED/ASK/error telemetry.
   - `reshard_with_keys`: seed keys in selected slots, move slots, verify reads and writes after convergence, record key movement evidence.
   - `rebalance_after_imbalance`: create a measurable imbalance, record slot distribution, rebalance to reduce imbalance, verify data path.
   - `rolling_restart_replica_first`: deterministic replica-before-primary order, one node at a time, health gate after each restart, workload impact.
   - `rolling_restart_primary_safe`: safe primary path with promotion/unavailability/recovery telemetry if failover occurs, health gate and target-state verification.

5. Telemetry and workload impact:
   - Use `TelemetryRun`, `CANONICAL_WINDOWS`, and workload helpers from P29/P17-P19 as the pattern, but set `stage_id`, `coverage_id`, `scale`, and `node_count` per P30 row.
   - Emit strict `events.jsonl` and `metrics_timeseries.jsonl` rows with no `null`, `NaN`, `undefined`, or omitted required fields.
   - For every operation, provide `baseline`, `pre_event`, `event`, `recovery`, `post_recovery`, and `all_run` windows with nonzero observed samples and the required latency/error taxonomy.
   - Aggregate row windows into `workload_windows.json` and `management_workload_impact.json` while preserving per-operation refs.

6. Coverage ledger update:
   - Start from `artifacts/coverage/strict_coverage_registry.json`.
   - Update only the 11 `50.management.*` rows to `PASS`.
   - Fill `source_artifacts`, `validation_artifacts`, `metric_refs`, `cleanup_ref`, and `status_reason`.
   - Keep every non-`50.management.*` row unchanged and still `PENDING`.
   - `review_ref` and `commit_sha` are 待验证 because review and commit happen after worker/gates; if the current schema/gate requires these for PASS before review, the worker must use the eventual review path placeholder only if allowed by harness policy, or otherwise strengthen the post-review update flow.

7. Exact-scale proof and cleanup:
   - Ensure `valkey_e2e_evidence.json` includes `nodes_requested=50`, `nodes_observed=50`, `real_valkey=true`, `probe_result=PASS`, `valkey_version_prefix_required=9.1.`, all observed versions starting `9.1.`, role counts, data path proof, and cleanup status.
   - Write `run_state.json` with a strict generic report wrapper or copied runtime state that includes `schema_version`, `artifact_type`, `phase_id`, `status`, `run_id`, runtime ownership labels, nodehost/process inventory, and node count.
   - Cleanup must terminate owned Valkey processes, remove owned nodehost containers/networks, scan residual owned resources, and produce `cleanup_report.json` with `status=PASS` and empty `resources_remaining`.

## Exact Files Likely To Change

- `src/valkey_scale_lab/runtime/docker_runtime.py`
- `src/valkey_scale_lab/resource.py`
- `src/valkey_scale_lab/planner/plan.py` or a P30-specific wrapper if stage-aware plan identity is added outside planner core
- `scripts/valkey_e2e_gate.py`
- `scripts/assert_management_matrix_strict.py`
- `scripts/assert_quant_completeness.py` if P30-specific strict telemetry checks are added
- `scripts/assert_workload_impact.py` if per-operation management workload coverage must be enforced
- `tests/unit/test_goal_loop_assertions.py`
- `tests/integration/test_docker_runtime_contract.py`
- Additional focused unit/integration tests for P30 scenario registration, preflight identity, exact-scale evidence fields, management row validation, and coverage ledger immutability.

Harness-control edits must strengthen fail-closed behavior only; if a harness defect is found, write `artifacts/harness_exception/P30_MANAGEMENT_MATRIX_50_REAL.md` before the smallest preserving fix.

## New Or Updated Schemas

- No schema replacement is required based on current permissive schemas.
- 待验证: whether `resource_preflight.schema.json`, `strict_generic_report.schema.json`, and management schemas are intentionally permissive enough for all P30 strict fields. If not, update schemas only to add stricter required fields matching the strict docs.

## New Or Updated Gates

- Required existing manifest gates:
  - `python3 scripts/valkey_e2e_gate.py --phase P30_MANAGEMENT_MATRIX_50_REAL --scenario strict_management_matrix_50 --config templates/configs/scale_50.yaml --out artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/valkey_e2e_evidence.json --min-nodes 50 --require-data-path`
  - `python3 scripts/assert_exact_scale_real_evidence.py --phase P30_MANAGEMENT_MATRIX_50_REAL --nodes 50`
  - `python3 scripts/assert_management_matrix_strict.py --phase P30_MANAGEMENT_MATRIX_50_REAL --scale 50 --require-all-rows`
  - `python3 scripts/assert_quant_completeness.py --phase P30_MANAGEMENT_MATRIX_50_REAL --category management --scale 50`
  - `python3 scripts/assert_coverage_registry.py --phase P30_MANAGEMENT_MATRIX_50_REAL --scale 50 --category management`
  - `python3 scripts/assert_no_bypass.py --phase P30_MANAGEMENT_MATRIX_50_REAL`
  - `python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/cleanup_report.json`
- Recommended strengthening:
  - `assert_management_matrix_strict.py` should enforce operation-specific requirements, exact `coverage_id`, exact field presence, row source refs, workload refs, topology refs, command refs, positive slot/key/restart movement where applicable, and no `SKIPPED_WITH_REASON`.
  - `assert_quant_completeness.py` should add P30 checks equivalent to P29 strict telemetry checks but allowing `coverage_id` values in `50.management.*`.
  - `assert_workload_impact.py` should verify all 11 operations have canonical windows and nonzero samples.

## Artifact List

Required P30 phase artifacts:

- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/phase_summary.json`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/valkey_e2e_evidence.json`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/resource_preflight.json`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/cluster_plan.json`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/run_state.json`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/cleanup_report.json`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/events.jsonl`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/metrics_timeseries.jsonl`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/workload_windows.json`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/quant_summary.json`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/coverage_ledger.json`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/management_ops_matrix.json`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/management_operation_results.jsonl`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/management_topology_snapshots.jsonl`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/management_command_log.jsonl`
- `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/management_workload_impact.json`

Useful extra source artifacts:

- `reshard_slot_movements.jsonl`
- `rebalance_summary.json`
- `rolling_restart_plan.json`
- `rolling_restart_results.jsonl`
- per-row cleanup/state/source evidence refs if row-level runtime isolation is used.

## Coverage IDs Targeted

- `50.management.create_cluster`
- `50.management.meet_nodes`
- `50.management.add_replica`
- `50.management.remove_replica`
- `50.management.remove_primary_drained_or_safe_replaced`
- `50.management.remove_failed_node`
- `50.management.reshard_slot_range`
- `50.management.reshard_with_keys`
- `50.management.rebalance_after_imbalance`
- `50.management.rolling_restart_replica_first`
- `50.management.rolling_restart_primary_safe`

No 100-node, 200-node, fault, lifecycle, full-flow, or >200 dry-run rows should be updated in P30.

## Commands To Run

Development checks:

```bash
PYTHONPATH=src python3 -m pytest -q tests/unit tests/integration
python3 -m compileall -q scripts src
python3 scripts/safety_scan.py
python3 scripts/assert_strict_stage_contract.py --phase P30_MANAGEMENT_MATRIX_50_REAL
```

P30 gates:

```bash
python3 scripts/codex_gate.py precheck --phase P30_MANAGEMENT_MATRIX_50_REAL
python3 scripts/codex_gate.py run --phase P30_MANAGEMENT_MATRIX_50_REAL
python3 scripts/assert_exact_scale_real_evidence.py --phase P30_MANAGEMENT_MATRIX_50_REAL --nodes 50
python3 scripts/assert_management_matrix_strict.py --phase P30_MANAGEMENT_MATRIX_50_REAL --scale 50 --require-all-rows
python3 scripts/assert_quant_completeness.py --phase P30_MANAGEMENT_MATRIX_50_REAL --category management --scale 50
python3 scripts/assert_coverage_registry.py --phase P30_MANAGEMENT_MATRIX_50_REAL --scale 50 --category management
python3 scripts/assert_no_bypass.py --phase P30_MANAGEMENT_MATRIX_50_REAL
python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/cleanup_report.json
```

After review passes:

```bash
python3 scripts/codex_gate.py postcheck --phase P30_MANAGEMENT_MATRIX_50_REAL
python3 scripts/codex_gate.py mark-complete --phase P30_MANAGEMENT_MATRIX_50_REAL
git status --short
git add <intentional P30 files>
git commit -m "P30_MANAGEMENT_MATRIX_50_REAL: prove 50-node management matrix"
git push
```

## Safety Constraints

- Never downshift below 50 nodes for P30.
- Never run above 50 nodes for P30.
- Do not mutate host firewall, routing, PF, nftables, iptables, physical interfaces, or global OS network services.
- Do not use `sudo` for network/firewall/interface paths.
- Fault-like row behavior for `remove_failed_node` must use owned Docker/process controls only.
- All containers, nodehosts, networks, ports, state files, and run IDs must be deterministic and ownership-labeled.
- Cleanup must be deterministic and idempotent.
- Missing values must be `MISSING` or an allowed status with a non-empty reason, never `null`, `0` placeholders, `NaN`, `undefined`, empty strings, or omitted required fields.

## Blocked Conditions

- Resource preflight returns `can_run=false`.
- Docker is unavailable or cannot run the owned Valkey image.
- Ports `7400-7449` or `17400-17449` are unavailable.
- Exact node count is not 50 in requested, planned, state, evidence, and probes.
- Any Valkey version does not start with `9.1.`.
- Any required management row is missing, skipped, synthetic, replayed, non-PASS, or lacks source artifacts.
- Any row cannot produce workload impact, topology, command log, convergence, or cleanup evidence.
- Any required metric is null/NaN/omitted or missing without reason.
- Coverage ledger changes rows outside `50.management.*`.
- Cleanup leaves owned resources behind or fails.

## Review Focus Points

- Does `valkey_e2e_evidence.json` independently prove exactly 50 live Valkey 9.1.x nodes and data path success?
- Are all 11 management rows real operations at scale 50, not inherited from P17-P19 small sidecars?
- Do operation results contain all required strict management fields, with `MISSING` only where justified?
- Do workload artifacts cover every row and canonical window with observed samples?
- Does the coverage ledger update only `50.management.*` rows and keep all other rows unchanged?
- Do strengthened gates fail closed against generated-only artifacts, skipped rows, fake evidence, wrong scale, and cleanup failure?
- Does cleanup prove no owned runtime resources remain?
- 待验证: whether a single long-lived 50-node cluster can survive all destructive rows in one run, or whether row-level exact-50 fresh clusters are required for isolation. Either path must still prove every row at exact 50 and produce deterministic cleanup.
