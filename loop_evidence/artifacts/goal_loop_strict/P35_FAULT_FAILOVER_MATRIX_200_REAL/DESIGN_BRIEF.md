# DESIGN_BRIEF - P35_FAULT_FAILOVER_MATRIX_200_REAL

## Objective

Execute the strict fault/failover/partition/split-brain/workload-impact matrix on exactly 200 real Valkey 9.1.x nodes for `P35_FAULT_FAILOVER_MATRIX_200_REAL`. P35 must not downshift to 100 nodes, must not run above 200 nodes, must not use dry-run or generated evidence as proof, and must block with `BLOCKED.md` if resource preflight or exact 200-node observation fails.

## Current Repository Facts

- `docs/codex/goal-loop-strict/stages/P35_FAULT_FAILOVER_MATRIX_200_REAL.md` requires exactly 200 real nodes, all 12 fault rows, at least 3 independent `primary_stop_failover` samples, sandboxed network faults, split-brain detector evidence, workload impact for every row, and cleanup PASS.
- `artifacts/goal_loop_strict/P35_FAULT_FAILOVER_MATRIX_200_REAL/CONTEXT_RELOAD.md` records P34 as completed/pushed at commit `1dad23b`; P35 must not reuse P34 evidence for `200.fault.*`.
- `codex/phase_manifest.json` already has a P35 manifest entry with `max_nodes=200`, `real_valkey_required=true`, a real gate command using `scripts/fault_failover_gate.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --scenario strict_fault_matrix_200_fault_failover --config templates/configs/scale_200.yaml --min-nodes 200`, and required artifacts matching the stage doc.
- `scripts/fault_failover_gate.py` currently defines strict fault profiles for P33/P34 only: `P33_FAULT_FAILOVER_MATRIX_50_REAL` with `strict_fault_matrix_50_fault_failover`, and `P34_FAULT_FAILOVER_MATRIX_100_REAL` with `strict_fault_matrix_100_fault_failover`. P35 is not yet present in `STRICT_FAULT_PROFILES`.
- `src/valkey_scale_lab/runtime/docker_runtime.py` currently maps strict fault setup scenarios only for P33/P34 in `_strict_fault_matrix_node_count`; `tests/integration/test_docker_runtime_contract.py` currently asserts that P35 `strict_fault_matrix_200` is not process runtime.
- `src/valkey_scale_lab/runtime/docker_runtime.py` allows exact 200 runtime exceptions only for P21 samples and P32 management in `_exact_200_stage_scenario_allowed`, and allows config marker phases only in `{"P21_FAILOVER_LATENCY_CURVE_200", P32_STAGE}`.
- `src/valkey_scale_lab/resource.py` allows exact 200 resource preflight exceptions only for P21 and P32 via `EXACT_200_CONFIG_MARKER_PHASES` and `_exact_200_phase_scenario_allowed`.
- `src/valkey_scale_lab/planner/plan.py` has a P32-specific exact-200 helper. P35 may not need planner-backed cluster plans because `scripts/fault_failover_gate.py` builds P33/P34 strict fault cluster-plan artifacts from live state, but any direct P35 planning path remains 待验证 unless updated or intentionally avoided.
- `src/valkey_scale_lab/cli.py` exposes `resource preflight --config --out --dry-run`, but does not expose `--phase` or `--scenario`, so `scripts/fault_failover_gate.py` cannot currently ask the CLI resource preflight to evaluate the P35 bounded exception explicitly.
- `templates/configs/scale_200.yaml` creates 200 nodes, keeps `default_max_nodes: 100`, `allow_1000_nodes: false`, and has `scale_profile.bounded_exception_phase: P21_FAILOVER_LATENCY_CURVE_200`. `scripts/safety_scan.py` explicitly permits this locked config shape; changing the config marker would require extra safety/gate-lock care and is not the preferred P35 path unless proven necessary.
- `scripts/assert_fault_matrix_strict.py`, `scripts/assert_failover_latency_curve.py`, `scripts/assert_split_brain_report.py`, and `scripts/assert_coverage_registry.py` already recognize P35/scale 200.
- `scripts/assert_quant_completeness.py` currently defines strict fault stages only for P33 and P34. P35 must be added there or the required P35 quant gate will not validate the strict fault artifacts.
- `artifacts/coverage/strict_coverage_registry.json` already contains 12 pending `200.fault.*` rows owned by P35. `scripts/strict_coverage_defs.py` and `scripts/build_strict_coverage_registry.py` already map fault scale 200 to P35.

