# DESIGN_BRIEF - P31_MANAGEMENT_MATRIX_100_REAL

## Fresh read confirmation

Read the strict design prompt, the required base/goal-loop/strict control docs, `docs/codex/goal-loop-strict/stages/P31_MANAGEMENT_MATRIX_100_REAL.md`, `artifacts/goal_loop_strict/P31_MANAGEMENT_MATRIX_100_REAL/CONTEXT_RELOAD.md`, and `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md`.

## Stage objective

Run the complete strict management matrix on exactly 100 real Valkey 9.1.x nodes. P31 must not downshift to 50 nodes, use replayed P30 artifacts, skip any required management row, or pass when resource preflight/Docker cannot support the run.

## Current repository findings

- `codex/phase_manifest.json` already declares P31 as automatic, `max_nodes=100`, with required P31 artifacts and gates. Its real gate currently runs `scripts/valkey_e2e_gate.py --phase P31_MANAGEMENT_MATRIX_100_REAL --scenario strict_management_matrix_100 --config templates/configs/scale_100.yaml --min-nodes 100 --require-data-path`.
- P30 is implemented in `src/valkey_scale_lab/runtime/docker_runtime.py` as hard-coded `P30_STAGE`, `P30_SCENARIO`, `P30_SCALE=50`, and P30-specific artifact writers/messages/coverage IDs. Runtime admission currently includes only `(P30_STAGE, P30_SCENARIO)`.
- P30 artifacts prove the existing path works at 50 nodes: `valkey_e2e_evidence.json` has `nodes_requested=50`, `nodes_observed=50`, Valkey `9.1.0`, and data path PASS; `quant_summary.json` has 11 operation PASS rows, 154 events, 1452 metric rows, 66 workload windows; cleanup PASS.
- `scripts/assert_management_matrix_strict.py` is already scale-parameterized and should work for P31 if artifacts contain `100.management.*`, `node_count=100`, all 11 rows PASS, and real source refs.
- `scripts/assert_quant_completeness.py` currently special-cases only P29 and P30. P31 will need strict management validation generalized from P30 to `{P30: 50, P31: 100}`.
- `tests/integration/test_docker_runtime_contract.py` has an exact-50 P30 process-runtime admission test but no exact-100 P31 equivalent.
- `templates/configs/scale_100.yaml` defines 50 shards with one replica each, port base `7500`, cluster bus base `17500`, and default max nodes `100`.
- Locked harness files include at least `codex/phase_manifest.json`, `scripts/valkey_e2e_gate.py`, `scripts/assert_quant_completeness.py`, and `scripts/assert_management_matrix_strict.py` in `codex/gate_lock.json`; update the lock only if a locked harness file changes.

## Scope boundaries

Implement only P31. Do not mark complete, commit, push, edit gate results, edit phase state manually, or modify source for P32/P33+ except reusable scale-aware helpers required to avoid duplicating P30 logic.

## Implementation plan

1. Generalize the P30 management runtime in `src/valkey_scale_lab/runtime/docker_runtime.py` into scale-aware strict management helpers.
   - Add constants/config mapping for P31: `P31_MANAGEMENT_MATRIX_100_REAL`, `strict_management_matrix_100`, scale `100`, config `templates/configs/scale_100.yaml`, coverage prefix `100.management`.
   - Replace hard-coded `P30_SCALE`, `P30_STAGE`, `P30_SCENARIO`, exact-50 messages, `expected_nodes=49`, `observed_nodes_after_restore=50`, expected primary/replica counts `25/24/25`, operation IDs `p30-...-50`, and artifact names `runtime_timing_breakdown_strict_management_matrix_50.json` with values derived from the active strict management stage.
   - Keep the existing P30 behavior intact; P30 artifacts and tests must still validate.
   - Extend `create_scenario`, `_uses_docker_process_runtime`, `_scenario_node_count_allowed`, `_spec` cluster timeout handling, `_create_process_scenario`, process preflight, artifact writing, coverage ledger update, and scale-ladder skip logic to include P31.
   - Resource preflight must run against `templates/configs/scale_100.yaml`; if `can_run` is not true, write `artifacts/goal_loop_strict/P31_MANAGEMENT_MATRIX_100_REAL/BLOCKED.md` and fail rather than downshifting.

2. Preserve exact 100-node evidence semantics.
   - Emit `nodes_requested=100` and `nodes_observed=100` through `scripts/valkey_e2e_gate.py`.
   - Ensure `cluster_plan.json`, `run_state.json`, topology snapshots, management results, matrix rows, workload windows, quant summary, and phase summary all use P31 IDs and `node_count=100`.
   - Ensure removal rows use derived expectations: after temporary removal `99` observed nodes, after restore `100`, expected primaries `50`, and expected replicas `49` or `50` depending on the row path.
   - Ensure rolling restart produces 100 restart rows and 100 health gates.

