# L09 Stability Soak Multi-Stage Metrics Design

## Scope

L09 extends the existing P11 stability smoke into an artifact-first, bounded, multi-stage soak model. The automatic stage covers:

- `baseline`
- `steady`
- `fault`
- `recovery`
- `post_recovery`

The stage must preserve the existing P11 small-real wrapper behavior while adding stricter source artifacts and audit coverage. It must not run `P14_SCALE_1000_OPTIN_DRYRUN`, set `VSLAB_ALLOW_1000_DRYRUN`, or count any 1000-node dry-run output as real stability evidence.

## Current Gaps

- P11 emits `stability_report.json`, `stability_metrics.jsonl`, and `stability_baseline_comparison.json`, but samples only carry interval numbers and no L09 window identity.
- `schemas/artifact/stability_report.schema.json` is permissive and cannot enforce required L09 windows, bounded semantics, source paths, or explicit missing reasons.
- 30/50/100 scale rungs have real scale and fault/failover evidence, but no dedicated bounded stability soak profile artifacts.
- Metric catalog, coverage matrix, provenance graph, and loop reports currently expose only small-real P11 stability metrics.

## Harness-First Plan

1. Add strict artifact contracts for stability timeseries samples, soak profiles, and the L09 rollup.
2. Add deterministic fake timeline tests for the five-window model. These tests must classify fake evidence as non-real.
3. Add `scripts/audit_stability_soak_metrics.py` to validate JSON/JSONL source artifacts only and emit `artifacts/loop_engineering/reports/stability_soak_metrics.json`.
4. Add negative artifact tests for missing windows, empty or unordered JSONL, missing reasons, invalid percentile ordering, stale cleanup, long-run claims from bounded windows, and P14 real coverage.
5. Extend runtime/wrapper output so P11 small-real stability produces L09-compatible windows while preserving cleanup and real Valkey evidence.
6. Add bounded/resource-aware 30/50/100 stability profile artifacts. If a rung is not measured, the profile must be `SKIPPED_WITH_REASON` tied to resource preflight and must not count as real stability coverage.
7. Wire stability metrics into coverage, metric catalog, provenance, and loop report rendering as views over JSON/JSONL artifacts.

## Artifact Contracts

Each measured profile must include:

- `node_count`, `phase_id`, `scenario`, `evidence_layer`, `bounded`, and `long_run_stability_claim=false`.
- `metrics_timeseries_path` pointing to non-empty JSONL rows.
- `baseline_comparison_path` when baseline comparison is applicable.
- `windows` entries for all five required windows.
- Per-window latency `p50`, `p95`, and `p99`, or explicit `MISSING`/`SKIPPED_WITH_REASON` objects with reasons.
- Memory growth/leak summaries and restart deltas measured from source samples or explicit missing objects with reasons.
- Window-aware error taxonomy.
- Source references for real evidence, resource preflight, and cleanup where applicable.

Each bounded/resource-aware 30/50/100 profile must include resource preflight evidence. A measured profile also needs matching real evidence and cleanup `PASS`. A skipped profile must carry `SKIPPED_WITH_REASON`, must not count as real coverage, and must explain the resource blocker.

## Safety Boundaries

- No host network, firewall, routing, interface, OS network service, sudo-network, broad process kill, or unrelated container cleanup changes.
- Fault-stage soak must use owned Docker/container scopes or explicit sandbox proxy layers only.
- Missing metrics remain explicit; aggregation must not convert missing restart, memory, latency, or baseline values into zero.
- Reports, Markdown, HTML, SVG, and CSV are never metric sources of truth.
- P14 remains dry-run/opt-in only. L09 may audit the P14 boundary but may not execute it.

## Validation

The stage validation must run the previous harness, L09 stability tests, schema validation, the L09 audit builder, metric/report/provenance tests, safety scan, `loop_engineering_validate`, review agent, validation agent, and anti-regression guardian before commit and push.
