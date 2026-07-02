# DESIGN_BRIEF — P17_MANAGEMENT_REMOVE_NODE

## Objective

Implement and quantify real Valkey remove-node management operations for the required P17 rows: `remove_replica`, `remove_primary_drained`, and `remove_failed_node` at both 6 and 10 nodes. The stage must produce schema-validated management, telemetry, workload-impact, topology, command-log, real-evidence, and cleanup artifacts. A 10-node resource or runtime failure blocks the stage; it must not be downshifted or marked PASS.

## Repository findings

- `src/valkey_scale_lab/runtime/docker_runtime.py` already owns deterministic Docker scenario creation, cleanup by labels, cluster meet/add-slots/replicate helpers, node-level command helpers, process-runtime helpers for 10+ nodes, and P16 telemetry artifact generation.
- `create_scenario()` currently accepts P16 `goal_loop_quant_telemetry` but does not accept P17 `management_remove_node`; `_scenario_node_count_allowed()` has no P17 entry.
- P17's manifest gate currently runs only `templates/configs/local_az_3x2.yaml` with `--min-nodes 6`. This is insufficient for the stage document because it does not force 10-node execution. The harness should be strengthened in P17, not treated as satisfied.
- `templates/configs/local_az_3x2.yaml` gives 6 nodes; `templates/configs/scale_10.yaml` gives 10 nodes. Both are within P17's max-node cap.
- Existing cluster helpers support `CLUSTER MEET`, `ADDSLOTS`, `REPLICATE`, `MYID`, `INFO`, `CLUSTER INFO`, and `CLUSTER NODES`. I found no existing safe remove-node workflow for `CLUSTER FORGET`, slot drain/reassignment, or failed-node metadata cleanup.
- `scripts/valkey_probe_lib.py` already independently probes live endpoints, parses `CLUSTER INFO`/`CLUSTER NODES`, follows MOVED/ASK for data-path checks, and waits for cluster OK. It can help verify topology from wrapper code but does not implement management operations.
- `src/valkey_scale_lab/fault/sandbox.py` supports `node_stop` through owned container stop or owned process `kill -TERM <pid>` inside the nodehost container, with clear/restart support. This is a suitable P17 safety base for `remove_failed_node`, but removal should not mutate host networking.
- P16 added reusable `TelemetryRun`, `write_jsonl`, workload metrics, and `run_windowed_workload()`. P17 should reuse or lightly extend these rather than inventing a parallel telemetry format.
- `scripts/assert_management_ops_coverage.py` currently requires operation names only, not the exact P17 `(operation_name, node_count)` pairs. It also does not verify removed-node absence, slot coverage, or cleanup details. It must be strengthened for P17.
- `scripts/assert_workload_impact.py` accepts `management_workload_impact.json` and requires canonical window metrics. This can validate a P17 aggregate impact artifact if the worker writes the same metric shape as P16 workload windows.
- Schemas for `management_ops_matrix`, `management_operation_result`, `topology_snapshot`, `command_log_entry`, and `workload_impact_report` already exist and are permissive enough for P17. Tightening can mostly live in assertion scripts to keep scope bounded.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `src/valkey_scale_lab/runtime/docker_runtime.py` | modify | Add P17 scenario allow-list, 6/10 node-count policy, P17 management runner, topology snapshots, command logs, operation result rows, P17 phase/quant summaries, and common telemetry/workload artifacts. |
| `src/valkey_scale_lab/metrics/__init__.py` | possible small modify | Reuse P16 helpers; add only generic helpers needed for operation timing/missing-field encoding if avoiding duplication in runtime. |
| `src/valkey_scale_lab/workload/__init__.py` | possible small modify | Allow operation-window workload refs or per-operation key prefixes if needed; preserve P16 behavior. |
| `src/valkey_scale_lab/fault/sandbox.py` | possible small modify | Only if `node_stop` clear/removal evidence needs a reusable primitive; do not broaden to host-level controls. |
| `scripts/valkey_e2e_gate.py` | modify | Ensure P17 real evidence covers both 6 and 10 nodes, or add explicit P17 artifact/coverage checks after setup before cleanup. |
| `scripts/assert_management_ops_coverage.py` | strengthen | Require all six P17 rows: each operation at node counts 6 and 10; reject fake PASS, missing timing, missing workload refs, absent removed-node proof, incomplete slot coverage, or unverified cleanup. |
| `scripts/assert_quant_artifacts.py` | possible strengthen | Add P17 real-stage semantic checks if common validation does not require event/metric phase consistency and non-empty P17 rows. |
| `codex/phase_manifest.json` | strengthen | Add a 10-node real gate or replace the single gate with a P17 wrapper that runs and aggregates both 6- and 10-node evidence. Do not remove existing safety/common gates. |
| `codex/gate_lock.json` | update | Refresh only after harness-control script/schema changes, preserving lock coverage. |
| `tests/unit/test_goal_loop_assertions.py` | add tests | Cover P17 management assertion exact row requirements and fail-closed behavior. |
| `tests/integration/test_docker_runtime_contract.py` | add tests | Cover P17 scenario allow-list for 6 and 10 nodes and helper behavior with mocked commands. |
| `tests/fault/test_sandbox_fault.py` | possible add tests | If failed-node removal uses new fault evidence fields, cover owned process/container stop semantics. |
| `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/*` | generated | Produce required real stage artifacts through the gate, not by hand. |

