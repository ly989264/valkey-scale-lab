# P45_CLEAN_GATE_LAYERED_DIAGNOSTICS

## Purpose

Keep the final clean-gate as the harness PASS, cleanup, and stability endpoint while separating it from failover RTO metrics. Failover evidence must expose three independently sourced layers:

- Level 1 recovery metric endpoint: first PFAIL to `cluster_state=ok` and all slots covered, sourced from the runtime observer.
- Level 2 client recovery endpoint: SIGKILL to first successful workload SET/GET recovery, sourced from the continuous client probe.
- Level 3 clean snapshot endpoint: no `fail`/`pfail`/`handshake` and all final node probes pass, sourced from the clean-gate.

## Required implementation

- Add clean-gate diagnostics that record representative and all-node probe rounds without weakening the final clean condition.
- Run the failover observer, client recovery probe, and clean-gate sampling as concurrent/layered endpoints. Level 1 and Level 2 must not be backfilled after waiting for Level 3.
- Derive `pfail_to_cluster_ok_ms` only from Level 1 observer timestamps. Do not use the clean snapshot endpoint for Level 1.
- Preserve Level 3 as a final harness PASS condition. If Level 3 fails, retain Level 1/2 RTO summaries for analysis but fail or block the stage.
- Emit per-round clean-gate probe records with `probe_start_ms`, `probe_end_ms`, `probe_duration_ms`, `sample_scope`, `sample_count`, `failed_reason`, and `slowest_node`.
- Record diagnostics fields: `first_cluster_ok_at_ms`, `first_slots_covered_at_ms`, `first_representative_clean_at_ms`, `first_all_nodes_clean_at_ms`, `clean_gate_total_ms`, `probe_round_count`, `full_probe_count`, `representative_probe_count`, `representative_probe_total_ms`, `all_nodes_probe_count`, `all_nodes_probe_total_ms`, `probe_timeout_count`, `max_single_probe_ms`, `slowest_probe_node`, `slowest_probe_ms`, `first_client_success_at_ms`, `first_pfail_seen_at_ms`, `first_fail_seen_at_ms`, `first_promotion_seen_at_ms`, and `last_failing_reason`.
- Keep the implementation scale-generic. Current real required scales are 30, 50, 100, and 200; greater-than-200 remains dry-run projection/schema proof only unless a future real-scale policy changes.

## Required artifacts

P45 must emit:

```text
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/phase_summary.json
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/valkey_e2e_evidence.json
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/cleanup_report.json
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/events.jsonl
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/metrics_timeseries.jsonl
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/workload_windows.json
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/quant_summary.json
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/analysis_summary.json
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/report_index.json
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/failover_timeline_samples.jsonl
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/observer_samples.jsonl
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/client_recovery_samples.jsonl
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/clean_gate_diagnostics.json
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/clean_gate_probe_rounds.jsonl
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/layered_recovery_summary.json
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/recovery_endpoint_summary.json
artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/dry_run_gt_200_projection.json
```

`layered_recovery_summary.json` must include `kill_to_pfail_ms`, `pfail_to_cluster_ok_ms`, `cluster_ok_to_client_success_ms`, `cluster_ok_to_clean_snapshot_ms`, `kill_to_clean_snapshot_ms`, `level_1`, `level_2`, `level_3`, and `clean_gate`.

## Coverage

- Fake/schema tests for layered schema, timestamp derivation, missing field fail-closed behavior, and RTO conflation rejection.
- Unit tests for clean-gate diagnostics aggregation, last failing reason selection, and timestamp monotonicity.
- Integration tests for a simulated slow clean-gate.
- Real smoke Valkey failover with layered endpoints.
- Real 30/50/100/200 Valkey failover/full-flow evidence with layered artifacts.
- Management, fault, and full-flow paths that call the clean-gate must preserve diagnostics-capable clean checks.
- Greater-than-200 dry-run projection may validate schema only and must not claim real evidence.

## Required harness assertions

Add fail-closed scripts:

```text
scripts/assert_clean_gate_diagnostics.py
scripts/assert_layered_recovery_semantics.py
scripts/assert_no_clean_gate_rto_conflation.py
scripts/assert_no_clean_gate_partial_coverage.py
```

Assertions must fail when:

- `clean_gate_total_ms`, `probe_round_count`, or `full_probe_count` is missing.
- `last_failing_reason` is missing when the clean-gate did not immediately pass.
- `pfail_to_cluster_ok_ms` equals `kill_to_clean_snapshot_ms` unless timestamps prove the endpoints are identical.
- Level 1, Level 2, or Level 3 lacks source and timestamps.
- Any required real scale in 30/50/100/200 lacks layered evidence.
- Fake tests are used as real evidence.
- Only one historical path, such as P35 or P36, has the implementation.
- Fields are present only in reports instead of being produced by runtime observer/client probe/clean-gate code.

## Safety and forbidden shortcuts

- Do not delete or weaken the clean-gate.
- Do not lower the final clean condition to shorten RTO.
- Do not count Level 3 clean snapshot time in Level 1 recovery.
- Do not use static JSON or mock-only evidence as real evidence.
- Do not hardcode 200 as a maximum in runtime code.
- Do not weaken cleanup, coverage, or no-bypass gates.
