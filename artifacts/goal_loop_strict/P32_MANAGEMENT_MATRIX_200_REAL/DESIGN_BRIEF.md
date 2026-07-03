# DESIGN_BRIEF - P32_MANAGEMENT_MATRIX_200_REAL

## Fresh read confirmation

Read `docs/codex/goal-loop-strict/prompts/DESIGN_SUBAGENT_PROMPT.md` and used it as the governing prompt for this design-only task. Also read the required base, goal-loop, strict-loop, P32 stage, strict journal, P32 context reload, and strict design template documents. Current observed git status before this output: `artifacts/goal_loop_strict/P32_MANAGEMENT_MATRIX_200_REAL/` is untracked because the main agent already added `CONTEXT_RELOAD.md`; no source-code edits were made by this design pass.

## Stage objective

Execute the complete strict management operation matrix on exactly 200 real Valkey 9.1.x nodes. P32 may pass only if resource preflight records `can_run=true`, `nodes_requested=200`, exact 200-node real evidence is observed, all 11 required `200.management.*` rows are `PASS`, workload impact and telemetry artifacts validate, coverage registry rows are updated from real source artifacts, and cleanup reports `PASS`.

## Current repository findings

- `docs/codex/goal-loop-strict/stages/P32_MANAGEMENT_MATRIX_200_REAL.md` requires exact 200 real nodes, all 11 management rows, `resource_preflight.json`, real Valkey evidence, strict telemetry artifacts, management artifacts, coverage ledger, and cleanup.
- `codex/phase_manifest.json` already declares P32 automatic, `max_nodes=200`, `bounded_200_exception=true`, and gate command `scripts/valkey_e2e_gate.py --phase P32_MANAGEMENT_MATRIX_200_REAL --scenario strict_management_matrix_200 --config templates/configs/scale_200.yaml --min-nodes 200 --require-data-path`.
- `templates/configs/scale_200.yaml` defines 100 shards with one replica each, ports `7800-7999` and `17800-17999`, Valkey image `valkey/valkey:9.1.0`, and workload enabled. It still names `scale_profile.bounded_exception_phase: P21_FAILOVER_LATENCY_CURVE_200`; P32 acceptance through this file is 待验证 and likely needs stage-aware 200-exception handling.
- `src/valkey_scale_lab/runtime/docker_runtime.py` currently has strict management profiles only for P30 and P31: `P30_MANAGEMENT_MATRIX_50_REAL/strict_management_matrix_50` and `P31_MANAGEMENT_MATRIX_100_REAL/strict_management_matrix_100`. P32 is not yet admitted in `create_scenario`, `_uses_docker_process_runtime`, `_scenario_node_count_allowed`, strict-management profile lookup, or slow `cluster_node_timeout` assignment.
- The P30/P31 artifact writer in `src/valkey_scale_lab/runtime/docker_runtime.py` is mostly profile-driven once a `StrictManagementProfile` exists: operation IDs, coverage IDs, artifact refs, workload windows, matrix rows, quant summary, coverage ledger, and registry updates derive from active scale/profile.
- `src/valkey_scale_lab/resource.py` currently treats the 200-node bounded preflight exception as P21-specific via `_is_p21_200_exception`, `_phase_for_node_count`, and report fields. P32 preflight must be accepted only for the current exact-200 stage and must still preserve `default_max_nodes=100`.
- `scripts/assert_quant_completeness.py` currently enumerates strict management validation for P30/P31 only. It must include P32 with scale `200`, coverage prefix `200.management.`, and timing artifact `runtime_timing_breakdown_strict_management_matrix_200.json`.
- `scripts/assert_management_matrix_strict.py`, `scripts/assert_exact_scale_real_evidence.py`, `scripts/assert_coverage_registry.py`, and `scripts/assert_cleanup.py` are already scale/phase-parameterized and should work if P32 artifacts are exact-scale and complete.
- `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md` records P30 and P31 PASS evidence at exact 50 and 100 nodes; it explicitly leaves `200.management.*` rows for P32.
- P31 review records exact 100-node real evidence, 11 PASS rows, 154 event rows, 1452 metric samples, 66 workload windows, 2772 command log rows, and cleanup PASS. P32 must not reuse those artifacts as proof.

## Scope boundaries