## Scope Boundaries

- Implement only P35 exact-200 fault/failover support.
- Do not make 200 nodes a default. Keep `default_max_nodes=100`.
- Do not allow arbitrary stages/scenarios to run 200 nodes.
- Do not create any real-runtime path above 200 nodes.
- Do not weaken harness scripts, gate checks, locked-file semantics, no-bypass checks, safety scan, schemas, or required artifacts.
- Do not mark complete, commit, push, or edit phase state in the worker step.

## Exact Implementation Plan

1. Add a P35 strict fault profile in `scripts/fault_failover_gate.py`.
   - Define `P35_PHASE = "P35_FAULT_FAILOVER_MATRIX_200_REAL"` and `P35_SETUP_SCENARIO = "strict_fault_matrix_200"`.
   - Add profile key `(P35_PHASE, "strict_fault_matrix_200_fault_failover")` with `scale=200`, `config_name="scale_200.yaml"`, `stage_label="P35"`, `work_dir_name="_p35_fault_matrix_work"`, and `state_file_name="state_fault_matrix_200.json"`.
   - Reuse the existing P33/P34 strict controller semantics, but keep every output path/stage label/coverage prefix exact to 200.
   - Increase setup/stability timeouts only for exact 200 where needed, for example setup timeout `2400` and stable/restore waits long enough for a 200-node cluster. Record timeout choices in artifacts/command logs where feasible.

2. Make P35 exact-200 setup an allowed bounded runtime exception.
   - In `src/valkey_scale_lab/runtime/docker_runtime.py`, add `("P35_FAULT_FAILOVER_MATRIX_200_REAL", "strict_fault_matrix_200"): 200` to `_strict_fault_matrix_node_count`.
   - Extend `_exact_200_stage_scenario_allowed` to permit `(P35_FAULT_FAILOVER_MATRIX_200_REAL, "strict_fault_matrix_200")`.
   - Ensure `_is_exact_200_runtime_exception` still requires `profile_name=="scale_200"`, `node_count==200`, `default_max_nodes==100`, `allow_1000_nodes is False`, `runtime.dry_run is False`, and an approved 200 config marker. Do not permit 201+ or unrelated P35 scenario names.
   - Confirm `_uses_docker_process_runtime` returns true for P35 setup and `_scenario_node_count_allowed` rejects 199, 201, P34/200, and unrelated 200 scenarios.

3. Make P35 resource preflight explicit and exact.
   - Add optional `--phase` and `--scenario` arguments to `src/valkey_scale_lab/cli.py resource preflight`, passing them through to `run_resource_preflight`.
   - In `src/valkey_scale_lab/resource.py`, add P35 phase/scenario allowance for exact 200, ideally via a small shared allowlist such as `{P21 scale_200_sample_*, P32 strict_management_matrix_200, P35 strict_fault_matrix_200}`.
   - In `scripts/fault_failover_gate.py`, call resource preflight with `--phase <profile.phase> --scenario <profile.setup_scenario>` so `resource_preflight.json` records P35, `nodes_requested=200`, `can_run=true`, and `dry_run=false`.
   - Preserve `templates/configs/scale_200.yaml` unless tests/gates prove a stage-specific marker is mandatory. If changing it becomes necessary, write a harness exception and update `safety_scan.py`/lock only in a strengthening way.

