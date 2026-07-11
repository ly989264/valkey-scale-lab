# M1-S04 Design Brief

stage_id: M1-S04
stage_title: 管理操作矩阵增强
designer: design-subagent
created_at: 2026-07-08
git_sha_before: bf111fe6b916ee21d92df1a44c310c54f8bf3fd1

## 目标理解

M1-S04 must turn management operations from a coarse result table into an explainable operation process. The required matrix is not a report-only feature: every management operation row must be backed by schema-validated operation results, before/after topology snapshots, topology/slot/role diffs, command-log trace refs from M1-S03, workload-impact refs, cleanup refs, and analysis/report views. Missing values are allowed only as structured `MISSING` or `SKIPPED_WITH_REASON` objects with a reason and impact; fake real PASS and empty management artifacts must fail gates.

Required operations for a single shared schema:

- `create_cluster`
- `meet_nodes`
- `add_replica`
- `remove_replica`
- `remove_primary_drained_or_safe_replaced`
- `remove_failed_node`
- `reshard_slot_range`
- `reshard_with_keys`
- `rebalance_after_imbalance`
- `rolling_restart_replica_first`
- `rolling_restart_primary_safe`

The same artifact schema must serve small clusters, 30, 50, 100, 200, 200+ dry-run planning, and blocked local runs. Long soak remains out of scope and must not be introduced.

## Current Code Paths

Relevant implementation already exists but is split across legacy phase-specific paths and needs consolidation for milestone1:

- [src/valkey_scale_lab/runtime/docker_runtime.py](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/src/valkey_scale_lab/runtime/docker_runtime.py)
  - `P30_REQUIRED_ROWS`, `P30_EXECUTION_ROWS`, `STRICT_MANAGEMENT_PROFILES`
  - `write_management_ops_report`
  - `write_p17_management_remove_node_artifacts`
  - `write_p18_management_reshard_rebalance_artifacts`
  - `write_p19_management_rolling_restart_artifacts`
  - `write_p30_management_matrix_artifacts`
  - `_p30_run_operation_with_workload`
  - `_p30_execute_operation`
  - `_p30_strict_operation_row`
  - `_p17_topology_snapshot`, `_p17_cluster_health`, `_p18_execute_operation`, `_p30_execute_process_rolling_restart`
- [src/valkey_scale_lab/runtime/command_recorder.py](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/src/valkey_scale_lab/runtime/command_recorder.py)
  - `CommandRecorder`, `current_command_recorder`, `record_result`, `build_command_audit_summary`
- [src/valkey_scale_lab/cli.py](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/src/valkey_scale_lab/cli.py)
  - scenario/cleanup command-recorder lifecycle and `command_log.jsonl` / `command_audit_summary.json` refs
- [src/valkey_scale_lab/analysis/summary.py](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/src/valkey_scale_lab/analysis/summary.py)
  - current optional readers for `setup_telemetry.json`, `command_log.jsonl`, and `command_audit_summary.json`
- [src/valkey_scale_lab/report/render.py](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/src/valkey_scale_lab/report/render.py)
  - current Chinese sections for setup and command audit, plus CSV/SVG exports
- [schemas/artifact/management_ops_matrix.schema.json](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/schemas/artifact/management_ops_matrix.schema.json)
  - currently loose; requires only basic operation fields
- [schemas/artifact/management_operation_result.schema.json](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/schemas/artifact/management_operation_result.schema.json)
  - currently lacks many M1-S04 required fields as required properties
- [schemas/artifact/topology_snapshot.schema.json](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/schemas/artifact/topology_snapshot.schema.json)
  - useful base for snapshots but no management diff schema exists yet
- [schemas/artifact/command_log_entry.schema.json](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/schemas/artifact/command_log_entry.schema.json)
  - M1-S03 command row contract to reference from management rows
- [scripts/assert_management_matrix_strict.py](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/scripts/assert_management_matrix_strict.py)
  - already checks some P30-style strict management fields, but it does not yet enforce the full M1-S04 topology diff, command-count, cleanup-ref, and analysis/report propagation contract
