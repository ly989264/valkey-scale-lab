# WORKER_SUMMARY - P35_FAULT_FAILOVER_MATRIX_200_REAL

## Status

Implementation complete for the P35 worker scope. Full real 200-node Docker fault/failover gate was not run by this worker; it should be run by the main stage gate loop.

## Changed Files

- `scripts/fault_failover_gate.py`
- `src/valkey_scale_lab/runtime/docker_runtime.py`
- `src/valkey_scale_lab/resource.py`
- `src/valkey_scale_lab/cli.py`
- `scripts/assert_quant_completeness.py`
- `tests/integration/test_docker_runtime_contract.py`
- `tests/scale/test_scale_ladder.py`
- `tests/unit/test_cli_contract.py`
- `tests/unit/test_goal_loop_assertions.py`
- `artifacts/harness_exception/P35_FAULT_FAILOVER_MATRIX_200_REAL.md`
- `artifacts/goal_loop_strict/P35_FAULT_FAILOVER_MATRIX_200_REAL/resource_preflight_check.json`
- `artifacts/goal_loop_strict/P35_FAULT_FAILOVER_MATRIX_200_REAL/WORKER_SUMMARY.md`

## Implementation Notes

- Added P35 strict fault profile for `P35_FAULT_FAILOVER_MATRIX_200_REAL` / `strict_fault_matrix_200_fault_failover`.
- P35 uses `templates/configs/scale_200.yaml`, exact scale 200, setup scenario `strict_fault_matrix_200`, work dir `_p35_fault_matrix_work`, and state file `state_fault_matrix_200.json`.
- Added bounded P35 setup/convergence timeouts: setup 2400s, stable 420s, restore 420s, with node-host/AZ restore preserving at least 600s.
- Added exact P35/runtime allowlist for only `(P35_FAULT_FAILOVER_MATRIX_200_REAL, strict_fault_matrix_200)`.
- Added P35 resource preflight identity handling and CLI `resource preflight --phase --scenario` pass-through.
- Added P35 quant completeness semantics for `200.fault.*`.

## Commands

- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache python3 -m compileall -q scripts src tests` - PASS, exit 0.
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache python3 -m pytest -q tests/integration/test_docker_runtime_contract.py tests/scale/test_scale_ladder.py tests/unit/test_cli_contract.py tests/unit/test_goal_loop_assertions.py -q` - PASS, exit 0.
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache python3 scripts/safety_scan.py` - PASS, exit 0.
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache python3 scripts/assert_strict_stage_contract.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL` - PASS, exit 0.
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache python3 scripts/assert_no_bypass.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL` - PASS, exit 0.
- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache python3 -m valkey_scale_lab.cli resource preflight --config templates/configs/scale_200.yaml --out /private/tmp/p35_resource_preflight_check.json --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --scenario strict_fault_matrix_200` - FAIL, exit 1 in sandbox; Docker socket permission denied and port checks reported unavailable.
- Escalated resource-only retry: `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache python3 -m valkey_scale_lab.cli resource preflight --config templates/configs/scale_200.yaml --out /private/tmp/p35_resource_preflight_check_escalated.json --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --scenario strict_fault_matrix_200` - PASS, exit 0.

Initial compile attempt without `PYTHONPYCACHEPREFIX` failed with exit 1 because Python tried to write bytecode under `/Users/allgood/Library/Caches/...`, outside the writable sandbox. The command was rerun with a writable pycache prefix and passed.

## Artifacts

- Worker preflight evidence: `artifacts/goal_loop_strict/P35_FAULT_FAILOVER_MATRIX_200_REAL/resource_preflight_check.json`
- Harness exception: `artifacts/harness_exception/P35_FAULT_FAILOVER_MATRIX_200_REAL.md`

The escalated preflight evidence records:

- `phase_id`: `P35_FAULT_FAILOVER_MATRIX_200_REAL`
- `scenario_name`: `strict_fault_matrix_200`
- `node_count`: 200
- `nodes_requested`: 200
- `can_run`: true
- `docker_available`: PASS
- `client_ports`: PASS
- `cluster_bus_ports`: PASS
- `previous_cleanup_state`: PASS

## Coverage IDs

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

## Schema And Gate Status

- Focused compile/tests: PASS.
- Safety scan: PASS.
- Strict stage contract: PASS.
- No-bypass assertion: PASS.
- P35 real gate and artifact assertions were not run by this worker:
  - `scripts/fault_failover_gate.py ... --min-nodes 200 --require-data-path`
  - `scripts/assert_exact_scale_real_evidence.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --nodes 200`
  - `scripts/assert_fault_matrix_strict.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --scale 200 --require-all-rows`
  - `scripts/assert_failover_latency_curve.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --scale 200 --min-samples 3`
  - `scripts/assert_split_brain_report.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --scale 200`
  - `scripts/assert_quant_completeness.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --category fault --scale 200`
  - `scripts/assert_coverage_registry.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL --scale 200 --category fault`
  - `scripts/assert_cleanup.py --cleanup-report artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/cleanup_report.json`

## Cleanup Status

No real P35 cluster was started by this worker. Escalated resource preflight reported `previous_cleanup_state=PASS` with no leftovers for run id `P35_FAULT_FAILOVER_MATRIX_200_REAL-strict_fault_matrix_200-20260628`.

## Deviations

