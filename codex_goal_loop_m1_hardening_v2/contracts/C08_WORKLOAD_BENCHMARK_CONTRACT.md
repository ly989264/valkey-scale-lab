# C08 Workload benchmark contract

A workload benchmark PASS requires:

- profiles: `smoke`, `uniform`, `hotspot`, `mixed_rw`, `write_heavy`, `read_heavy`;
- windows: `baseline`, `pre_event`, `event`, `recovery`, `post_recovery`, `all_run`;
- required metrics per profile-window: requested_qps, achieved_qps, throughput_ratio, ok_ops, error_ops, error_rate, latency_p50/p90/p95/p99/p999, timeout_count, connection_error_count, moved/ask/cluster_down/readonly/tryagain;
- metric row count >= profile_count * window_count * required_metric_count;
- connections and pipeline either actually exercised and recorded or explicitly blocked;
- operations_per_window above the configured minimum for benchmark claims;
- full-slot coverage for non-smoke profiles.

One metric row is a FAIL for benchmark claims.