4. Add P35 quant completeness support.
   - In `scripts/assert_quant_completeness.py`, add P35 to `STRICT_FAULT_STAGES` with `scale=200`, `coverage_prefix="200.fault."`, the same 12 required rows, and `min_failover_samples=3`.
   - Do not loosen field, missing-data, workload-window, coverage-ledger, command-log, topology, or exact-scale checks.

5. Add/update focused tests.
   - In `tests/integration/test_docker_runtime_contract.py`, replace the current P35 rejection assertion with positive exact-200 assertions for `strict_fault_matrix_200`, and add rejection checks for 100, 199, 201, wrong scenario, and unrelated phase.
   - Add resource preflight tests in `tests/scale/test_scale_ladder.py` for P35 exact-200 allowance and wrong P35 scenario rejection.
   - Add CLI contract coverage in `tests/unit/test_cli_contract.py` or nearby unit tests for `resource preflight --phase --scenario` parsing/pass-through if current patterns support it.
   - Add a P35 quant completeness unit fixture, preferably by parameterizing the existing P34 helper in `tests/unit/test_goal_loop_assertions.py` over `(phase, scale, scenario, prefix)`, then assert P35 accepts 200 and rejects wrong `100.fault.*` prefixes or fewer than 3 samples.
   - Add a `scripts/fault_failover_gate.py` unit assertion that `strict_fault_profile(P35, "strict_fault_matrix_200_fault_failover")` returns scale 200 and config `scale_200.yaml`.

6. Run P35 real gate and let it produce artifacts.
   - Run P35 through `python3 scripts/codex_gate.py run --phase P35_FAULT_FAILOVER_MATRIX_200_REAL` after precheck and tests.
   - If resource preflight fails, write `artifacts/goal_loop_strict/P35_FAULT_FAILOVER_MATRIX_200_REAL/BLOCKED.md`, do not fabricate artifacts, and do not mark complete.
   - If exact 200 observed nodes, Valkey 9.1.x versions, rows, samples, workload windows, split-brain detector evidence, coverage ledger, or cleanup fail, fix only P35 and rerun from the worker/gate step.

## Files Likely To Change

- `scripts/fault_failover_gate.py`
- `src/valkey_scale_lab/runtime/docker_runtime.py`
- `src/valkey_scale_lab/resource.py`
- `src/valkey_scale_lab/cli.py`
- `scripts/assert_quant_completeness.py`
- `tests/integration/test_docker_runtime_contract.py`
- `tests/scale/test_scale_ladder.py`
- `tests/unit/test_goal_loop_assertions.py`
- `tests/unit/test_cli_contract.py` or another existing CLI-focused test file
- Runtime/generated P35 artifacts under `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/`
- Updated coverage registry at `artifacts/coverage/strict_coverage_registry.json` after P35 passes
- Worker/review/audit/closeout artifacts under `artifacts/goal_loop_strict/P35_FAULT_FAILOVER_MATRIX_200_REAL/`, `artifacts/gates/P35_FAULT_FAILOVER_MATRIX_200_REAL/`, and `audit/P35_FAULT_FAILOVER_MATRIX_200_REAL/`

Likely not needed unless a gate proves otherwise:

- `templates/configs/scale_200.yaml`
- `codex/phase_manifest.json`
- `schemas/**/*.json`
- `docs/codex/**/*.md`
- `codex/gate_lock.json`

## Schemas And Gates

No new schema is expected. Existing schemas should validate P35 outputs:

- `schemas/artifact/phase_summary.schema.json`
- `schemas/artifact/valkey_e2e_evidence.schema.json`
- `schemas/artifact/resource_preflight.schema.json`
- `schemas/artifact/cluster_plan.schema.json`
- `schemas/artifact/cleanup_report.schema.json`
- `schemas/artifact/goal_loop_event.schema.json`
- `schemas/artifact/goal_loop_metric_sample.schema.json`
- `schemas/artifact/workload_windows.schema.json`
- `schemas/artifact/quant_summary.schema.json`
- `schemas/artifact/strict_coverage_registry.schema.json`
- `schemas/artifact/fault_matrix_report.schema.json`
- `schemas/artifact/failover_latency_curve.schema.json`
- `schemas/artifact/partition_report.schema.json`
- `schemas/artifact/split_brain_report.schema.json`
- `schemas/artifact/workload_impact_report.schema.json`
- `schemas/artifact/command_log_entry.schema.json`
- `schemas/artifact/topology_snapshot.schema.json`

