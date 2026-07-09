# C10 System metrics contract

Exact-scale real system metrics claims require rows across lifecycle windows:

```text
setup
management
workload
fault_or_failover where applicable
cleanup
```

Rows must include node_id, node_count, lifecycle_window, metric_name, metric_value or structured missing reason, source_type, timestamp/monotonic time.

Required metrics can be missing only with reasons, but a claim cannot PASS if all high-value resource metrics are missing. The gate must enforce a minimum numeric coverage threshold for CPU/RSS/network/Valkey INFO/cluster INFO metrics.