Implement only P32. Do not implement P33+ fault/failover rows, P36 full-flow rows, or P37 >200 dry-run behavior except preserving interfaces they depend on. Do not mark complete, commit, push, edit phase state, edit gate results, or fabricate artifacts. If any harness-control file is defective, write the required harness exception and make only a strengthening fix.

## Implementation plan

1. Add a P32 strict management profile in `src/valkey_scale_lab/runtime/docker_runtime.py`.
   - Add constants for `P32_MANAGEMENT_MATRIX_200_REAL`, `strict_management_matrix_200`, scale `200`, and config `templates/configs/scale_200.yaml`.
   - Add `(P32_STAGE, P32_SCENARIO)` to `STRICT_MANAGEMENT_PROFILES`, `create_scenario` admission, `_uses_docker_process_runtime`, `_scenario_node_count_allowed`, and slow cluster-node-timeout logic.
   - Add an integration admission test: allow exactly 200; reject 199, 100, and 201; require Docker process runtime.

2. Generalize exact-200 bounded exception handling without raising defaults.
   - Replace P21-only preflight/runtime exception checks in `src/valkey_scale_lab/resource.py` and `docker_runtime.py` with an allowlist for exact 200 real stages: P21 existing failover, P32 management, P35 fault, and P36 full-flow as already declared by strict docs/manifest.
   - Keep acceptance conditions strict: `node_count==200`, `profile_name=="scale_200"`, `default_max_nodes==100`, `allow_1000_nodes is false`, `runtime.dry_run is false`, stage/scenario matches an allowed exact-200 real stage, and no real execution above 200.
   - Ensure P32 `resource_preflight.json` reports `phase_id=P32_MANAGEMENT_MATRIX_200_REAL`, `scenario_name=strict_management_matrix_200`, `nodes_requested=200`, `node_count=200`, `can_run`, and bounded-exception details naming P32 or a stage-aware list rather than claiming P21-only.
   - If `can_run=false`, runtime must write `artifacts/goal_loop_strict/P32_MANAGEMENT_MATRIX_200_REAL/BLOCKED.md`, fail the gate, and avoid downshift/fake artifacts.

3. Carry P30/P31 management semantics to 200 nodes.
   - Reuse the existing process-in-owned-Docker-nodehost runtime path; do not introduce host networking changes or a new unsandboxed runtime.
   - Start exactly 200 Valkey processes, verify 100 primaries and 100 replicas, and write `run_state.json` with 200 nodes.
   - Run all 11 rows through the same semantics as P30/P31: setup proof, remove/restore replica, safe primary replacement/removal, failed-node removal through owned controls, slot range reshard, keyed reshard, imbalance-reducing rebalance, replica-first rolling restart, and safe primary rolling restart.
   - Ensure scale-derived expectations are not hard-coded to 50/100: temporary removal should observe 199 nodes, restore should return to 200, rolling restart should produce 200 restart rows and health gates, coverage IDs must be `200.management.*`.

4. Tune only bounded P32 runtime limits if real 200 evidence requires it.
   - P32 manifest currently omits the P30/P31 `--probe-timeout 10` pattern; add a bounded P32 `--probe-timeout 10` or documented larger value only if needed by real gate behavior.
   - If convergence or setup timeouts are insufficient at 200, adjust deterministic timeout formulas or P32-specific manifest timeout narrowly; do not weaken health gates or allow smaller node counts.

5. Extend strict quant validation.
   - Add P32 to `STRICT_MANAGEMENT_STAGES` in `scripts/assert_quant_completeness.py`.
   - Verify exact `scale=200`, `node_count=200`, 11 operation rows, 11 coverage passes, real Valkey/data-path evidence, cleanup PASS, canonical workload windows per operation, and no forbidden null/NaN/undefined placeholders.

6. Preserve and update coverage correctly.
   - `coverage_ledger.json` for P32 should include the global strict registry snapshot with exactly 11 P32 management rows updated to `PASS` and prior P30/P31 rows preserved.
   - Global `artifacts/coverage/strict_coverage_registry.json` should update only `200.management.*` rows. Later fault/lifecycle/full-flow/dry-run rows must remain pending unless already legitimately completed.

## Harness plan

Expected P32 gate sequence:

```bash
python3 scripts/codex_gate.py precheck --phase P32_MANAGEMENT_MATRIX_200_REAL
python3 scripts/safety_scan.py
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
python3 scripts/assert_strict_stage_contract.py --phase P32_MANAGEMENT_MATRIX_200_REAL
python3 scripts/assert_no_bypass.py --phase P32_MANAGEMENT_MATRIX_200_REAL
python3 scripts/valkey_e2e_gate.py --phase P32_MANAGEMENT_MATRIX_200_REAL --scenario strict_management_matrix_200 --config templates/configs/scale_200.yaml --out artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/valkey_e2e_evidence.json --min-nodes 200 --require-data-path
python3 scripts/assert_exact_scale_real_evidence.py --phase P32_MANAGEMENT_MATRIX_200_REAL --nodes 200
python3 scripts/assert_management_matrix_strict.py --phase P32_MANAGEMENT_MATRIX_200_REAL --scale 200 --require-all-rows
python3 scripts/assert_quant_completeness.py --phase P32_MANAGEMENT_MATRIX_200_REAL --category management --scale 200
python3 scripts/assert_coverage_registry.py --phase P32_MANAGEMENT_MATRIX_200_REAL --scale 200 --category management
python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/cleanup_report.json
python3 scripts/codex_gate.py run --phase P32_MANAGEMENT_MATRIX_200_REAL
```

Use `PYTHONPYCACHEPREFIX=/tmp/vslab-p32-pycache` for compile/pytest commands if sandboxed Python cache writes fail. If locked harness files change, refresh `codex/gate_lock.json` through the existing project path and document why the change strengthens or preserves fail-closed behavior.

## Schema and artifact plan

No new schema is clearly required. Existing schemas should remain compatible:

- `schemas/artifact/resource_preflight.schema.json`
- `schemas/artifact/cluster_plan.schema.json`
- `schemas/artifact/strict_generic_report.schema.json`
- `schemas/artifact/valkey_e2e_evidence.schema.json`
- `schemas/artifact/management_ops_matrix.schema.json`
- `schemas/artifact/management_operation_result.schema.json`
- `schemas/artifact/topology_snapshot.schema.json`
- `schemas/artifact/command_log_entry.schema.json`
- `schemas/artifact/workload_windows.schema.json`
- `schemas/artifact/workload_impact_report.schema.json`
- `schemas/artifact/quant_summary.schema.json`
- `schemas/artifact/cleanup_report.schema.json`
- `schemas/artifact/strict_coverage_registry.schema.json`

Required P32 artifacts:

- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/phase_summary.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/valkey_e2e_evidence.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/resource_preflight.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/cluster_plan.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/run_state.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/cleanup_report.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/events.jsonl`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/metrics_timeseries.jsonl`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/workload_windows.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/quant_summary.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/coverage_ledger.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/management_ops_matrix.json`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/management_operation_results.jsonl`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/management_topology_snapshots.jsonl`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/management_command_log.jsonl`
- `artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/management_workload_impact.json`

Useful extra source artifacts, if produced by the existing runtime path: `runtime_timing_breakdown_strict_management_matrix_200.json`, `cluster_snapshots_strict_management_matrix_200.json`, `state_strict_management_matrix_200.json`, `reshard_slot_movements.jsonl`, `rebalance_summary.json`, `rolling_restart_plan.json`, and `rolling_restart_results.jsonl`.

## Coverage IDs targeted

- `200.management.create_cluster`
- `200.management.meet_nodes`
- `200.management.add_replica`
- `200.management.remove_replica`
- `200.management.remove_primary_drained_or_safe_replaced`
- `200.management.remove_failed_node`
- `200.management.reshard_slot_range`
- `200.management.reshard_with_keys`
- `200.management.rebalance_after_imbalance`
- `200.management.rolling_restart_replica_first`
- `200.management.rolling_restart_primary_safe`

No P33 fault rows, P36 lifecycle/full-flow rows, or P37 >200 dry-run rows should be marked PASS in P32.

## Test and gate plan

Focused development checks:

```bash
PYTHONPYCACHEPREFIX=/tmp/vslab-p32-pycache python3 -m compileall -q scripts src
PYTHONPYCACHEPREFIX=/tmp/vslab-p32-pycache python3 -m pytest -q tests/unit tests/integration
PYTHONPYCACHEPREFIX=/tmp/vslab-p32-pycache python3 scripts/assert_strict_stage_contract.py --phase P32_MANAGEMENT_MATRIX_200_REAL
PYTHONPYCACHEPREFIX=/tmp/vslab-p32-pycache python3 scripts/assert_no_bypass.py --phase P32_MANAGEMENT_MATRIX_200_REAL
python3 scripts/codex_gate.py precheck --phase P32_MANAGEMENT_MATRIX_200_REAL
```

