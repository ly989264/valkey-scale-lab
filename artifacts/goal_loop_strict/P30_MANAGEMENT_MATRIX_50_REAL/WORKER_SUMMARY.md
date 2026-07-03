# WORKER_SUMMARY - P30_MANAGEMENT_MATRIX_50_REAL

## Status

Worker implementation changes were made for P30, but P30 is not complete. The real 50-node gate has not passed. The latest long-running verification attempt was interrupted at user request and exited 130.

## Changed Files

- `src/valkey_scale_lab/runtime/docker_runtime.py`
  - Registered `P30_MANAGEMENT_MATRIX_50_REAL/strict_management_matrix_50` as exact 50-node process runtime.
  - Added P30 resource preflight, cluster plan, run-state, management matrix artifact writer, coverage ledger writer, and row execution helpers.
  - Added owned process stop/start/rejoin helpers for process-runtime Valkey nodes.
  - Adjusted reshard slot selection to read live slot ownership instead of assuming static slot ranges.
- `src/valkey_scale_lab/resource.py`
  - Added optional stage/scenario identity for resource preflight and `nodes_requested`.
- `scripts/valkey_e2e_gate.py`
  - Added `nodes_requested` / `min_nodes_requested` evidence fields and P30 `run_state.json` fallback.
- `scripts/assert_management_matrix_strict.py`
  - Strengthened fail-closed checks for coverage ID, exact scale, workload refs, source refs, command refs, topology refs, and complete result rows.
- `codex/gate_lock.json`
  - Updated only the hashes for the two strengthened scripts above.
- `tests/integration/test_docker_runtime_contract.py`
  - Added P30 exact-50/process-runtime admission test.
- `artifacts/harness_exception/P30_MANAGEMENT_MATRIX_50_REAL.md`
  - Documents the harness-control changes and why they are fail-closed.

## Commands Attempted

- `python3 -m compileall -q scripts src` -> exit 1
  - Failed because Python attempted to write pyc files under `/Users/allgood/Library/Caches/...` and the sandbox denied it.
- `PYTHONPYCACHEPREFIX=/tmp/valkey-scale-lab-pyc python3 -m compileall -q scripts src` -> exit 0.
- `PYTHONPYCACHEPREFIX=/tmp/valkey-scale-lab-pyc PYTHONPATH=src python3 -m pytest -q tests/integration/test_docker_runtime_contract.py::test_p30_strict_management_matrix_is_exact_50_process_runtime` -> exit 0.
- `PYTHONPYCACHEPREFIX=/tmp/valkey-scale-lab-pyc PYTHONPATH=src python3 -m pytest -q tests/unit tests/integration` -> exit 0, 150 passed.
- `python3 scripts/safety_scan.py` -> exit 0.
- `python3 scripts/assert_strict_stage_contract.py --phase P30_MANAGEMENT_MATRIX_50_REAL` -> exit 0.
- `python3 scripts/codex_gate.py precheck --phase P30_MANAGEMENT_MATRIX_50_REAL` -> exit 1 before lock update, then exit 0 after documenting harness exception and updating the two script hashes.
- `python3 scripts/valkey_e2e_gate.py --phase P30_MANAGEMENT_MATRIX_50_REAL --scenario strict_management_matrix_50 --config templates/configs/scale_50.yaml --out artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/valkey_e2e_evidence.json --min-nodes 50 --require-data-path --setup-timeout 7200 --cleanup-timeout 600 --wait-cluster-timeout 600` -> exit 1 in sandbox.
  - Failure: `port 127.0.0.1:7400 is not available: [Errno 1] Operation not permitted`.
- Same real gate rerun with escalation -> exit 1.
  - Failure: `P30 docker command failed owned_valkey_process_stop`.
- Same real gate rerun after process-stop fix -> exit 1.
  - Failure: `ERR Target node is not a master`.
- Same real gate rerun after operation ordering fix -> exit 1.
  - Failure: `ERR I'm not the owner of hash slot 7860`.
