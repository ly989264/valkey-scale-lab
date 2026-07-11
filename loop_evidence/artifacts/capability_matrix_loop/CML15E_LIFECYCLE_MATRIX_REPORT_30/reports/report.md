# CML15E lifecycle_matrix_report_30

Status: PASS

## Cluster Summary

- nodes_observed: `30`
- cluster_state: `ok`
- slots_assigned: `16384`
- slots_fail: `0`
- roles: `15` primary / `15` replica
- data_path_result: `PASS`

## Operation Durations

| operation | duration_seconds | status |
| --- | ---: | --- |
| add_node | 0.077456 | PASS |
| remove_node | 1.125269 | PASS |
| reshard_slots | 0.072206 | PASS |
| rebalance_slots | 0.051261 | PASS |
| rolling_restart | 0.637876 | PASS |

## Workload Windows

| window | availability_percent | errors | p50_ms | p95_ms | p99_ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| before | 100.000 | 0 | 0.000 | 0.000 | 0.000 |
| operation_or_fault_apply | 100.000 | 0 | 0.000 | 0.000 | 0.000 |
| during | 100.000 | 0 | 0.000 | 0.000 | 0.000 |
| clear_or_recovery_start | 100.000 | 0 | 0.000 | 0.000 | 0.000 |
| after_recovery | 100.000 | 0 | 0.000 | 0.000 | 0.000 |
| all_run | 100.000 | 0 | 0.000 | 0.000 | 0.000 |

## Visual

See `lifecycle_timeline.svg` for operation duration, latency, availability, slot coverage, and role count charts.
