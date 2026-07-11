# Audit - P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-07-07T04:45:00Z

Gate Result: artifacts/gates/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/gate_result.json
Observed Gate Result SHA256: a7dd9770c88bfccc3eb0f9eb018960004c8bed1c444ed3c4468be86117a31f67

## Scope inspected

- P44 stage document, goal-loop context reload, design brief, worker summary, and fresh-context review.
- P44 source, config, runtime, schema, assertion, test, and artifact diffs.
- P44 gate logs and real Valkey artifacts for 10/30/50/100/200.

## Gate findings

| Gate | Observed | Evidence |
|---|---:|---|
| safety_static_scan | PASS | `artifacts/gates/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/gate_result.json` |
| scripts_compile | PASS | `artifacts/gates/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/gate_result.json` |
| failover_timeline_tests | PASS | `artifacts/gates/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/stdout/failover_timeline_tests.log` |
| failover_timeline_real | PASS | Real 10/30/50/100/200 run in `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/` |
| schema and semantic assertions | PASS | Timeline, summary, client, observer, events, metrics, workload windows, completeness, RTO semantics, partial coverage, cleanup |

## Artifact findings

P44 required artifacts are present. `failover_timeline_samples.jsonl` has PASS real-Valkey samples for 10/30/50/100/200. `failover_rto_summary.json` reports p50/p95/max for the required RTO series. `client_recovery_samples.jsonl` and `observer_samples.jsonl` provide source rows for the derived sample timestamps and workload windows. `dry_run_gt_200_projection.json` declares dry-run projection only with `real_valkey=false`.

| Artifact | Observed |
|---|---:|
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/phase_summary.json` | present |
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/valkey_e2e_evidence.json` | present |
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/cleanup_report.json` | present |
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/events.jsonl` | present |
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/metrics_timeseries.jsonl` | present |
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/workload_windows.json` | present |
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/quant_summary.json` | present |
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/analysis_summary.json` | present |
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/report_index.json` | present |
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/failover_timeline_samples.jsonl` | present |
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/failover_rto_summary.json` | present |
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/client_recovery_samples.jsonl` | present |
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/observer_samples.jsonl` | present |
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/dry_run_gt_200_projection.json` | present |

## Safety findings

No host firewall, routing, interface, or global network mutation was found in the P44 paths. Faults and cleanup remain scoped to owned Docker/process resources. Cleanup reports PASS with no remaining resources.

## Real Valkey findings

Required for this phase: YES
Evidence file: `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/valkey_e2e_evidence.json`
Valkey version observed: `9.1.0`
Observed real scales: 10, 30, 50, 100, 200

## Quantitative findings

RTO metrics separate `kill_to_client_recovered_ms`, `pfail_to_cluster_ok_ms`, clean snapshot tail, and the intermediate segments. `workload_windows.json` includes baseline, pre_event, event, recovery, post_recovery, and all_run windows for every sample, with all_run metrics derived from `client_recovery_samples.jsonl`.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| P44 captures one sample per scale in the required gate | low | no | The stage requires coverage and semantic protection, not a statistically broad repeated run. |

## Final rationale

All manifest gates passed, fresh-context review passed, real Valkey evidence covers 10/30/50/100/200 without fake promotion, >200 remains dry-run only, cleanup passes, and the RTO timeline metrics are derived from concurrent observer and client probe artifacts instead of clean-gate timing.
