# COMPLETION - P35_FAULT_FAILOVER_MATRIX_200_REAL

## Stage result

- Stage ID: P35_FAULT_FAILOVER_MATRIX_200_REAL
- Review path: artifacts/goal_loop_strict/P35_FAULT_FAILOVER_MATRIX_200_REAL/REVIEW.md
- Review decision: Decision: PASS
- Audit path: audit/P35_FAULT_FAILOVER_MATRIX_200_REAL/AUDIT.md
- Audit decision JSON: audit/P35_FAULT_FAILOVER_MATRIX_200_REAL/audit_decision.json
- Gate result path: artifacts/gates/P35_FAULT_FAILOVER_MATRIX_200_REAL/gate_result.json
- Gate result SHA256: c791a20aa98ffb62c3db48ec07055b32420519291e9364386b3a520be186548f

## Commands

```text
python3 scripts/codex_gate.py run --phase P35_FAULT_FAILOVER_MATRIX_200_REAL
WROTE artifacts/gates/P35_FAULT_FAILOVER_MATRIX_200_REAL/gate_result.json status=PASS

python3 scripts/codex_gate.py postcheck --phase P35_FAULT_FAILOVER_MATRIX_200_REAL
PASS postcheck P35_FAULT_FAILOVER_MATRIX_200_REAL

python3 scripts/codex_gate.py mark-complete --phase P35_FAULT_FAILOVER_MATRIX_200_REAL
PASS postcheck P35_FAULT_FAILOVER_MATRIX_200_REAL
MARKED_COMPLETE P35_FAULT_FAILOVER_MATRIX_200_REAL
```

## Commit and push

- Commit hash: stage commit containing this file
- Commit subject: P35_FAULT_FAILOVER_MATRIX_200_REAL: prove 200-node fault failover matrix
- Push result: stage commit pushed after mark-complete

## Coverage IDs completed

- 200.fault.primary_stop_failover
- 200.fault.replica_stop
- 200.fault.node_host_stop
- 200.fault.az_stop
- 200.fault.network_delay
- 200.fault.network_loss
- 200.fault.network_flap
- 200.fault.network_partition
- 200.fault.minority_partition
- 200.fault.majority_partition
- 200.fault.split_brain_window_detection
- 200.fault.fault_period_workload_impact

P35 produced exact 200-node real Valkey 9.1.0 fault/failover evidence after resource preflight passed. It emitted 12 PASS fault rows, 3 primary-stop failover samples with `coverage_id=200.fault.primary_stop_failover`, 28 events, 70 metric samples, 14 workload windows, 14 topology snapshots, 213 command-log entries, split-brain detector evidence, partition evidence, and cleanup PASS. The global strict coverage registry now records the 12 `200.fault.*` rows as `PASS`.

P35 strengthened the harness without weakening requirements: exact-200 P35 profile dispatch, sample `coverage_id` validation, clean strict work directories, bounded P35 restart retries, and sustained process-readiness checks. Network faults remained sandbox-proxy scoped and host-level network mutation remained forbidden.

## Next stage

- Next stage ID: P36_LIFECYCLE_FULL_FLOW_200_REAL
- Handoff: P36 must run the exact 200-node real lifecycle/full-flow proof as the next bounded 200-node exception, preserving resource preflight, no host network mutation, schema-complete artifacts, review/postcheck fail-closed behavior, deterministic cleanup, and no downshift below 200 nodes.