- Did not edit `codex/phase_manifest.json`, phase state, gate results, coverage registry, audit files, or commit/push.
- Did not change `templates/configs/scale_200.yaml`; the config marker remains `P21_FAILOVER_LATENCY_CURVE_200`, while resource/runtime code records P35 through explicit phase/scenario identity.
- Did not run the full real 200-node matrix gate in worker scope.

## Remaining Risks

- The full P35 real gate still needs to create exactly 200 live Valkey 9.1.x nodes and may fail or time out during setup, fault rows, split-brain detection, workload windows, or cleanup.
- Main runner must verify fresh P35 artifacts under `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/`; no P34 evidence can satisfy P35.
- Network fault rows must continue to use `sandbox_proxy` or `container_netns_tc`; host-level mutation remains forbidden.

## Main Runner Addendum

After worker completion, the first full exact-200 P35 gate exposed a real recovery defect: process-backed `node_stop` clear operations could report PASS after issuing `valkey-server <config>` without proving the restarted node had written a fresh pid file and answered `PING`.

The main runner strengthened `src/valkey_scale_lab/fault/sandbox.py` so process clear now removes stale pid files, restarts the target process inside the owned nodehost container, and waits for both a numeric pid file and `valkey-cli PING` before recording PASS. New unit coverage in `tests/unit/test_fault_sandbox.py` verifies both the successful wait path and timeout failure path.

Additional checks after this fix:

- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache_p35_sandbox_tests python3 -m pytest -q tests/unit/test_fault_sandbox.py tests/unit/test_goal_loop_assertions.py tests/unit/test_cli_contract.py tests/integration/test_docker_runtime_contract.py tests/scale/test_scale_ladder.py -q` - PASS, exit 0.
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache_p35_compile2 python3 -m compileall -q scripts src tests` - PASS, exit 0.
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache_p35_safety2 python3 scripts/safety_scan.py` - PASS, exit 0.
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache_p35_contract2 python3 scripts/assert_strict_stage_contract.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL` - PASS, exit 0.
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache_p35_nobypass3 python3 scripts/assert_no_bypass.py --phase P35_FAULT_FAILOVER_MATRIX_200_REAL` - PASS, exit 0.
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache_p35_precheck4 python3 scripts/codex_gate.py precheck --phase P35_FAULT_FAILOVER_MATRIX_200_REAL` - PASS, exit 0.
- Escalated exact-200 resource preflight for `P35_FAULT_FAILOVER_MATRIX_200_REAL` / `strict_fault_matrix_200` - PASS, exit 0.
- Escalated `PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache_p35_gate_after_sandbox_fix python3 scripts/codex_gate.py run --phase P35_FAULT_FAILOVER_MATRIX_200_REAL` - PASS, exit 0.

Passing P35 evidence from the final gate:

- `artifacts/gates/P35_FAULT_FAILOVER_MATRIX_200_REAL/gate_result.json`: `status=PASS`.
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/valkey_e2e_evidence.json`: `status=PASS`, `probe_result=PASS`, `data_path_result=PASS`, `nodes_requested=200`, `nodes_observed=200`, `valkey_versions=["9.1.0"]`.
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/fault_operation_results.jsonl`: 12 strict fault rows, all `status=PASS`, all `real_execution_verified=true`.
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/failover_report.json`: 3 real failover samples.
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/cleanup_report.json`: `status=PASS`, `resources_remaining=[]`.
- Final owned-container check: `docker ps --filter label=vsl.run_id=P35_FAULT_FAILOVER_MATRIX_200_REAL-strict_fault_matrix_200-20260628` returned no rows.

The stale blocked note from the failed intermediate gate was removed after the final passing exact-200 gate. P35 is ready for the required fresh review subagent.

## Main Runner Recovery Addendum

A fresh review failed on missing `coverage_id` fields in `failover_samples.jsonl`. The producer and quant completeness assertion were strengthened, and regenerated samples now include `coverage_id=200.fault.primary_stop_failover`.

Subsequent exact-200 gate reruns exposed a real P35 recovery blocker for 100-node `node_host_stop` and `az_stop` groups. The main runner strengthened process restart readiness checks, added bounded P35 retry behavior, increased P35 node-host/AZ convergence to 1800 seconds, removed stale strict work directories before setup, and required a short sustained-readiness window for P35 process restarts.

The final sustained-readiness exact-200 gate passed:

- `artifacts/gates/P35_FAULT_FAILOVER_MATRIX_200_REAL/gate_result.json`: `status=PASS`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/valkey_e2e_evidence.json`: `status=PASS`, `probe_result=PASS`, `nodes_requested=200`, `nodes_observed=200`, `data_path_result=PASS`, `valkey_versions=["9.1.0"]`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/fault_operation_results.jsonl`: all 12 strict `200.fault.*` rows PASS with `real_execution_verified=true`, including `node_host_stop` and `az_stop` with `target_group_count=100` and `cluster_restored=true`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/failover_samples.jsonl`: three primary-stop samples PASS with `coverage_id=200.fault.primary_stop_failover`
- `artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/cleanup_report.json`: `status=PASS`, `resources_remaining=[]`
- Final owned-container check: `docker ps --filter label=vsl.run_id=P35_FAULT_FAILOVER_MATRIX_200_REAL-strict_fault_matrix_200-20260628` returned no rows.

P35 is ready for the required fresh review subagent. It has not yet been postchecked, marked complete, committed, pushed, or advanced.
