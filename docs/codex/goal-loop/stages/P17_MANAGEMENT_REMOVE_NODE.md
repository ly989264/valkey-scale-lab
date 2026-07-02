# P17_MANAGEMENT_REMOVE_NODE — Management Matrix: Remove Node

## Stage objective

Implement and quantify remove-node operations with real Valkey evidence.

## Required operation rows

```text
remove_replica on 6 nodes
remove_replica on 10 nodes
remove_primary_drained on 6 nodes
remove_primary_drained on 10 nodes
remove_failed_node on 6 nodes
remove_failed_node on 10 nodes
```

If 10-node execution is blocked by resources, the stage is blocked and must not pass.

## Worker implementation requirements

Implement:

- safe target selection for replica and primary;
- slot drain or safe replacement path for primary removal;
- failed-node removal path using project-owned fault/runtime controls;
- topology snapshots before/during/after;
- workload windows during removal;
- operation command log;
- cleanup of removed containers/processes;
- management operation result JSONL rows.

## Required artifacts

```text
management_ops_matrix.json
management_operation_results.jsonl
management_workload_impact.json
management_topology_snapshots.jsonl
management_command_log.jsonl
events.jsonl
metrics_timeseries.jsonl
quant_summary.json
```

## Required assertions

- removed node disappears from converged cluster views;
- slot coverage remains complete after safe remove operations;
- workload windows exist for every required row;
- errors are classified;
- unsupported paths cannot be marked PASS;
- cleanup verifies removed resources.

## Review focus

Confirm primary removal is not a simple `kill` plus fake success. Confirm cluster safety and workload impact were measured.
