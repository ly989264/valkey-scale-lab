# REVIEW — P17_MANAGEMENT_REMOVE_NODE

## Decision

Decision: PASS

## Scope Reviewed

- Controlling context: `AGENTS.md`, `CODEX_START_HERE.md`, `CODEX_GOAL_LOOP_START.md`, `artifacts/goal_loop/STAGE_JOURNAL.md`, `docs/codex/goal-loop/stages/P17_MANAGEMENT_REMOVE_NODE.md`, `docs/codex/04_AUDITOR.md`, `templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md`, `artifacts/goal_loop/P17_MANAGEMENT_REMOVE_NODE/CONTEXT_RELOAD.md`, `DESIGN_BRIEF.md`, and `WORKER_SUMMARY.md`.
- Diff reviewed: `src/valkey_scale_lab/runtime/docker_runtime.py`, `scripts/assert_management_ops_coverage.py`, `tests/unit/test_goal_loop_assertions.py`, and `codex/gate_lock.json`.
- Evidence reviewed: P17 gate result/logs, management artifacts, topology snapshots, command log, workload impact, quant summary, cleanup reports, and harness exception.

## Gate Evidence

- `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/gate_result.json` status is `PASS`.
- Gate result SHA256: `e827d805256897c922efdd6cd96ff3823cd9d6c8cc3413a3250ca2a291fc0c7e`.
- All 10 listed gates passed: precheck, safety scan, compile, unit/integration tests, goal-loop assertion, real Valkey e2e, quant assertion, management ops assertion, workload impact assertion, and cleanup assertion.
- I verified stdout/stderr files referenced by `gate_result.json` exist and their SHA256 values match the gate result.
- The real e2e wrapper command is still the 6-node outer probe with `--min-nodes 6`, but the P17 runtime invoked by that wrapper generated the 6-node and 10-node sidecar management rows, and `scripts/assert_management_ops_coverage.py` now asserts the exact six required operation/node-count pairs.

## Required Row Coverage

`artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_operation_results.jsonl` contains exactly the six required P17 rows, all `PASS` and `real_execution_verified=true`:

- `remove_replica` on 6 nodes: clean before/after, 6 to 5 nodes, full slots after.
- `remove_replica` on 10 nodes: clean before/after, 10 to 9 nodes, full slots after.
- `remove_primary_drained` on 6 nodes: clean before/after, 6 to 5 nodes, full slots after.
- `remove_primary_drained` on 10 nodes: clean before/after, 10 to 9 nodes, full slots after.
- `remove_failed_node` on 6 nodes: clean before/after, 6 to 5 nodes, full slots after.
- `remove_failed_node` on 10 nodes: clean before/after, 10 to 9 nodes, full slots after.

`artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_ops_matrix.json` also lists all six rows as `PASS` with `real_execution_verified=true`. `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/quant_summary.json` reports 6 operations, 3 six-node rows, 3 ten-node rows, 24 topology snapshots, 56 command-log rows, 36 workload windows, and `status=PASS`.

## Primary Removal Safety

The primary-removal path is not a kill plus fake success. In `src/valkey_scale_lab/runtime/docker_runtime.py`, `remove_primary_drained` selects the primary's replica, runs `CLUSTER FAILOVER TAKEOVER`, waits for the replacement to report `master`, then stops/removes the old primary and issues `CLUSTER FORGET` from survivors.

The command log confirms this order for both node counts:

- `remove_primary_drained-06`: `cluster_failover_takeover` on `shard-0000-replica-00`, then owned container stop/removal of `shard-0000-primary`, plus survivor `CLUSTER FORGET` commands.
- `remove_primary_drained-10`: same takeover-first path, then old-primary stop/removal and survivor `CLUSTER FORGET` commands.

Both result rows record `safe_path=cluster_failover_takeover_then_forget_old_primary`, `removed_node_absent=true`, `cluster_state_after=ok`, and `slots_after=16384`.

## Cluster State, Workload, Cleanup, Safety

- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_topology_snapshots.jsonl` has before, during-before-command, during-after-command, and after snapshots for every row. Before and after snapshots are clean and full-slot for all six rows; after snapshots show the expected node count reduced by one.
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_workload_impact.json` and `workload_windows.json` show 36 PASS workload windows, six per operation, with event-period workload metrics and zero recorded workload errors.
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_command_log.jsonl` records owned Docker container stop/rm and Valkey `CLUSTER FORGET`/`CLUSTER FAILOVER TAKEOVER` commands. I found no host firewall, host routing, `sudo`, PF, nftables, iptables, or host-interface mutation path in the P17 diff or command log.
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/cleanup_report.json` is `PASS` with `resources_remaining=[]`; all six `sidecar_cleanup_*.json` reports are also `PASS` with empty remaining resources.
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/valkey_e2e_evidence.json` proves live Valkey `9.1.0`, cluster state `ok`, data path `PASS`, and cleanup `PASS` for the outer 6-node probe. The 10-node operation evidence is in the P17 sidecar artifacts and is enforced by the strengthened management assertion.

## Harness Exception

`artifacts/harness_exception/P17_MANAGEMENT_REMOVE_NODE.md` documents a real harness defect: the prior assertion could pass operation-name coverage without proving the 10-node half of the matrix. The patch strengthens requirements by adding exact `(operation_name, node_count)` checks and semantic PASS checks for real execution, timing, removed-node absence, clean before/after cluster state, full slot coverage, expected node-count reduction, and cleanup. This preserves and strengthens the harness rather than weakening it.

## Residual Notes

- The outer real-Valkey gate remains a 6-node wrapper probe, so P17's 10-node evidence depends on runtime-generated sidecar operation rows plus the strengthened assertion. Given the sidecar state files, result rows, command logs, topology snapshots, and management assertion gate all prove and enforce 10-node execution, this satisfies the P17 review focus.
- No source or test changes were made by this review subagent.
## Postcheck Artifact References

Gate result: `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/gate_result.json`

Gate result SHA256: `e827d805256897c922efdd6cd96ff3823cd9d6c8cc3413a3250ca2a291fc0c7e`

Required artifacts cited for postcheck:

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

