# WORKER_SUMMARY - P19_MANAGEMENT_ROLLING_RESTART

## Changed files

- `src/valkey_scale_lab/runtime/docker_runtime.py`
  - Added `P19_MANAGEMENT_ROLLING_RESTART / management_rolling_restart` scenario admission.
  - Added P19 sidecar row execution for:
    - `rolling_restart_replica_first` on 6 and 10 nodes.
    - `rolling_restart_primary_safe` on 6 and 10 nodes.
  - Emits P19 management artifacts, workload windows, topology snapshots, command logs, rolling restart plan, rolling restart results, quant summary, and phase summary.
  - Uses owned Docker `restart` only, one node at a time, with a cluster health gate after every node.
  - Uses controlled `CLUSTER FAILOVER TAKEOVER` before restarting a node that is primary in the primary-safe row.
- `scripts/assert_management_ops_coverage.py`
  - Added exact P19 6/10 required rows.
  - Validates `rolling_restart_plan.json` and `rolling_restart_results.jsonl`.
  - Rejects missing plan/results, non-PASS rows, all-at-once overlap, failed/missing health gates, plan/execution mismatch, missing command evidence, and primary-before-replica ordering for replica-first rows.
- `schemas/artifact/rolling_restart_plan.schema.json`
  - Tightened required plan shape while preserving `additionalProperties`.
- `schemas/artifact/rolling_restart_result.schema.json`
  - Tightened per-node restart result shape while preserving `additionalProperties`.
- `tests/unit/test_goal_loop_assertions.py`
  - Added focused P19 assertion tests for valid rows, missing 10-node rows, primary-before-replica order, overlapping restart/health timing, and failed health gate.

## Commands run

- `python3 -m pytest -q tests/unit/test_goal_loop_assertions.py`
  - Result: PASS, `18 passed`.
- `PYTHONPYCACHEPREFIX=/tmp/vslab-p19-pycache python3 -m compileall -q src scripts`
  - Result: PASS.
- Initial plain `python3 -m compileall -q src scripts`
  - Result: failed because Python attempted to write bytecode under `/Users/allgood/Library/Caches/...`, outside the writable sandbox. Reran successfully with `PYTHONPYCACHEPREFIX=/tmp/vslab-p19-pycache`.

## Evidence status

- Focused unit coverage and script compilation passed.
- Full Docker real gate was not run by this worker, per instruction. Main agent should run the P19 real gate and artifact assertions.

## Remaining risks

- Docker restart behavior and Valkey failover timing still require the real P19 gate to verify on this machine.
- `rolling_restart_primary_safe` records unavailability fields as `MISSING` with reasons when no read/write outage is observed or the node was not primary at restart time.
