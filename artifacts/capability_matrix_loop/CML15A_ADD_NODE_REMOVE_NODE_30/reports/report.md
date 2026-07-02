# CML15A add_node/remove_node 30

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

## Workload Windows

| window | availability_percent | errors | p50_ms | p95_ms | p99_ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| before | 100.000 | 0 | 51.167 | 60.552 | 65.267 |
| during | 100.000 | 0 | 44.128 | 60.316 | 73.877 |
| after | 100.000 | 0 | 53.448 | 59.525 | 60.227 |

## Visual

See `lifecycle_timeline.svg` for operation duration, latency, availability, slot coverage, and role count charts.
