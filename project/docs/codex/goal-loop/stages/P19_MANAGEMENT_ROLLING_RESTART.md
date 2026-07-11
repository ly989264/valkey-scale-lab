# P19_MANAGEMENT_ROLLING_RESTART — Management Matrix: Rolling Restart

## Stage objective

Implement and quantify rolling restart with health gates between node restarts.

## Required operation rows

```text
rolling_restart_replica_first on 6 nodes
rolling_restart_replica_first on 10 nodes
rolling_restart_primary_safe on 6 nodes
rolling_restart_primary_safe on 10 nodes
```

## Worker implementation requirements

Implement:

- deterministic restart order;
- one-node-at-a-time or explicitly safe batch behavior;
- per-node restart events;
- health gate before next node;
- primary restart safe path with promotion/unavailability measurement if failover occurs;
- workload windows during each restart and whole operation;
- cleanup and post-restart topology verification.

## Required artifacts

```text
management_ops_matrix.json
rolling_restart_plan.json
rolling_restart_results.jsonl
management_workload_impact.json
management_topology_snapshots.jsonl
events.jsonl
metrics_timeseries.jsonl
quant_summary.json
```

## Required assertions

- restart order is recorded and matches execution;
- no next node restarts before previous health gate passes;
- cluster recovers after each restart;
- workload impact is measured;
- cleanup passes.

## Review focus

Reject all-at-once restart as rolling restart. Reject a restart row without inter-node health gates.
