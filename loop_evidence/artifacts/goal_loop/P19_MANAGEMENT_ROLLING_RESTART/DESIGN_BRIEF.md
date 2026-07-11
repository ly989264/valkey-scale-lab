# DESIGN_BRIEF — P19_MANAGEMENT_ROLLING_RESTART

## Objective

Implement P19 only: real Valkey rolling restart management rows for `rolling_restart_replica_first` and `rolling_restart_primary_safe` on 6-node and 10-node clusters, with deterministic one-node-at-a-time execution, inter-node health gates, workload impact measurement, rolling restart plan/result artifacts, topology/command traces, cleanup evidence, and stronger assertions that reject all-at-once restarts or rows without health gates.

## Repository findings

- `codex/phase_manifest.json` already defines P19 as automatic, real-Valkey, max 10 nodes, and requires `management_rolling_restart`, `rolling_restart_plan.json`, and `rolling_restart_results.jsonl`.
- `src/valkey_scale_lab/runtime/docker_runtime.py` currently admits P16-P18 goal-loop scenarios, but not `("P19_MANAGEMENT_ROLLING_RESTART", "management_rolling_restart")`; the wrapper gate will fail until `create_scenario()` and `_scenario_node_count_allowed()` include P19.
- P17/P18 already provide the best local pattern: bounded sidecar clusters per required row, distinct port ranges, `TelemetryRun`, canonical workload windows, JSON/JSONL artifact writers, topology snapshots, command logs, sidecar cleanup summaries, and final common artifacts.
- `scripts/assert_management_ops_coverage.py` names P19 required operations but lacks exact P19 6/10 required row enforcement and rolling-restart-specific checks.
- `schemas/artifact/rolling_restart_plan.schema.json` and `schemas/artifact/rolling_restart_result.schema.json` exist but are very loose; they do not yet require operation IDs, node counts, sequence numbers, role/order semantics, one-at-a-time/batch size, command refs, or health gate timing.
- `tests/unit/test_goal_loop_assertions.py` covers P17/P18 management assertions but has no P19 negative/positive assertion tests.
- `scripts/assert_workload_impact.py` is generic and can validate P19 aggregate workload windows if P19 writes `management_workload_impact.json` using the existing workload impact report shape.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `src/valkey_scale_lab/runtime/docker_runtime.py` | runtime implementation | Add P19 scenario admission, node-count allowance, required rows, sidecar row runner, rolling restart execution, plan/result artifact generation, workload windows, topology snapshots, command logs, quant/phase summaries. |
| `scripts/assert_management_ops_coverage.py` | harness assertion strengthening | Add exact P19 required rows and fail-closed checks for restart order, one-at-a-time execution, per-node result rows, inter-node health gates, command evidence, cluster recovery, and cleanup. |
| `schemas/artifact/rolling_restart_plan.schema.json` | schema strengthening | Require operation row identity, node count, deterministic restart order entries with sequence/role/logical ID, max concurrent restarts, and health gate policy. |
| `schemas/artifact/rolling_restart_result.schema.json` | schema strengthening | Require operation ID/name, node count, sequence, role before restart, command status/ref, health gate start/end/status, cluster state/slot coverage after gate, and workload impact ref. |
| `tests/unit/test_goal_loop_assertions.py` | unit tests | Add P19 assertion fixtures and tests for exact 6/10 rows, missing plan/results, all-at-once overlap, failed/missing health gates, and accepted valid P19 rows. |
| `codex/gate_lock.json` | harness lock update, if required by precheck | Harness-controlled schemas/scripts are expected to change; update only through the existing lock workflow if precheck reports drift. |
| `artifacts/goal_loop/P19_MANAGEMENT_ROLLING_RESTART/WORKER_SUMMARY.md` | worker artifact | Worker must summarize implementation, gates, artifacts, cleanup, and deviations. |
| `artifacts/phases/P19_MANAGEMENT_ROLLING_RESTART/*` | generated evidence | Real gate must produce required P19 machine-readable artifacts. |

## Implementation plan

1. Admit P19 into the runtime gate path.
   - Add `("P19_MANAGEMENT_ROLLING_RESTART", "management_rolling_restart")` to `create_scenario()` allowlist.
   - Add P19 6-node allowance to `_scenario_node_count_allowed()`.
   - Invoke a new `write_p19_management_rolling_restart_artifacts()` after the main 6-node setup, mirroring P17/P18.

