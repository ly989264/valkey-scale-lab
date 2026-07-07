# P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY

## Purpose

Split failover recovery observability into independently measured RTO segments so business-visible client recovery, Valkey cluster recovery, and clean-gate tail cost are not conflated.

## Required implementation

- Add a failover timeline observer under `src/valkey_scale_lab/observer/` that runs concurrently with fault injection and is not blocked by the clean-gate path.
- Sample `CLUSTER INFO`, `CLUSTER NODES`, cluster slot counters, `fail`/`pfail`/`handshake` counts, role changes, replica promotion, target-process-gone markers, and client SET/GET success while the fault is active.
- Record the required timestamps for every real single-primary failover sample:
  - `fault_apply_at_ms`
  - `target_process_gone_at_ms`
  - `first_pfail_seen_at_ms`
  - `first_fail_seen_at_ms`
  - `first_promotion_seen_at_ms`
  - `first_slots_covered_at_ms`
  - `first_cluster_ok_at_ms`
  - `first_client_success_at_ms`
  - `clean_snapshot_passed_at_ms`
- Derive:
  - `kill_to_pfail_ms`
  - `pfail_to_cluster_ok_ms`
  - `kill_to_client_recovered_ms`
  - `cluster_ok_to_client_success_ms`
  - `cluster_ok_to_clean_snapshot_ms`
  - `kill_to_clean_snapshot_ms`
- Add a continuous client recovery probe that runs during the fault period, performs SET/GET, records first successful round trip after fault, and reports:
  - `client_probe_interval_ms`
  - `first_success_after_fault_ms`
  - `error_count_before_recovery`
  - `timeout_count_before_recovery`
  - `moved_count`
  - `ask_count`

## Required artifacts

P44 must emit:

```text
artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/phase_summary.json
artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/valkey_e2e_evidence.json
artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/cleanup_report.json
artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/events.jsonl
artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/metrics_timeseries.jsonl
artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/workload_windows.json
artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/quant_summary.json
artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/analysis_summary.json
artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/report_index.json
artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/failover_timeline_samples.jsonl
artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/failover_rto_summary.json
artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/client_recovery_samples.jsonl
artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/observer_samples.jsonl
artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/dry_run_gt_200_projection.json
```

`failover_rto_summary.json` must include `sample_count`, p50/p95/max for `kill_to_pfail_ms`, `pfail_to_cluster_ok_ms`, `kill_to_client_recovered_ms`, `cluster_ok_to_clean_snapshot_ms`, and `kill_to_clean_snapshot_ms`, plus `timeout_config_ms`, `server_profile`, `nodehost_strategy`, `node_count`, and `scale`.

## Coverage

The stage must cover:

- fake/schema tests for timeline schema and derived metric calculation;
- a real small Valkey single-primary failover smoke path using the observer;
- real 30/50/100/200 failover timeline paths;
- greater-than-200 dry-run projection only, clearly marked non-real;
- scale-generic observer code with no hardcoded 200-node ceiling.

## Required harness assertions

Add fail-closed scripts:

```text
scripts/assert_failover_timeline_completeness.py
scripts/assert_rto_metric_semantics.py
scripts/assert_no_rto_partial_coverage.py
```

Assertions must fail when:

- any real failover sample lacks a complete timeline;
- `pfail_to_cluster_ok_ms` is replaced by `kill_to_clean_snapshot_ms`;
- `kill_to_client_recovered_ms` does not come from a continuous fault-period client probe;
- clean-gate time is counted in `pfail_to_cluster_ok_ms`;
- timestamps are not monotonic;
- `first_pfail_seen_at_ms` is missing;
- fake/schema tests are presented as real evidence;
- any of 30/50/100/200 real scales is absent;
- only one scale has observer evidence.

## Required tests

- Unit tests for timestamp derivation, missing field fail-closed behavior, and percentile calculation.
- Integration tests that aggregate fake observer samples into a summary without claiming real evidence.
- Negative tests for missing PFAIL, missing client recovery, missing cluster OK, semantic substitution, and partial scale coverage.
- Real smoke gate for a small Valkey single-primary failover.

## Safety and forbidden shortcuts

- Do not modify host networking, global firewall/routing, host interfaces, or unrelated processes.
- Do not use clean snapshot as the endpoint for `pfail_to_cluster_ok_ms`.
- Do not count mock client probes as real recovery evidence.
- Do not pass with only smoke or only one large scale.
- Greater-than-200 remains dry-run projection/schema proof unless a future explicit real-scale policy allows it.