Required gates/commands:

```bash
python3 scripts/codex_gate.py precheck --phase P35_FAULT_FAILOVER_MATRIX_200_REAL
python3 scripts/safety_scan.py
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
python3 scripts/assert_strict_stage_contract.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL
python3 scripts/assert_no_bypass.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL
python3 scripts/fault_failover_gate.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --scenario strict_fault_matrix_200_fault_failover --config templates/configs/scale_200.yaml --out artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/valkey_e2e_evidence.json --failover-report artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/failover_report.json --fault-report artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/fault_report.json --workload-window-report artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/workload_windows.json --cleanup-report artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/cleanup_report.json --min-nodes 200 --require-data-path
python3 scripts/assert_exact_scale_real_evidence.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --nodes 200
python3 scripts/assert_fault_matrix_strict.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --scale 200 --require-all-rows
python3 scripts/assert_failover_latency_curve.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --scale 200 --min-samples 3
python3 scripts/assert_split_brain_report.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --scale 200
python3 scripts/assert_quant_completeness.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --category fault --scale 200
python3 scripts/assert_coverage_registry.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --scale 200 --category fault
python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/cleanup_report.json
python3 scripts/codex_gate.py run --phase P35_FAULT_FAILOVER_MATRIX_200_REAL
```

After worker and gate success, the main agent must run fresh-context review, then:

```bash
python3 scripts/codex_gate.py postcheck --phase P35_FAULT_FAILOVER_MATRIX_200_REAL
python3 scripts/codex_gate.py mark-complete --phase P35_FAULT_FAILOVER_MATRIX_200_REAL
```

Only the main agent should mark complete/commit/push after review PASS.

## Required Artifact List

P35 must produce:

- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/phase_summary.json`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/valkey_e2e_evidence.json`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/resource_preflight.json`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/cluster_plan.json`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/run_state.json`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/cleanup_report.json`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/events.jsonl`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/metrics_timeseries.jsonl`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/workload_windows.json`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/quant_summary.json`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/coverage_ledger.json`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/fault_matrix_report.json`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/fault_operation_results.jsonl`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/failover_samples.jsonl`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/failover_latency_curve.json`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/partition_report.json`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/split_brain_report.json`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/fault_workload_impact.json`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/fault_topology_snapshots.jsonl`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/fault_command_log.jsonl`

Stage-loop artifacts:

- `artifacts/goal_loop_strict/P35_FAULT_FAILOVER_MATRIX_200_REAL/DESIGN_BRIEF.md`
- `artifacts/goal_loop_strict/P35_FAULT_FAILOVER_MATRIX_200_REAL/WORKER_SUMMARY.md`
- `artifacts/goal_loop_strict/P35_FAULT_FAILOVER_MATRIX_200_REAL/REVIEW.md`
- `artifacts/goal_loop_strict/P35_FAULT_FAILOVER_MATRIX_200_REAL/BLOCKED.md` only if blocked
- `artifacts/goal_loop_strict/P35_FAULT_FAILOVER_MATRIX_200_REAL/COMPLETION.md` only after pass/commit/push
- `artifacts/gates/P35_FAULT_FAILOVER_MATRIX_200_REAL/gate_result.json`
- `audit/P35_FAULT_FAILOVER_MATRIX_200_REAL/AUDIT.md`
- `audit/P35_FAULT_FAILOVER_MATRIX_200_REAL/audit_decision.json`

## Coverage IDs Targeted

- `200.fault.primary_stop_failover`
- `200.fault.replica_stop`
- `200.fault.node_host_stop`
- `200.fault.az_stop`
- `200.fault.network_delay`
- `200.fault.network_loss`
- `200.fault.network_flap`
- `200.fault.network_partition`
- `200.fault.minority_partition`
- `200.fault.majority_partition`
- `200.fault.split_brain_window_detection`
- `200.fault.fault_period_workload_impact`