- [scripts/assert_management_ops_coverage.py](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/scripts/assert_management_ops_coverage.py)
  - legacy P17/P18/P19 coverage gate for old artifact layout
- Existing fixtures/tests likely to extend:
  - [tests/unit/test_goal_loop_assertions.py](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/tests/unit/test_goal_loop_assertions.py)
  - [tests/integration/test_docker_runtime_contract.py](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/tests/integration/test_docker_runtime_contract.py)
  - [tests/analysis/test_analysis_summary.py](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/tests/analysis/test_analysis_summary.py)
  - [tests/report/test_report_rendering.py](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/tests/report/test_report_rendering.py)

## Design

Add a reusable management artifact layer rather than continuing to widen P17/P18/P19/P30 special cases. The runtime may still call existing real-operation helpers, but it should normalize every row through one shared writer contract.

Proposed new module:

- `src/valkey_scale_lab/management_matrix.py`

Responsibilities:

- Define `REQUIRED_MANAGEMENT_OPERATIONS`.
- Define required common fields and operation-specific extra fields.
- Build management topology snapshots from live/runtime node dictionaries.
- Build `topology_diff` and separate `slot_diff` / `role_diff` objects.
- Build operation rows with command-log refs, workload refs, cleanup refs, snapshot refs, diff refs, and missing-value helpers.
- Validate that PASS rows have command evidence and non-empty before/after snapshots.
- Write:
  - `management_ops_matrix.json`
  - `management_operation_results.jsonl`
  - `management_topology_snapshots.jsonl`
  - `management_topology_diffs.jsonl`
  - `management_workload_impact.json`
  - optional sidecars already used for specific ops: `reshard_slot_movements.jsonl`, `rebalance_summary.json`, `rolling_restart_plan.json`, `rolling_restart_results.jsonl`

The Docker runtime should call this layer from strict management paths and from small/smoke management fixture paths. Legacy P17/P18/P19/P30 writers can be left in place for backward compatibility, but M1-S04 gates should validate the new shared artifact shape from the current run directory.

## Required Fields

Every operation result row should require:

- `schema_version`
- `artifact_type`: `management_operation_result`
- `phase_id`
- `run_id`
- `scenario`
- `coverage_id`
- `operation_name`
- `operation_id`
- `node_count`
- `scale`
- `operation_status`
- `status_reason`
- `started_at_unix_ms`
- `ended_at_unix_ms`
- `operation_duration_ms`
- `wall_ms` as legacy alias if needed
- `prepare_ms`
- `command_ms`
- `convergence_ms`
- `cleanup_ms`
- `before_topology_snapshot`
- `after_topology_snapshot`
- `before_topology_snapshot_ref`
- `after_topology_snapshot_ref`
- `topology_diff`
- `topology_diff_ref`
- `slot_diff`
- `role_diff`
- `cluster_state_before`
- `cluster_state_after`
- `known_nodes_before`
- `known_nodes_after`
- `fail_pfail_handshake_before`
- `fail_pfail_handshake_after`
- `command_count`
- `retry_count`
- `error_count`
- `command_log_refs`
- `workload_impact_ref`
- `cleanup_ref`
- `source_evidence_refs`
- `missing_fields`

Compatibility aliases should be retained where existing gates/tests expect them:

- `cluster_known_nodes_before/after`
- `cluster_slots_assigned_before/after`
- `cluster_slots_ok_before/after`
- `slots_before/after`
- `workload_window_ref`
- `command_log_ref`
- `topology_before_ref`
- `topology_after_ref`
- `topology_ref`
- `duration_ms`

Reshard/rebalance rows additionally require:

- `slots_moved`
- `keys_moved`
- `bytes_migrated` as numeric or structured `MISSING`
- `slot_balance_before`
- `slot_balance_after`
- `imbalance_delta`
- for compatibility: `imbalance_before`, `imbalance_after`, `movement_ids`, `source_node_id`, `target_node_id`, `slot_coverage_complete`, `post_move_writable`

Rolling restart rows additionally require:

- `per_node_stop_ms`
- `per_node_restart_ms`
- `per_node_rejoin_ms`
- `per_node_unavailable_ms`
- `cluster_impact_ms`
- `restart_count`
- `health_gate_count`
- `max_concurrent_restarts`
- refs to `rolling_restart_plan.json` and `rolling_restart_results.jsonl`

## Schema Propagation Plan

Modify:

- `schemas/artifact/management_operation_result.schema.json`
  - Make `artifact_type`, `run_id`, `scenario`, snapshot refs, topology diff, slot diff, role diff, command counts, workload/cleanup refs, and operation-specific blocks explicit.
  - Use `oneOf`/object variants for numeric-or-missing fields such as `bytes_migrated`.
  - Require structured reason objects for missing/skipped fields; reject `null`, empty string, `N/A`, `NaN`, `Infinity`.
- `schemas/artifact/management_ops_matrix.schema.json`
  - Require all required operation names through `contains` checks or gate-level enforcement.
  - Require matrix rows to carry operation refs, status, command/log/workload/topology refs, and `coverage_id`.
- Add `schemas/artifact/management_topology_diff.schema.json`.
  - Fields: `schema_version`, `artifact_type`, `phase_id`, `run_id`, `operation_id`, `before_snapshot_ref`, `after_snapshot_ref`, `slot_diff`, `role_diff`, `known_nodes_delta`, `fail_pfail_handshake_delta`, `changed_nodes`, `moved_slots`, `status`.
- Optionally strengthen `schemas/artifact/topology_snapshot.schema.json`.
  - For management snapshots, include `operation_id`, `label`, `cluster_state`, `known_nodes`, `fail_count`, `pfail_count`, `handshake_count`, `role_counts`, `slot_ranges` while preserving existing fault snapshot compatibility.
- Ensure schema validation covers JSONL files:
  - `management_operation_results.jsonl`
  - `management_topology_snapshots.jsonl`
  - `management_topology_diffs.jsonl`
  - `command_log.jsonl` or copied/linked `management_command_log.jsonl`

## Writer Path Plan

Modify:

- `src/valkey_scale_lab/runtime/docker_runtime.py`
  - In `write_p30_management_matrix_artifacts`, replace hand-built result/snapshot/diff fields with calls to the shared management writer.
  - In `_p30_execute_operation`, populate operation-specific fields and return raw timing/evidence; let the shared writer normalize field names and missing reasons.
  - In `_p30_run_operation_with_workload`, preserve current workload windows but add a stable `workload_impact_ref` pointing to `management_workload_impact.json#<operation_id>`.
  - When command rows are generated manually as `management_command_log.jsonl`, also make refs compatible with M1-S03 `command_log.jsonl` semantics. Best option: write management commands through `CommandRecorder.record_result` when a recorder exists, and include operation-specific refs like `command_log.jsonl#cmd-000123`. If strict P30 still uses synthetic management rows, the gate must treat them as fake fixture only unless generated from real commands.
  - Add `cleanup_ref` to every operation result and matrix row, usually `cleanup_report.json`, with structured skipped reason before cleanup has run if necessary.
- `src/valkey_scale_lab/cli.py`
  - No CLI command contract change required. Ensure `gate scenario` state/runtime refs include `management_ops_matrix_ref`, `management_operation_results_ref`, `management_topology_snapshots_ref`, and `management_topology_diffs_ref` when management artifacts are emitted.
- New `src/valkey_scale_lab/management_matrix.py`
  - `missing(field, reason, impact)`
  - `build_topology_snapshot(...)`
  - `diff_topology(before, after)`
  - `build_management_operation_result(...)`
  - `write_management_matrix_artifacts(...)`
  - `load_management_artifacts(...)` for analysis/gates

## Reader / Analyzer Plan

Modify [src/valkey_scale_lab/analysis/summary.py](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/src/valkey_scale_lab/analysis/summary.py):

- Load optional:
  - `management_ops_matrix.json`
  - `management_operation_results.jsonl`
  - `management_topology_diffs.jsonl`
  - `management_workload_impact.json`