## Implementation plan

1. Strengthen the P17 gate shape before relying on it. Preferred small path: make `scripts/valkey_e2e_gate.py` handle P17 `management_remove_node` as a two-rung wrapper using `local_az_3x2.yaml` and `scale_10.yaml`, or add a second manifest real gate plus deterministic aggregation that cannot overwrite or omit either rung. The final artifacts in `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/` must contain rows for both node counts.
2. Add P17 to `create_scenario()` and `_scenario_node_count_allowed()` for `management_remove_node` at 6 and 10 nodes only. For 10 nodes, prefer the existing process-runtime path if needed for resource efficiency; otherwise use the existing Docker container path if it is already reliable for 10 nodes. This runtime choice is `待验证`.
3. Implement a small P17-only management runner after cluster creation. For each configured node count, run exactly the required operations on fresh clusters or clearly isolated sub-runs so earlier removals do not corrupt later rows.
4. For `remove_replica`, select a live replica, record before topology, run `CLUSTER FORGET <replica_node_id>` from all surviving nodes after stopping or disconnecting the target as required by Valkey semantics, wait for cluster OK with expected known-node count reduced by one, verify full slot coverage and absence of the removed node from converged views, then remove/stop the owned target resource and record cleanup evidence.
5. For `remove_primary_drained`, select a primary with a replica. Use a safe path only: either drain/move every slot to another primary before `CLUSTER FORGET`, or perform a controlled failover/replacement path documented in the operation command log. The minimal likely path is `CLUSTER FAILOVER` on the target's replica, wait for promotion and full slot coverage, then forget/stop the old primary from surviving nodes. Direct kill plus success is forbidden. Slot-drain details are `待验证` against live Valkey 9.1.0.
6. For `remove_failed_node`, apply an owned `node_stop` fault or equivalent owned runtime control to the target, verify the failure is visible in cluster probes, run metadata cleanup via `CLUSTER FORGET` from surviving nodes, wait for convergence or record a real `FAIL`, and ensure cleanup leaves no owned resources. If the old process/container is intentionally removed, do not restart it silently as part of the operation row.
7. For every operation row, capture timings: start/end wall ms, command duration, convergence duration, cleanup duration, before/after cluster state, before/after slot counts, slots/keys/bytes moved or `MISSING` with reason, errors by type, and `real_execution_verified=true` only after live probes and data path pass.
8. Capture topology snapshots as JSONL before/during/after each operation using `CLUSTER INFO` and `CLUSTER NODES`. Include removed node id/logical id, role counts, known-node counts, slot coverage, and whether the target is absent from survivor views.
9. Capture command log JSONL entries for each Valkey/runtime/fault command with redacted deterministic argv, target logical id, started/ended unix ms, status, stdout/stderr tail, and reason on failure.
10. Reuse P16 `TelemetryRun` and `run_windowed_workload()` to produce common `events.jsonl`, `metrics_timeseries.jsonl`, and `workload_windows.json`. The P17 `event` window must correspond to the actual management operation period, not the P16 smoke-only event window.
11. Write `management_ops_matrix.json`, `management_operation_results.jsonl`, `management_workload_impact.json`, `management_topology_snapshots.jsonl`, and `management_command_log.jsonl`. `quant_summary.json` should reference all P17 artifacts and set `management_runtime_claimed=true`, `fault_runtime_claimed=false` except for the owned fault control used inside `remove_failed_node` if represented as management-support evidence rather than a fault-stage claim.
12. Keep P18 reshard/rebalance out of scope except for the minimum slot reassignment required to safely remove a primary.