Every row must end as `PASS`, `execution_mode=real`, with source artifacts, validation artifacts, metrics refs, cleanup ref, and later review ref. `SKIPPED_WITH_REASON`, `MISSING`, `DRY_RUN_PASS`, or stale P34 source artifacts are not acceptable final states for P35.

## Safety Constraints

- Never mutate host firewall, routes, interfaces, PF, nftables, iptables, or OS network services.
- Do not use `sudo` for network operations.
- Network faults must use `sandbox_proxy` or `container_netns_tc` scoped to owned containers/project proxy only.
- Do not kill unrelated host processes or physical host network interfaces.
- Keep deterministic cleanup through existing owned state files, labels, work dirs, and cleanup reports.
- Do not run above 200 real nodes.
- Do not make 200 the default or broaden exact-200 exceptions beyond P21/P32/P35/P36 stage-specific paths.
- If Docker/resource capacity cannot run 200, block the stage; do not downshift.

## Blocked Conditions

P35 must write `artifacts/goal_loop_strict/P35_FAULT_FAILOVER_MATRIX_200_REAL/BLOCKED.md` and stop without mark-complete if:

- `resource_preflight.json` has `can_run=false` or does not record P35 exact 200.
- Setup cannot create exactly 200 live Valkey nodes.
- `valkey_e2e_evidence.json` lacks `nodes_requested=200`, `nodes_observed=200`, `real_valkey=true`, Valkey `9.1.x`, or `data_path_result=PASS`.
- Any required fault row is missing, skipped, unsupported, or not PASS.
- Fewer than 3 independent primary-stop failover samples are recorded.
- Network faulting would require host-level mutation.
- Split-brain report lacks detector-run evidence, especially if `split_brain_window_ms=0`.
- Any row lacks workload impact/event/metric/topology/command evidence.
- Cleanup status is not PASS or owned resources remain.
- Required tests/gates fail.

## Review Focus Points

- Verify P35 is the only new exact-200 fault runtime path and that it does not raise `default_max_nodes`.
- Verify P35 setup scenario is exactly `strict_fault_matrix_200` and wrapper scenario is exactly `strict_fault_matrix_200_fault_failover`.
- Verify P35 resource preflight is evaluated as P35, not merely inherited as P21, and records exact 200 non-dry-run capacity.
- Verify `templates/configs/scale_200.yaml` semantics remain safe; any config or safety-scan changes must be justified as strengthening, not bypassing.
- Verify P35 artifacts are fresh and source paths are under `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/`, not P34 or P21.
- Verify coverage ledger/global registry update only the 12 `200.fault.*` rows and do not touch future P36/P37 rows.
- Verify no generated or fallback artifacts are treated as real proof after a failed setup.
- Verify command logs and fault reports prove `sandbox_proxy` or `container_netns_tc` for network rows and owned runtime controls for non-network rows.
- Verify split-brain detectors ran and `split_brain_window_ms=0` is detector-backed, not a placeholder.
- Verify cleanup report and post-cleanup inventory are PASS before review/mark-complete.

## 待验证 Items

- 待验证: whether the local Docker environment can pass 200-node resource preflight and sustain the full P35 matrix within the manifest’s 7200-second real gate timeout.
- 待验证: whether P35 needs longer `wait_for_stable_cluster_ok` or `wait_after_fault` values than P34 due to the 200-node topology.
- 待验证: whether direct planner support for P35 exact-200 is needed by any P35 gate path, or whether live-state cluster-plan generation remains sufficient.
- 待验证: whether `scale_profile.bounded_exception_phase` should remain the existing P21 marker or be broadened in code documentation only. Prefer not changing the locked config unless a gate proves it necessary.
- 待验证: whether Docker Desktop/container runtime limits expose enough memory, ports, and process capacity for 200 Valkey processes in this environment.
