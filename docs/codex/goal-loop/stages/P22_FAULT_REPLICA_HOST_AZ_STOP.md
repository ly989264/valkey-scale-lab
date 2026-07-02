# P22_FAULT_REPLICA_HOST_AZ_STOP — Replica, Node-Host, and AZ Stop Faults

## Stage objective

Implement and quantify non-primary-stop process/container fault scenarios.

## Required fault rows

```text
replica_stop
node_host_stop
az_stop
```

Run at the largest safe existing scale up to 100 nodes. At minimum, include real 6/10-node evidence and at least one 30+ node evidence row if resource preflight passes. If the manifest sets stricter node counts, the stricter manifest wins.

## Worker implementation requirements

Implement:

- target selector for replica, logical host, and virtual AZ;
- project-owned stop/restore lifecycle;
- per-target topology and role impact summary;
- workload windows during fault/recovery;
- recovery timing;
- cleanup verification.

## Required artifacts

```text
fault_matrix_report.json
fault_results.jsonl
fault_topology_snapshots.jsonl
workload_impact_report.json
events.jsonl
metrics_timeseries.jsonl
quant_summary.json
```

## Required assertions

- replica stop does not claim promotion success unless promotion unexpectedly happens and is reported as impact;
- host stop targets only nodes assigned to that logical host;
- AZ stop targets only nodes assigned to that virtual AZ;
- workload impact exists for every row;
- cleanup passes.

## Review focus

Confirm host/AZ faults are not physical host mutations. Confirm fault targets are derived from plan topology.