3. Update strict quant validation for P31.
   - In `scripts/assert_quant_completeness.py`, generalize P30 management assertions to accept P31 with `scale=100`, `stage_id=P31_MANAGEMENT_MATRIX_100_REAL`, coverage prefix `100.management.`, expected operation/pass count `11`, exact evidence `nodes_observed=100`, and P31 timing artifact name.
   - Keep forbidden value checks, workload-window checks, coverage-ledger checks, and cleanup checks fail-closed.

4. Add the process-runtime admission test.
   - In `tests/integration/test_docker_runtime_contract.py`, add a P31 test asserting `strict_management_matrix_100` admits only exactly `100`, rejects `99`, `50`, and `101`, and uses Docker process runtime.
   - Add/adjust any focused tests needed for the strict quant validator if an existing unit test surface exists.

5. Adjust the P31 e2e probe timeout only if needed.
   - P30 manifest uses `--probe-timeout 10`; P31 currently omits it. If P31 data-path probes are flaky or too slow at exact 100, update only the P31 manifest gate command to include a bounded timeout such as `--probe-timeout 10` or a documented slightly larger value.
   - If `codex/phase_manifest.json` changes, treat it as a harness-control change and update `codex/gate_lock.json` transparently.

## Harness plan

Expected gates:

```bash
python3 scripts/codex_gate.py precheck --phase P31_MANAGEMENT_MATRIX_100_REAL
python3 scripts/safety_scan.py
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
python3 scripts/assert_strict_stage_contract.py --phase P31_MANAGEMENT_MATRIX_100_REAL
python3 scripts/assert_no_bypass.py --phase P31_MANAGEMENT_MATRIX_100_REAL
python3 scripts/valkey_e2e_gate.py --phase P31_MANAGEMENT_MATRIX_100_REAL --scenario strict_management_matrix_100 --config templates/configs/scale_100.yaml --out artifacts/phases/P31_MANAGEMENT_MATRIX_100_REAL/valkey_e2e_evidence.json --min-nodes 100 --require-data-path
python3 scripts/assert_exact_scale_real_evidence.py --phase P31_MANAGEMENT_MATRIX_100_REAL --nodes 100
python3 scripts/assert_management_matrix_strict.py --phase P31_MANAGEMENT_MATRIX_100_REAL --scale 100 --require-all-rows
python3 scripts/assert_quant_completeness.py --phase P31_MANAGEMENT_MATRIX_100_REAL --category management --scale 100
python3 scripts/assert_coverage_registry.py --phase P31_MANAGEMENT_MATRIX_100_REAL --scale 100 --category management
python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P31_MANAGEMENT_MATRIX_100_REAL/cleanup_report.json
python3 scripts/codex_gate.py run --phase P31_MANAGEMENT_MATRIX_100_REAL
```

If locked harness files change, update `codex/gate_lock.json` using the project’s existing lock-refresh path and cite the before/after reason in the worker summary and review.

## Schema and artifact plan

No new schemas appear required. P31 must produce the exact artifact list from the stage doc under `artifacts/phases/P31_MANAGEMENT_MATRIX_100_REAL/`, including `resource_preflight.json`, `valkey_e2e_evidence.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `coverage_ledger.json`, `management_ops_matrix.json`, `management_operation_results.jsonl`, `management_topology_snapshots.jsonl`, `management_command_log.jsonl`, and `management_workload_impact.json`.

## Coverage IDs targeted

`100.management.create_cluster`, `100.management.meet_nodes`, `100.management.add_replica`, `100.management.remove_replica`, `100.management.remove_primary_drained_or_safe_replaced`, `100.management.remove_failed_node`, `100.management.reshard_slot_range`, `100.management.reshard_with_keys`, `100.management.rebalance_after_imbalance`, `100.management.rolling_restart_replica_first`, `100.management.rolling_restart_primary_safe`.

## Safety constraints

Use only owned Docker containers/networks/processes and deterministic cleanup labels. Do not use host firewall/routing/interface changes, `sudo` network mutation, unrelated process kills, fake Valkey, replayed P30 outputs, or real execution above 100 for this stage.

## Blocked conditions

Block P31 if Docker is unavailable, resource preflight returns `can_run=false`, exact 100 nodes cannot be started/probed, any required management row fails or is skipped, any required metric is null/NaN/omitted, Valkey version is not `9.1.x`, data-path proof fails, coverage registry rows do not update to PASS, or cleanup does not pass.

## Risks

- P30 helper names and user-facing messages are deeply P30/exact-50-specific; incomplete generalization could produce mixed P30/P31 coverage IDs or artifact refs.
- The 100-node rolling restart path may need longer convergence/probe timeouts than P30; any timeout increase must be bounded and recorded.
- Coverage registry update must preserve the 50 PASS rows from P30 while updating only the 100 management rows.
- Resource preflight and actual host capacity may diverge; runtime must fail closed and clean up.

## 待验证

- Docker availability and host resources for exactly 100 process-runtime Valkey nodes.
- Whether P31 needs the same `--probe-timeout 10` as P30 or a larger bounded data-path timeout.
- Whether P30 removal/restore and rolling restart timings remain sufficient at 100 nodes without weakening health gates.
- Whether `codex/gate_lock.json` must change after the worker edits harness files.
