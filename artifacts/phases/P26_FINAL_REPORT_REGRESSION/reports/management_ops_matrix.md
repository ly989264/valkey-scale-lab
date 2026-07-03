# P26 Management Operation Matrix

Generated from JSON/JSONL artifacts only. Source refs are listed in `final_report_index.json`.

| operation_name | status | node_counts | row_count | source_stage_ids | reason |
| --- | --- | --- | --- | --- | --- |
| create_cluster | PASS | 6 | 1 | P04_CLUSTER_MANAGEMENT_OPS | MISSING (MISSING) |
| meet_nodes | PASS | 6 | 1 | P04_CLUSTER_MANAGEMENT_OPS | MISSING (MISSING) |
| add_replica | PASS | 6 | 1 | P04_CLUSTER_MANAGEMENT_OPS | MISSING (MISSING) |
| remove_replica | PASS | 10;6 | 2 | P17_MANAGEMENT_REMOVE_NODE | MISSING (MISSING) |
| remove_primary_drained | PASS | 10;6 | 2 | P17_MANAGEMENT_REMOVE_NODE | MISSING (MISSING) |
| remove_failed_node | PASS | 10;6 | 2 | P17_MANAGEMENT_REMOVE_NODE | MISSING (MISSING) |
| reshard_slot_range | PASS | 10;6 | 2 | P18_MANAGEMENT_RESHARD_REBALANCE | missing_fields=bytes_migrated: Valkey MIGRATE byte count is not exposed by the command path. |
| reshard_with_keys | PASS | 10;6 | 2 | P18_MANAGEMENT_RESHARD_REBALANCE | missing_fields=bytes_migrated: Valkey MIGRATE byte count is not exposed by the command path. |
| rebalance_after_imbalance | PASS | 10;6 | 2 | P18_MANAGEMENT_RESHARD_REBALANCE | missing_fields=bytes_migrated: Valkey MIGRATE byte count is not exposed by the command path. |
| rolling_restart_replica_first | PASS | 10;6 | 2 | P19_MANAGEMENT_ROLLING_RESTART | MISSING (MISSING) |
| rolling_restart_primary_safe | PASS | 10;6 | 2 | P19_MANAGEMENT_ROLLING_RESTART | missing_fields=cluster_recovery_latency_ms: Target was not primary at restart time, so primary failover recovery did not apply.; promotion_latency_ms: Target was not primary at restart time, so no failover promotion was required.; read_unavailability_ms: No read outage was observed during controlled primary handoff.; read_unavailability_ms: Target was not primary at restart time, so primary read-unavailability measurement did not apply.; write_unavailability_ms: No write outage was observed during controlled primary handoff.; write_unavailability_ms: Target was not primary at restart time, so primary write-unavailability measurement did not apply. |
