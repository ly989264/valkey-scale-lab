# C06 Setup telemetry contract

For any `REAL_EXACT_SCALE` setup claim, the following core metrics must be numeric:

```text
nodehost_start_ms
node_config_generate_ms
node_config_distribute_ms
process_start_ms
process_ready_wait_ms
cluster_meet_ms
cluster_slots_assign_ms
replica_replicate_ms
cluster_convergence_probe_ms
full_cluster_probe_ms
cleanup_ms
total_setup_ms
```

`SKIPPED_WITH_REASON` is allowed for fixture, dry-run, blocked, and small smoke only. It is not allowed for exact-scale PASS.

Per-node samples must include node id, role, nodehost id, pid, ready metric, cluster state, and known nodes, or the claim is blocked/fail.