- Same real gate rerun after live slot-selection fix -> exit 130.
  - Stopped by user request while `scripts/valkey_e2e_gate.py` was waiting on the setup subprocess.
- `docker ps --filter label=org.valkey-scale-lab.phase=P30_MANAGEMENT_MATRIX_50_REAL --format '{{.ID}} {{.Names}} {{.Status}}'` -> exit 0, no containers listed.
- `ps -ef | rg ...` -> exit 1 due sandbox: `operation not permitted`.

## Current Artifacts

Present under `artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL`:

- `resource_preflight.json`: PASS, `can_run=true`, `node_count=50`, `nodes_requested=50`.
- `cluster_plan.json`: PASS, `node_count=50`, phase/scenario set to P30.
- `run_state.json`: PASS, `node_count=50`.
- `cleanup_report.json`: PASS, `resources_remaining=[]`.
- `cleanup_report_strict_management_matrix_50.json`
- `cluster_snapshots_strict_management_matrix_50.json`
- `runtime_timing_breakdown_strict_management_matrix_50.json`
- `state_strict_management_matrix_50.json`
- setup/cleanup stdout/stderr logs.
- `valkey_e2e_evidence.json`: FAIL, `nodes_requested=50`, `nodes_observed=0`, error `setup command failed exit=1`.

Missing required P30 artifacts:

- `management_ops_matrix.json`
- `management_operation_results.jsonl`
- `management_topology_snapshots.jsonl`
- `management_command_log.jsonl`
- `management_workload_impact.json`
- `events.jsonl`
- `metrics_timeseries.jsonl`
- `workload_windows.json`
- `quant_summary.json`
- `coverage_ledger.json`
- final PASS `valkey_e2e_evidence.json`

## Coverage IDs

Targeted but not passed:

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

No coverage rows should be treated as PASS from this worker run.

## Cleanup

The latest available P30 `cleanup_report.json` is PASS with no resources remaining. A direct Docker check for P30-labeled containers returned no containers. A host `ps` check was blocked by sandbox permissions, so process absence beyond Docker ownership was not independently verified.

## Remaining Risks

- The real 50-node P30 gate has not completed after the live slot-selection fix because the user requested stopping verification.
- `management_*`, telemetry, quant, and coverage artifacts are still missing because the scenario has not completed.
- The interrupted gate exited 130; the persisted `valkey_e2e_evidence.json` still reflects an earlier setup failure and is not proof.
- P30 code changes need review carefully around process-mode remove/restore and rolling restart behavior before marking the stage complete.

## Main-Agent Rerun Command

Run the real gate again, then run the required assertions only if it exits 0:

```bash
python3 scripts/valkey_e2e_gate.py --phase P30_MANAGEMENT_MATRIX_50_REAL --scenario strict_management_matrix_50 --config templates/configs/scale_50.yaml --out artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/valkey_e2e_evidence.json --min-nodes 50 --require-data-path --setup-timeout 7200 --cleanup-timeout 600 --wait-cluster-timeout 600
python3 scripts/assert_exact_scale_real_evidence.py --phase P30_MANAGEMENT_MATRIX_50_REAL --nodes 50
python3 scripts/assert_management_matrix_strict.py --phase P30_MANAGEMENT_MATRIX_50_REAL --scale 50 --require-all-rows
python3 scripts/assert_quant_completeness.py --phase P30_MANAGEMENT_MATRIX_50_REAL --category management --scale 50
python3 scripts/assert_coverage_registry.py --phase P30_MANAGEMENT_MATRIX_50_REAL --scale 50 --category management
python3 scripts/assert_no_bypass.py --phase P30_MANAGEMENT_MATRIX_50_REAL
python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P30_MANAGEMENT_MATRIX_50_REAL/cleanup_report.json
```

Do not mark complete, commit, or push until those pass and review returns `Decision: PASS`.
