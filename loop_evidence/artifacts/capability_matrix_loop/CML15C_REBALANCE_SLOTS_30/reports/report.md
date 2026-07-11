# CML15C rebalance_slots 30

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
| rebalance_slots | 0.051261 | PASS |

## Workload Windows

| window | availability_percent | errors | p50_ms | p95_ms | p99_ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| before | 100.000 | 0 | 52.956 | 65.576 | 65.797 |
| during | 100.000 | 0 | 43.794 | 57.407 | 63.005 |
| after | 100.000 | 0 | 51.332 | 62.976 | 64.740 |

## Visual

See `lifecycle_timeline.svg` for operation duration, latency, availability, slot coverage, and role count charts.
