# CML15B reshard_slots 30

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
| reshard_slots | 0.072206 | PASS |

## Workload Windows

| window | availability_percent | errors | p50_ms | p95_ms | p99_ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| before | 100.000 | 0 | 54.777 | 62.629 | 64.149 |
| during | 100.000 | 0 | 60.237 | 74.979 | 76.825 |
| after | 100.000 | 0 | 54.747 | 61.221 | 62.943 |

## Visual

See `lifecycle_timeline.svg` for operation duration, latency, availability, slot coverage, and role count charts.
