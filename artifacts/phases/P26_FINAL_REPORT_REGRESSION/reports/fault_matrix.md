# P26 Fault Matrix

Generated from JSON/JSONL artifacts only. Source refs are listed in `final_report_index.json`.

| fault_row | status | node_counts | sample_count | implementation_paths | reason |
| --- | --- | --- | --- | --- | --- |
| primary_stop_failover | PASS | 30;50;100;200 | 12 | project_fault_api_node_stop_owned_container_or_process | MISSING (MISSING) |
| replica_stop | PASS | 10;30;6 | 3 | owned_runtime_control | MISSING (MISSING) |
| node_host_stop | PASS | 10;30;6 | 3 | owned_runtime_control | MISSING (MISSING) |
| az_stop | PASS | 10;30;6 | 3 | owned_runtime_control | MISSING (MISSING) |
| network_delay | PASS | 10;6 | 2 | sandbox_proxy | MISSING (MISSING) |
| network_loss | PASS | 10;6 | 2 | sandbox_proxy | MISSING (MISSING) |
| network_flap | PASS | 10;6 | 2 | sandbox_proxy | MISSING (MISSING) |
| network_partition | PASS | 10;6 | 4 | owned_docker_network_control | MISSING (MISSING) |
| minority_partition | PASS | 10;6 | 2 | owned_docker_network_control | MISSING (MISSING) |
| majority_partition | PASS | 10;6 | 2 | owned_docker_network_control | MISSING (MISSING) |
| split_brain_window | PASS | 10;6 | 6 | owned_docker_network_control | MISSING (MISSING) |
| fault_workload_impact | PASS | all_source_rows | 21 | artifact_only_p25_consolidation | MISSING (MISSING) |