## Harness, schema, and gate plan

- Required common commands remain:
  - `python3 scripts/codex_gate.py precheck --phase P17_MANAGEMENT_REMOVE_NODE`
  - `python3 scripts/safety_scan.py`
  - `python3 -m compileall -q scripts src`
  - `python3 -m pytest -q tests/unit tests/integration`
  - `python3 scripts/assert_goal_loop_stage.py --phase P17_MANAGEMENT_REMOVE_NODE`
  - `python3 scripts/codex_gate.py run --phase P17_MANAGEMENT_REMOVE_NODE`
  - `python3 scripts/assert_quant_artifacts.py --phase P17_MANAGEMENT_REMOVE_NODE`
  - `python3 scripts/assert_management_ops_coverage.py --phase P17_MANAGEMENT_REMOVE_NODE`
  - `python3 scripts/assert_workload_impact.py --phase P17_MANAGEMENT_REMOVE_NODE`
  - `python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/cleanup_report.json`
- Strengthen P17 real evidence so the stage cannot pass with only the current 6-node gate. Acceptable designs:
  - one P17-specific wrapper path in `scripts/valkey_e2e_gate.py` that internally runs 6-node and 10-node management sub-runs and emits one aggregate `valkey_e2e_evidence.json`; or
  - two explicit real gates plus an aggregator/assertion that merges and validates both node counts before the manifest gate passes.
- Strengthen `scripts/assert_management_ops_coverage.py` to require exact pairs: `remove_replica/6`, `remove_replica/10`, `remove_primary_drained/6`, `remove_primary_drained/10`, `remove_failed_node/6`, `remove_failed_node/10`.
- The management assertion should fail if any required pair has `operation_status != PASS`, `real_execution_verified is not true`, missing timing, missing workload ref, missing target node id, missing topology refs, target still present in survivor views, `slots_after != 16384`, or cleanup evidence is absent.
- Schema files can remain mostly permissive if assertions enforce P17 semantics. Tighten schemas only if needed and only in a backward-compatible/fail-closed way.
- Any harness file change requires a transparent `codex/gate_lock.json` refresh and tests showing the change strengthens coverage rather than bypassing it.

## Test plan

- Unit tests for `assert_management_ops_coverage.py`:
  - minimal valid six-row P17 artifacts pass;
  - missing 10-node row fails;
  - PASS without `real_execution_verified=true` fails;
  - PASS with target still present or `slots_after != 16384` fails;
  - `SKIPPED_WITH_REASON` for a required P17 row fails unless the stage is explicitly blocked rather than passed.
- Integration tests in `tests/integration/test_docker_runtime_contract.py`:
  - P17 `management_remove_node` allows 6 and 10 nodes and rejects other counts;
  - topology/command/result helper functions encode `MISSING` with reasons;
  - P16 scenario behavior remains unchanged.
