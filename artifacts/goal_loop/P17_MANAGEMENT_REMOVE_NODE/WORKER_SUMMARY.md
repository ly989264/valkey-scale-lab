# WORKER_SUMMARY — P17_MANAGEMENT_REMOVE_NODE

## Worker role

This P17 worker-summary agent did not implement code. The main agent had already implemented the P17 changes and generated the gate/artifact outputs. This worker read the required stage context, inspected the current diff and generated evidence, and is summarizing/validating the completed work for review.

Requested read paths `docs/codex/CODEX_GOAL_LOOP_START.md` and `docs/codex/goal-loop/STAGE_JOURNAL.md` were not present at those exact locations. The corresponding repository files were found and read as `CODEX_GOAL_LOOP_START.md` and `artifacts/goal_loop/STAGE_JOURNAL.md`.

## Implementation summary

The main-agent implementation adds P17 `management_remove_node` runtime support in `src/valkey_scale_lab/runtime/docker_runtime.py`. The new runtime path emits the P17 management artifacts and executes the six required remove-node rows:

- `remove_replica` on 6 and 10 nodes.
- `remove_primary_drained` on 6 and 10 nodes.
- `remove_failed_node` on 6 and 10 nodes.

The implementation records operation timings, command logs, workload windows, topology snapshots, result rows, cleanup summaries, and quantification artifacts. Safe paths reflected in the produced result rows are:

- `remove_replica`: stop owned replica container, issue `CLUSTER FORGET` from survivors, verify convergence.
- `remove_primary_drained`: run controlled replica `CLUSTER FAILOVER TAKEOVER`, then forget and remove the old primary.
- `remove_failed_node`: stop an owned replica container to represent the failed node, forget it from survivors, and verify cleanup.

The management assertion was strengthened so P17 requires exact operation/node-count pairs and rejects missing 10-node coverage, fake PASS rows, missing timing, missing removed-node proof, incomplete slot coverage, missing cleanup evidence, and missing target/removed node identifiers.
After worker-summary review flagged one stale-row risk, the main agent added a clean-cluster precondition before every P17 operation and strengthened the assertion to require `cluster_state_before=ok`, `slots_before=16384`, `cluster_state_after=ok`, and `slots_after=16384`.

## Files changed

- `src/valkey_scale_lab/runtime/docker_runtime.py`: adds P17 artifact generation, six-row management operation execution, sidecar 6-node/10-node runs, topology snapshots, command logging, workload aggregation, quant summary, and cleanup summaries.
- `scripts/assert_management_ops_coverage.py`: strengthens P17 coverage from operation-name-only checks to exact `(operation_name, node_count)` row checks plus semantic PASS requirements.
- `tests/unit/test_goal_loop_assertions.py`: adds unit coverage showing missing P17 10-node rows fail and the complete six-row matrix passes.
- `codex/gate_lock.json`: refreshes the hash for the strengthened management assertion.
- `artifacts/harness_exception/P17_MANAGEMENT_REMOVE_NODE.md`: documents the harness defect and strengthening patch.
- Generated P17 gate/phase artifacts under `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/` and `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/`.

## Real-gate results

`artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/gate_result.json` reports overall `PASS`.

Required gates passed:

- harness precheck.
- safety static scan.
- scripts/source compile.
- unit and integration tests.
- goal-loop stage assertion.
- real Valkey e2e gate.
- quant artifact assertion.
- management ops assertion.
- workload impact assertion.
- cleanup report check.

The real Valkey gate used `scripts/valkey_e2e_gate.py` for `P17_MANAGEMENT_REMOVE_NODE` with scenario `management_remove_node`, observed 6 nodes, `cluster_state_observed=ok`, `data_path_result=PASS`, and Valkey version `9.1.0`.

Review note: the outer e2e wrapper probes the main 6-node cluster. The 10-node P17 evidence is produced by the runtime's P17 sidecar operation rows and enforced by `scripts/assert_management_ops_coverage.py`; the reviewer should confirm this satisfies the stage's real 10-node execution requirement.

## Artifact evidence summary

`artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_operation_results.jsonl` contains all six required rows with `operation_status=PASS`, `real_execution_verified=true`, `cluster_state_before=ok`, `slots_before=16384`, `cluster_state_after=ok`, `removed_node_absent=true`, `slots_after=16384`, expected node-count reduction, zero classified command/cleanup errors, and `sidecar_cleanup_status=PASS`.

Observed row highlights:

- `remove_replica-06`: 6 to 5 nodes, replica removed, wall time about 8.9s.
- `remove_replica-10`: 10 to 9 nodes, replica removed, wall time about 13.1s.
- `remove_primary_drained-06`: 6 to 5 nodes, old primary removed after takeover, wall time about 7.9s.
- `remove_primary_drained-10`: 10 to 9 nodes, old primary removed after takeover, wall time about 15.4s.
- `remove_failed_node-06`: 6 to 5 nodes, failed replica removed, wall time about 9.1s.
- `remove_failed_node-10`: 10 to 9 nodes, failed replica removed, wall time about 13.3s.

`quant_summary.json` reports `PASS`, 6 operations, 3 six-node rows, 3 ten-node rows, 86 events, 720 metric rows, 36 workload windows, 24 topology snapshots, and 56 command-log rows.

`management_workload_impact.json` reports 36 operation windows with aggregate baseline/event/recovery metrics. The aggregate event window shows 24 ok operations, 0 errors, and 0.0 error rate.

`cleanup_report.json` reports `PASS` with `resources_remaining=[]`. Per-operation sidecar cleanup summaries in `quant_summary.json` also report `PASS` and no remaining resources.

## Harness exception summary

`artifacts/harness_exception/P17_MANAGEMENT_REMOVE_NODE.md` records a real harness defect: the prior management coverage assertion only required P17 operation names and could pass a partial matrix with no 10-node rows. The patch strengthens the assertion to require all six exact P17 rows and additional semantic evidence for PASS rows. This appears to preserve and strengthen the original requirement rather than weakening the harness.

## Risks and notes for review

- The main manifest real-Valkey wrapper still invokes the scenario with `templates/configs/local_az_3x2.yaml` and `--min-nodes 6`; 10-node evidence is generated inside the P17 runtime sidecar rows, not as a separate outer wrapper probe.
- `_scenario_node_count_allowed()` for P17 allows the main scenario at 6 nodes, while the 10-node runs are internal P17 sidecars based on `templates/configs/scale_10.yaml`.
- A previous gate run exposed that one primary-drained row could start before all node views converged; the code and assertion now reject that case, and the latest gate artifacts show all six rows start from `cluster_state_before=ok` and `slots_before=16384`.
- The failed-node path uses owned container stop/removal for a replica, not host network mutation. No Docker or host actions were run by this worker-summary agent.