2. Implement row-driven sidecar execution for exactly:
   - `("rolling_restart_replica_first", 6)`
   - `("rolling_restart_replica_first", 10)`
   - `("rolling_restart_primary_safe", 6)`
   - `("rolling_restart_primary_safe", 10)`
   Use port bases that do not collide with P17/P18, for example starting at `7900 + row_index * 40` after confirming availability.

3. Build deterministic rolling restart plans.
   - For `rolling_restart_replica_first`, derive live topology, sort replicas by shard/logical ID first, then primaries by shard/logical ID.
   - For `rolling_restart_primary_safe`, derive live primaries and same-shard replicas; for each original primary, use a controlled safe path before restarting it, likely `CLUSTER FAILOVER TAKEOVER` on the same-shard replica, then restart the demoted old primary one at a time. Exact command path is 待验证 against the current Valkey 9.1 cluster behavior.
   - Write `rolling_restart_plan.json` with all row plans or a top-level `operations` array plus flattened `restart_order`; avoid a single ambiguous order that hides per-row ordering.

4. Execute one node at a time.
   - Log `owned_container_restart` commands through the existing command-log pattern, using `docker restart` only on owned, label-scoped containers.
   - Record `node_restart_started`, `node_restart_completed`, `health_gate_started`, and `health_gate_passed` events for every node.
   - After each restart, wait for endpoint responsiveness, expected cluster known nodes, full slot assignment, `cluster_state=ok`, and data-path SET/GET before moving to the next node.
   - Record monotonic/wall timestamps so the assertion can prove the next restart did not begin before the previous health gate passed.

5. Measure workload impact.
   - Reuse the P17/P18 canonical window loop and workload metric helpers.
   - In the `event` window, trigger the rolling restart sequence while continuing bounded SET/GET probes around it.
   - Produce `workload_windows.json` and `management_workload_impact.json` with all six canonical windows.

