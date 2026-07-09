# C09 Fault timeline contract

A real fault timeline claim requires:

- events for fault_planned, apply_started, apply_completed, effect_observed, cluster_impact_started, failover_started, promotion_observed when applicable, cluster_recovered, workload_recovered, clear_started, clear_completed, cleanup_verified;
- metrics: apply_duration_ms, effect_observed_delay_ms, cluster_impact_ms, failover_latency_ms, promotion_latency_ms where applicable, client_unavailability_ms, workload_recovery_ms, clear_duration_ms, cleanup_duration_ms, split_brain_window_ms, cluster_down_window_ms;
- real_valkey true;
- execution_mode not fake;
- status PASS, not PARTIAL;
- source refs to workload and cleanup;
- clean cluster evidence.

Fake/PARTIAL rows may test parsing but cannot satisfy real claims.