- Add `management_ops` object to `analysis_summary.json`:
  - `status`
  - `operation_count`
  - `required_operations_observed`
  - `missing_required_operations`
  - `duration_ranking_topN`
  - `slow_operations_topN`
  - `error_operations`
  - `retry_operations`
  - `command_traceability`
  - `topology_diff_summary`
  - `reshard_rebalance_summary`
  - `rolling_restart_summary`
  - `workload_impact_refs`
  - `cleanup_refs`
- Add management missing/skipped fields into top-level `missing_metrics` with source `management_operation_results`.
- Keep legacy artifact-dir input behavior: if management artifacts are missing, analysis should emit `SKIPPED_WITH_REASON`, not fail unrelated stages.

Modify `schemas/artifact/analysis_summary.schema.json` if it constrains top-level fields; add optional `management_ops` object.

## Chinese Report Rendering Plan

Modify [src/valkey_scale_lab/report/render.py](/Users/allgood/centos_ex/projects/VibeCoding/valkey_scale_lab/src/valkey_scale_lab/report/render.py):

- Exports:
  - `management_ops_matrix.csv`
  - `management_operation_durations.csv`
  - `management_topology_diffs.csv`
  - `management_rolling_restart.csv`
  - `management_reshard_rebalance.csv`
- SVG assets:
  - `management_operation_duration.svg`
  - `management_topology_diff.svg` or compact bar/table SVG for changed nodes/slots/roles
- Markdown/HTML Chinese sections:
  - `管理操作矩阵`
  - `管理操作耗时排序`
  - `管理操作 topology diff 摘要`
  - `reshard / rebalance 摘要`
  - `rolling restart 摘要`
  - `管理操作 workload impact`
  - `管理操作 cleanup 追踪`
- Add `management_report_inputs` to `report_index.json` with source artifact refs and hashes where available.
- Reports must remain offline static HTML/Markdown/CSV/SVG only.

## Fixture Plan

Add fixtures under `tests/fixtures/management_matrix/`:

- `success/`
  - all 11 required operations
  - non-empty `command_log.jsonl`
  - non-empty `management_operation_results.jsonl`
  - before/after snapshots and topology diffs
  - workload impact and cleanup refs
- `missing_command_ref/`
  - one PASS operation with `command_count: 0` and no structured reason; gate must fail
- `missing_topology_snapshot/`
  - missing before/after snapshot; gate must fail
- `reshard_missing_extra/`
  - reshard/rebalance missing `slots_moved`, `keys_moved`, `slot_balance_*`, or `imbalance_delta`; gate must fail
- `rolling_missing_extra/`
  - rolling restart missing per-node stop/restart/rejoin/unavailable metrics; gate must fail
- `blocked_real_run/`
  - matrix status `BLOCKED_WITH_REASON` with blocked preflight/port-bind reason, no fake PASS
- `dry_run_200_plus/`
  - planning-only rows with `SKIPPED_WITH_REASON` or `UNSUPPORTED_WITH_REASON`; no real runtime claim
- `cleanup_residual/`
  - cleanup ref reports residual resources; analysis/report must surface it

Tests:

- `tests/artifacts/test_management_matrix.py`
  - validates fixtures against schemas and helper writer output
- `tests/analysis/test_analysis_summary.py`
  - verifies management aggregation and missing metrics propagation
- `tests/report/test_report_rendering.py`
  - verifies Chinese sections and CSV/SVG report outputs
- `tests/integration/test_docker_runtime_contract.py`
  - verifies strict management runtime emits new refs and shared field names without real Docker
- `tests/unit/test_goal_loop_assertions.py`
  - gate accepts success fixture and rejects negative fixtures

## Stage Gate Plan

Add:

- `scripts/assert_management_matrix_m1.py`

Gate inputs:

- `--artifacts-dir <dir>`
- optional `--analysis <analysis_summary.json>`
- optional `--report-index <report_index.json>`
- optional `--fixtures tests/fixtures/management_matrix`

Gate checks:

- `management_ops_matrix.json` exists, schema-valid, and non-empty.
- `management_operation_results.jsonl` exists, schema-valid, and non-empty.
- `management_topology_snapshots.jsonl` exists, schema-valid, and non-empty for PASS/non-blocked runs.
- `management_topology_diffs.jsonl` exists, schema-valid, and non-empty for PASS/non-blocked runs.
- All 11 required operations are present in matrix and operation results.
- Every required operation has `before_topology_snapshot` and `after_topology_snapshot` or refs to rows in `management_topology_snapshots.jsonl`.
- Every required operation has `topology_diff`, `slot_diff`, `role_diff`, `cluster_state_before/after`, `known_nodes_before/after`, and fail/pfail/handshake counts before/after.
- Every PASS operation has `command_count > 0`, `command_log_refs` that resolve to command ids in `command_log.jsonl` or `management_command_log.jsonl`, and `retry_count`/`error_count` numeric.
- Reshard/rebalance operations have complete extra fields.
- Rolling restart operations have complete per-node extra fields and plan/result refs.
- `workload_impact_ref` resolves to `management_workload_impact.json`.
- `cleanup_ref` is present and structured.
- Blocked run must use `BLOCKED_WITH_REASON` and must not set `real_execution_verified: true`.
- Analysis contains `management_ops`.
- Report index contains `management_report_inputs`.
- HTML/Markdown contain Chinese management sections.
- Fixtures include success, failure, timeout/blocked, missing metric, cleanup residual, dry-run/blocked coverage.

Keep `scripts/assert_management_matrix_strict.py` for legacy P30 strict checks, but M1-S04 exit should use the new milestone1 gate because it enforces schema -> writer -> fixture -> reader -> aggregator -> renderer -> gate.

## Coverage Matrix Plan

The worker should update `runs/m1-s04-local/artifacts/goal_loop/M1-S04/coverage_matrix.md` with at least these rows:

| change_id | field_or_behavior | execution_shape | scale_rung | functional_path | data_path | outcome_class | coverage_status | evidence_path | test_or_gate | missing_or_skipped_reason |
|---|---|---|---|---|---|---|---|---|---|---|
| M1S04-001 | required management operation set | fake/unit/integration/smoke/real_local_run/blocked_run | small_cluster/30/50/100/200 | management_ops | schema/writer/fixture/gate | success | PASS | schemas/artifact/management_ops_matrix.schema.json | assert_management_matrix_m1.py | none |
| M1S04-002 | before/after topology snapshots | fake/unit/integration/smoke/blocked_run | small_cluster/30/50/100/200 | management_ops/metrics | schema/writer/reader/gate | success/missing_metric | PASS | management_topology_snapshots.jsonl | assert_management_matrix_m1.py | none |
| M1S04-003 | topology/slot/role diffs | fake/unit/integration/smoke/blocked_run | small_cluster/30/50/100/200 | management_ops/analysis/report | schema/writer/reader/renderer/gate | success | PASS | management_topology_diffs.jsonl | report rendering tests | none |
| M1S04-004 | command-log refs from M1-S03 | fake/unit/integration/smoke/blocked_run | small_cluster/30/50/100/200 | management_ops | writer/reader/aggregator/gate | command_failure/timeout/success | PASS | command_log.jsonl | assert_command_log_nonempty_and_schema.py + assert_management_matrix_m1.py | none |
| M1S04-005 | workload impact refs | fake/unit/integration/smoke/blocked_run | small_cluster/30/50/100/200 | workload/management_ops | writer/reader/renderer/gate | success/report_input_missing | PASS | management_workload_impact.json | assert_management_matrix_m1.py | none |
| M1S04-006 | reshard/rebalance extras | fake/unit/integration/smoke/blocked_run | small_cluster/30/50/100/200 | management_ops | schema/writer/fixture/gate | success/missing_metric | PASS | management_operation_results.jsonl | negative fixture gate | none |
| M1S04-007 | rolling restart extras | fake/unit/integration/smoke/blocked_run | small_cluster/30/50/100/200 | management_ops | schema/writer/fixture/gate | success/missing_metric | PASS | rolling_restart_results.jsonl | negative fixture gate | none |
| M1S04-008 | Chinese management report | unit/integration/smoke | small_cluster/30/50/100/200 | report | renderer/regression_check | success/report_input_missing | PASS | reports/report.md, reports/index.html | report tests + assert_management_matrix_m1.py | none |
| M1S04-009 | real local run unavailable | real_local_run/blocked_run | small_cluster | management_ops | gate/artifact | blocked_run | BLOCKED_WITH_REASON | real_heavy_gate_blocked.json | valkey_e2e_gate.py | sandbox port bind may deny 127.0.0.1:7000; must not fake PASS |
| M1S04-010 | 200+ planning only | dry_run | 200_plus_dry_run_planning | plan/resource_preflight | fixture/gate | success | SKIPPED_WITH_REASON | dry_run_200_plus fixture | assert_management_matrix_m1.py | 200+ real execution is out of milestone1 scope |