6. Emit all management artifacts.
   - Write `management_ops_matrix.json`, `management_operation_results.jsonl`, `management_topology_snapshots.jsonl`, `management_command_log.jsonl`, `rolling_restart_plan.json`, `rolling_restart_results.jsonl`, `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `management_workload_impact.json`, `quant_summary.json`, and `phase_summary.json`.
   - Include sidecar cleanup summaries and artifact refs in `quant_summary.json`.

## Harness, schema, and gate plan

- Strengthen `scripts/assert_management_ops_coverage.py`:
  - Add P19 `REQUIRED_ROWS` for both operations at 6 and 10 nodes.
  - Require all four rows to have `operation_status=PASS` and `real_execution_verified=true`.
  - Validate `rolling_restart_plan.json` and `rolling_restart_results.jsonl` for P19.
  - Require each operation row to have matching plan entries and at least `node_count` restart result entries for that operation.
  - Reject `max_concurrent_restarts > 1` unless a future stage explicitly permits a safe batch; P19 design should keep it at `1`.
  - Require sequence numbers to be contiguous, command status `PASS`, `restart_completed_at_ms >= restart_started_at_ms`, `health_gate_status=PASS`, `health_gate_completed_at_ms <= next.restart_started_at_ms`, `cluster_state_after_gate=ok`, and `slots_after_gate=16384`.
  - Require `rolling_restart_replica_first` plan order to restart all replicas before any primary.
  - Require `rolling_restart_primary_safe` rows to include safe-primary fields such as `primary_safe_path`, `target_primary_node_id`, and promotion/unavailability/recovery fields, using `MISSING` plus reason only for fields that truly do not apply because no failover occurred.
- Strengthen rolling restart schemas while preserving additional properties where useful for forward compatibility.
- `scripts/assert_quant_artifacts.py` should not need P19-specific code if schemas and manifest artifacts validate, but if P19 event/window reference checks are missing, the worker may add narrowly scoped P19 semantic checks. 待验证.
- `scripts/assert_workload_impact.py` should pass if P19 writes canonical aggregate windows; no design change required unless tests reveal missing P19 metrics. 待验证.
- Keep manifest gate commands unchanged unless implementation discovers a command/path mismatch; do not weaken any required gate.

## Test plan

- Unit tests in `tests/unit/test_goal_loop_assertions.py`:
  - Valid P19 fixture with all four required rows, plan entries, result rows, one-at-a-time sequencing, passing health gates, cleanup, and workload refs must pass.
  - Missing 10-node P19 row must fail.
  - `rolling_restart_replica_first` with a primary before a replica must fail.
  - Result rows with overlapping restart/health gate timing must fail.
  - A result row with `health_gate_status != PASS` must fail.
  - A P19 row marked `PASS` without `real_execution_verified=true` must fail.
- Existing unit/integration command remains: `python3 -m pytest -q tests/unit tests/integration`.
- Stage gates expected after worker implementation:
  - `python3 scripts/codex_gate.py precheck --phase P19_MANAGEMENT_ROLLING_RESTART`
  - `python3 scripts/safety_scan.py`
  - `python3 -m compileall -q scripts src`
  - `python3 -m pytest -q tests/unit tests/integration`
  - `python3 scripts/assert_goal_loop_stage.py --phase P19_MANAGEMENT_ROLLING_RESTART`
  - `python3 scripts/valkey_e2e_gate.py --phase P19_MANAGEMENT_ROLLING_RESTART --config templates/configs/local_az_3x2.yaml --scenario management_rolling_restart --out artifacts/phases/P19_MANAGEMENT_ROLLING_RESTART/valkey_e2e_evidence.json --min-nodes 6 --require-data-path`
  - `python3 scripts/assert_quant_artifacts.py --phase P19_MANAGEMENT_ROLLING_RESTART`
  - `python3 scripts/assert_management_ops_coverage.py --phase P19_MANAGEMENT_ROLLING_RESTART`
  - `python3 scripts/assert_workload_impact.py --phase P19_MANAGEMENT_ROLLING_RESTART`
  - `python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P19_MANAGEMENT_ROLLING_RESTART/cleanup_report.json`

## Required artifacts

Under `artifacts/phases/P19_MANAGEMENT_ROLLING_RESTART/`:

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
- `rolling_restart_plan.json`
- `rolling_restart_results.jsonl`
- Sidecar state/cleanup logs may be emitted as supporting artifacts, but required evidence must be in the canonical files above.

Under `artifacts/goal_loop/P19_MANAGEMENT_ROLLING_RESTART/`:

- `CONTEXT_RELOAD.md` already exists.
- `DESIGN_BRIEF.md` from this design subagent.
- `WORKER_SUMMARY.md`, `REVIEW.md`, and later `COMPLETION.md` are required before completion.

## Safety considerations

- Restart commands must target only owned Docker containers from the current P19 run ID or sidecar run IDs.
- Do not use host firewall, routing, interfaces, PF, nftables, iptables, OS network services, or `sudo`.
- Do not kill host processes. Use Docker-owned container restart only, or Valkey cluster commands through owned containers.
- Cleanup must run for every sidecar cluster even on exceptions, following P17/P18 `try/except` cleanup style.
- Plan and result artifacts must encode failures as `FAIL`, `MISSING`, or `SKIPPED_WITH_REASON` with reasons; do not invent promotion or unavailability measurements.
- P19 must not implement P20+ failover curves or network fault rows.

## Resource considerations

- P19 remains bounded at 6 and 10 nodes. It should not start 30/50/100/200/1000-node clusters.
- The implementation pattern will likely run four sidecar clusters serially plus the wrapper’s main 6-node cluster. This is acceptable for P19 but may push the 900-second real gate timeout; keep per-window operation counts bounded as in P17/P18.
- Use deterministic, non-overlapping port ranges and `_check_ports_free()` before starting sidecar clusters.
- Docker availability, free ports, and Valkey image availability remain real blockers, not reasons to fake artifacts.

## `待验证`

- Whether `CLUSTER FAILOVER TAKEOVER` is the safest command for P19 `rolling_restart_primary_safe`, or whether normal `CLUSTER FAILOVER` is sufficient and less disruptive for Valkey 9.1.x in this topology.
- Whether a restarted primary container rejoins as a replica with stable node identity quickly enough under the existing cluster-node-timeout settings.
- Whether Docker `restart` preserves container IP and cluster bus connectivity reliably on the local Docker runtime.
- Whether the current `workload_metrics()` helper already includes every metric required by P19 workload impact assertions, including `latency_p90_ms`, `latency_p999_ms`, and detailed error counters.
- Whether `codex/gate_lock.json` requires a lock refresh after strengthening harness scripts and schemas.
- Whether aggregate `rolling_restart_plan.json` with all four row plans satisfies current schema expectations after tightening, or whether a schema shape with `operations[]` plus top-level compatibility fields is needed.

## Worker instructions

- Implement only this stage.
- Do not commit.
- Do not weaken harness or safety rules.
- Reuse P17/P18 sidecar and artifact patterns where possible.
- Keep P19 rows real; do not mark simulated or skipped rolling restart rows as PASS.
- Make assertions fail closed for all-at-once restart, missing inter-node health gates, missing 6/10 rows, and missing workload impact.