Real gate and assertions:

```bash
python3 scripts/codex_gate.py run --phase P32_MANAGEMENT_MATRIX_200_REAL
python3 scripts/assert_exact_scale_real_evidence.py --phase P32_MANAGEMENT_MATRIX_200_REAL --nodes 200
python3 scripts/assert_management_matrix_strict.py --phase P32_MANAGEMENT_MATRIX_200_REAL --scale 200 --require-all-rows
python3 scripts/assert_quant_completeness.py --phase P32_MANAGEMENT_MATRIX_200_REAL --category management --scale 200
python3 scripts/assert_coverage_registry.py --phase P32_MANAGEMENT_MATRIX_200_REAL --scale 200 --category management
python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P32_MANAGEMENT_MATRIX_200_REAL/cleanup_report.json
```

Add or update tests likely in:

- `tests/integration/test_docker_runtime_contract.py` for P32 exact admission, process runtime routing, and narrow 200 exception behavior.
- `tests/unit/test_goal_loop_assertions.py` for P32 quant completeness and no-bypass/downshift guard coverage if existing fixtures do not already cover it.
- Resource/preflight-focused tests if stage-aware exact-200 exception logic is added outside existing coverage.

## Safety constraints

- Never downshift P32 to 100 or any smaller node count.
- Never run above 200 real nodes.
- Do not change physical host networking, global firewall/routing/PF/nftables/iptables, host interfaces, or OS network services.
- Do not use `sudo` for network, route, firewall, or interface changes.
- Use only owned Docker containers, owned process namespaces inside those containers, owned networks, deterministic labels, deterministic ports, and deterministic cleanup.
- Missing values must be encoded as `MISSING`, `SKIPPED_WITH_REASON`, or another allowed status with a reason. Required P32 management rows cannot pass as skipped.
- Cleanup must be idempotent and must fail the stage if owned containers, networks, or Valkey processes remain.

## Blocked conditions

- `resource_preflight.json` has `can_run=false` or does not identify exact 200 requested nodes.
- Docker or the Valkey 9.1.x image is unavailable.
- Required port ranges `7800-7999` or `17800-17999` are unavailable.
- The runtime admits any non-200 node count for P32 or accepts P32 by weakening the global default cap above 100.
- `nodes_observed` is not exactly 200, Valkey version does not start with `9.1.`, or data-path proof fails.
- Any required management row is missing, skipped, synthetic, replayed, or not `PASS`.
- Workload impact windows, metrics, topology snapshots, or command logs are missing/invalid.
- Coverage registry does not update all 11 `200.management.*` rows to PASS from source artifacts.
- Cleanup report is missing or not `PASS`.

## Risks

- P32 doubles the P31 cluster size; startup, cluster create, replica configuration, reshard, and rolling restart timing may exceed current bounded defaults.
- The current 200 config still names P21 in `scale_profile`; careless changes could either block P32 incorrectly or broaden the 200 exception too far.
- P30/P31 helper names are still P30-prefixed; behavior may be scale-aware, but mixed names in new code or artifacts could confuse review. Functional IDs and artifact contents must be P32/200-specific.
- The 200-node rolling restart row may be the longest operation because it health-gates 200 individual restarts; timeout changes must be narrow and recorded.
- Global coverage registry updates must preserve P30/P31 PASS rows and not accidentally mark future lifecycle/fault/full-flow rows.

## 待验证

- 待验证: local Docker resources can actually support exactly 200 Valkey processes plus workload and telemetry overhead.
- 待验证: `resource_preflight.json` for P32 reports `can_run=true`; otherwise the stage must block with `BLOCKED.md`.
- 待验证: `strict_management_matrix_200` completes end to end with `nodes_observed=200`, Valkey `9.1.x`, and data-path PASS.
- 待验证: P30/P31 operation semantics remain stable at 200 nodes without weakening convergence or workload checks.
- 待验证: P32 needs a bounded `--probe-timeout` or larger gate timeout beyond the current manifest command.
- 待验证: existing schemas remain sufficient for all P32 artifacts after the exact-200 run.
- 待验证: locked harness files changed by the worker require `codex/gate_lock.json` refresh.
