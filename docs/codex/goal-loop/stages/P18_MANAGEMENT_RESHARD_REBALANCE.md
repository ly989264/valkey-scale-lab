# P18_MANAGEMENT_RESHARD_REBALANCE — Management Matrix: Reshard and Rebalance

## Stage objective

Implement and quantify real slot movement and rebalance behavior.

## Required operation rows

```text
reshard_slot_range on 6 nodes
reshard_slot_range on 10 nodes
reshard_with_keys on 6 nodes
reshard_with_keys on 10 nodes
rebalance_after_imbalance on 6 nodes
rebalance_after_imbalance on 10 nodes
```

## Worker implementation requirements

Implement:

- source/target primary selection;
- explicit slot range movement;
- test-key generation in moved slots;
- key readability and writability verification after movement;
- slot balance metric before/after;
- rebalance operation that reduces measurable imbalance;
- workload windows and redirect/error counting;
- topology snapshots and command log.

## Required artifacts

```text
management_ops_matrix.json
management_operation_results.jsonl
management_workload_impact.json
management_topology_snapshots.jsonl
management_command_log.jsonl
reshard_slot_movements.jsonl
rebalance_summary.json
events.jsonl
metrics_timeseries.jsonl
quant_summary.json
```

## Required assertions

- moved slot count is greater than zero;
- moved-slot keys remain readable;
- cluster slot coverage is complete after convergence;
- rebalance reduces declared imbalance;
- workload impact is measured for every row;
- cleanup passes.

## Review focus

Reject no-op rebalance as a substitute for an imbalance-reducing row. Reject reshard evidence that does not verify key movement/data path.