## Gates To Run

Stage-specific:

- `PYTHONPATH=src python3 scripts/assert_management_matrix_m1.py --fixtures tests/fixtures/management_matrix`
- `PYTHONPATH=src python3 scripts/assert_management_matrix_m1.py --artifacts-dir runs/m1-s04-local/artifacts --analysis runs/m1-s04-local/artifacts/analysis_summary.json --report-index runs/m1-s04-local/reports/report_index.json`
- Schema validation for:
  - `management_ops_matrix.json`
  - `management_operation_results.jsonl`
  - `management_topology_snapshots.jsonl`
  - `management_topology_diffs.jsonl`
  - `command_log.jsonl`
  - `command_audit_summary.json`

Common:

- `PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m compileall -q scripts src`
- `PYTHONPATH=src python3 -m pytest -q tests/artifacts/test_management_matrix.py tests/analysis/test_analysis_summary.py tests/report/test_report_rendering.py tests/integration/test_docker_runtime_contract.py`
- `PYTHONPATH=src python3 -m pytest -q tests/unit tests/integration`
- Real heavy attempt with wrapper, expected to PASS only if local Valkey can bind ports. If the current sandbox still denies `127.0.0.1:7000`, write `real_heavy_gate_blocked.json` with `BLOCKED_WITH_REASON`, stderr/stdout refs, `fake_real_evidence: false`, and no PASS claim.

## Risks And Validation Points

- Existing P30 code writes `management_command_log.jsonl` manually, while M1-S03 writes `command_log.jsonl` through `CommandRecorder`. Review should reject a PASS operation that only has synthetic command rows and no resolvable M1-S03-style refs.
- Existing schemas are permissive. M1-S04 must fail on missing required fields via schema or gate, not merely accept `additionalProperties`.
- Setup verification operations (`create_cluster`, `meet_nodes`, `add_replica`) may have `command_ms: 0` because they summarize setup already completed. They still need command evidence from setup command log or structured `SKIPPED_WITH_REASON`; for PASS rows, prefer refs to setup commands.
- Topology diffs for operations that restore cluster state may have no final node-count change. That is valid only if the diff still records observed command, slot, role, or health/convergence evidence.
- Workload benchmark is improved in M1-S05, so M1-S04 should use existing workload-window refs and structure them so M1-S05 can enrich, not replace, the contract.
- Real local gate may remain environmentally blocked. That is acceptable only with structured blocked artifacts and no `real_execution_verified: true`.

## Review-Fail Checkpoints

Review must FAIL if any of these are true:

- Any of the 11 required operations is absent from matrix or operation results.
- A PASS operation lacks before/after topology snapshots or topology diff.
- A PASS operation has `command_count == 0` without a structured reason, or command refs do not resolve to command-log rows.
- Reshard/rebalance rows lack `slots_moved`, `keys_moved`, `bytes_migrated` numeric-or-missing reason, `slot_balance_before`, `slot_balance_after`, or `imbalance_delta`.
- Rolling restart rows lack per-node stop/restart/rejoin/unavailable timings or cluster impact.
- New fields exist only in fixtures, only in the runtime writer, or only in the report.
- Analysis does not read management artifacts.
- Chinese report does not render management matrix and topology diff sections.
- Gate checks only file existence and not content.
- Empty JSONL files are accepted.
- A blocked real Valkey run is presented as PASS.
- Any implementation introduces long soak stage or >200 real nodes.