- Fault tests if touched:
  - `node_stop` remains scoped to owned container or owned process PID;
  - failed-node removal does not call host network/firewall commands.
- Real gate:
  - run the strengthened P17 real wrapper for both 6 and 10 nodes with Valkey 9.1.x evidence and cleanup.
- Final stage gates:
  - `python3 scripts/codex_gate.py run --phase P17_MANAGEMENT_REMOVE_NODE`
  - post-worker fresh review, then postcheck/mark-complete only after review PASS.

## Required artifacts

- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/phase_summary.json`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/valkey_e2e_evidence.json`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/cleanup_report.json`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/events.jsonl`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/metrics_timeseries.jsonl`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/workload_windows.json`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/quant_summary.json`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_ops_matrix.json`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_operation_results.jsonl`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_workload_impact.json`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_topology_snapshots.jsonl`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_command_log.jsonl`
- Gate logs under `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/`

## Safety considerations

- Do not use `sudo`, host firewall, host routing, PF, nftables, iptables, host interface changes, or unrelated process kills.
- Failed-node removal must use only owned Docker containers, owned logical processes inside owned nodehost containers, or already-approved project runtime controls.
- Primary removal must not be represented as a kill plus fake convergence. It must drain slots or use a controlled promotion/replacement path with topology proof.
- Each removed/stopped resource must have deterministic ownership labels, state references, and cleanup evidence.
- Any missing measurements must be `MISSING`, `SKIPPED_WITH_REASON`, or `UNSUPPORTED_WITH_REASON` with reasons. Do not use nulls, zero placeholders, or omissions for required metrics.
- P17 remains capped at 10 nodes. Do not change global defaults, P14, or the 200-node exception logic.

## Resource considerations

- P17 requires real 6-node and 10-node execution. If Docker, image availability, ports, memory, disk, or CPU block 10 nodes, the stage is blocked and must write `BLOCKED.md`; it must not pass with only 6 nodes.
- `local_az_3x2.yaml` uses ports 7100-7105 and bus ports 17100-17105. `scale_10.yaml` uses ports 7200-7209 and bus ports 17200-17209.
- Running six operation rows on fresh clusters may mean up to six sequential real sub-runs. To reduce resource pressure, the worker can run one fresh 6-node cluster per operation type and one fresh 10-node cluster per operation type, or reuse a cluster only when isolation and artifact clarity remain strong. This choice is `待验证`.
- Process-runtime reuse for 10 nodes may reduce Docker container count but requires careful failed-node process cleanup; container-per-node may be simpler but heavier. This is `待验证`.

## `待验证`

- Whether Valkey 9.1.0 permits the intended primary-removal path via replica `CLUSTER FAILOVER` followed by `CLUSTER FORGET`, and the exact wait conditions needed for full slot coverage.
- Whether slot drain via direct `CLUSTER SETSLOT`/`MIGRATE` is necessary for `remove_primary_drained`, or whether controlled failover is accepted as the documented safe replacement path for P17.
- Whether `CLUSTER FORGET` must be issued to every survivor, only primaries, or a representative set for stable convergence in 6- and 10-node clusters.
- Whether a removed replica should be stopped before or after `CLUSTER FORGET` to avoid gossip reintroduction.
- Whether 10-node P17 should use one-container-per-node or the existing docker-process runtime.
- Whether the generic `scripts/valkey_e2e_gate.py` is the right place for two-rung P17 aggregation or whether a narrow P17 wrapper is cleaner.
- Real 10-node execution, timing, and cleanup on the current machine.

## Worker instructions

- Implement only this stage.
- Do not commit.
- Do not weaken harness or safety rules.
- First strengthen the P17 gate/assertion gap so 10-node evidence is required.
- Keep P18 reshard/rebalance and P19 rolling restart out of scope except for safe primary-removal mechanics needed by P17.
- Use real Valkey operations and live probes for PASS rows; if a required row cannot run safely, block/fail the stage rather than inventing success.
