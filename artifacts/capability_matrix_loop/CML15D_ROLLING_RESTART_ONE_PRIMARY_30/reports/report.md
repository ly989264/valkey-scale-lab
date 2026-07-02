# CML15D rolling_restart_one_primary 30

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
| rolling_restart | 0.637876 | PASS |

## Workload Windows

| window | availability_percent | errors | p50_ms | p95_ms | p99_ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| before | 100.000 | 0 | 51.251 | 60.581 | 64.910 |
| during | 100.000 | 0 | 62.676 | 68.351 | 68.462 |
| after | 100.000 | 0 | 53.252 | 62.351 | 63.935 |

## Visual

See `lifecycle_timeline.svg` for operation duration, latency, availability, slot coverage, and role count charts.
