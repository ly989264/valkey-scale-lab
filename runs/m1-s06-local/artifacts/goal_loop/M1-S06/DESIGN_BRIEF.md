# M1-S06 Design Brief

Stage: M1-S06
Role: design subagent
Repository HEAD inspected: `0705a95fe4de30237b6a27a9dbe89f15be281d8e`
Decision: IMPLEMENT A COMMON FAULT TIMELINE CONTRACT, NOT A PRIMARY-STOP-ONLY PATCH

## 1. 当前 Stage 目标复述

M1-S06 must upgrade fault/failover evidence from row-level PASS artifacts into a shared, schema-validated timeline that covers every required fault type and every required scale rung. The required event sequence is:

```text
fault_planned
fault_apply_started
fault_apply_completed
fault_effect_observed
cluster_impact_started
failover_started
promotion_observed
cluster_recovered
workload_recovered
fault_clear_started
fault_clear_completed
cleanup_verified
```

The timeline must produce or explicitly mark these metrics: `apply_duration_ms`, `effect_observed_delay_ms`, `cluster_impact_ms`, `failover_latency_ms`, `promotion_latency_ms`, `client_unavailability_ms`, `workload_recovery_ms`, `clear_duration_ms`, `cleanup_duration_ms`, `split_brain_window_ms`, and `cluster_down_window_ms`.

Coverage must include `primary_stop_failover`, `replica_stop`, `node_host_stop`, `az_stop`, `network_delay`, `network_loss`, `network_flap`, `network_partition`, `minority_partition`, `majority_partition`, `split_brain_window_detection`, and `fault_period_workload_impact`. Small, 30, 50, 100, and 200 node paths must either execute or write structured `SKIPPED_WITH_REASON`/`BLOCKED_WITH_REASON`. 200+ remains dry-run planning only and must not create runtime resources.

Failover latency samples must be derived from, or reference, timeline rows. M1-S05 workload benchmark windows must be linked to fault-period impact windows, not copied into report-only summaries. Real-gate failures caused by local Docker/port restrictions must be recorded as blocked evidence; no fake real PASS is allowed.

## 2. 当前仓库中相关代码路径

- Fault lifecycle API: `src/valkey_scale_lab/fault/sandbox.py`
- Sandbox proxy path: `src/valkey_scale_lab/fault/network_proxy.py`
- Existing observer/RTO helpers: `src/valkey_scale_lab/observer/failover_timeline.py`
- Runtime scenario writer and strict stage hooks: `src/valkey_scale_lab/runtime/docker_runtime.py`
- CLI entrypoints: `src/valkey_scale_lab/cli.py`
- Fault/failover gates: `scripts/fault_failover_gate.py`, `scripts/fault_failover_timeline_gate.py`, `scripts/fault_safety_gate.py`
- Existing assertions: `scripts/assert_failover_timeline_completeness.py`, `scripts/assert_failover_latency_curve.py`, `scripts/assert_fault_matrix_coverage.py`, `scripts/assert_fault_matrix_strict.py`, `scripts/assert_workload_impact.py`
- Current schemas: `schemas/artifact/failover_timeline_sample.schema.json`, `schemas/artifact/failover_latency_sample.schema.json`, `schemas/artifact/failover_latency_curve.schema.json`, `schemas/artifact/fault_matrix_report.schema.json`, `schemas/artifact/fault_result.schema.json`, `schemas/artifact/fault_report.schema.json`, `schemas/artifact/workload_windows.schema.json`, `schemas/artifact/workload_impact_report.schema.json`
- Analysis readers: `src/valkey_scale_lab/analysis/summary.py`, `src/valkey_scale_lab/analysis/workload_impact.py`
- Offline Chinese renderer: `src/valkey_scale_lab/report/render.py`, final report path in `src/valkey_scale_lab/report/final.py`
- Existing tests: `tests/unit/test_failover_timeline_observer.py`, `tests/integration/test_failover_timeline_artifacts.py`, `tests/failover/test_failover_timeline_assertions.py`, `tests/failover/test_failover_contract.py`, `tests/fault/test_sandbox_fault.py`, `tests/fault/test_network_proxy.py`, `tests/analysis/test_workload_impact_cross_stage.py`, `tests/report/test_report_rendering.py`
- M1-S05 handoff and workload artifacts: `runs/m1-s05-local/artifacts/goal_loop/M1-S05/HANDOFF.md`, `runs/m1-s05-local/artifacts/workload_windows.json`, `runs/m1-s05-local/artifacts/analysis_summary.json`, `runs/m1-s05-local/reports/report_index.json`

Current gaps observed:

- `failover_timeline_sample.schema.json` is P44/RTO-oriented and does not model all M1-S06 events, all M1-S06 metrics, all fault types, blocked rows, dry-run rows, or workload-impact refs.
- `scripts/fault_failover_timeline_gate.py` handles primary stop RTO and emits events named `fault_apply`, `first_pfail_seen`, etc.; it does not emit the M1-S06 canonical event names for every fault type.
- `scripts/fault_failover_gate.py` has useful primary failover, network, partition, and workload-window helpers, but they are phase-specific and not unified into one timeline contract.
- `src/valkey_scale_lab/analysis/summary.py` reads `failover_report.json` but does not aggregate a first-class fault timeline distribution, split-brain-window distribution, or timeline-derived latency samples.
- `src/valkey_scale_lab/report/render.py` currently reports workload and management details but has no Chinese fault timeline, failover latency distribution, or split-brain window section.
- There are no `tests/fixtures/fault_timeline/...` fixtures spanning success, failure, timeout, missing effect observed, blocked, dry-run, cleanup residual, and report-input missing paths.

## 3. 需要修改的通用路径

Implement through shared model/writer helpers so P20/P21/P22/P23/P24/P33/P34/P35/P44 can converge on the same contract:

- Add or extend a common module such as `src/valkey_scale_lab/observer/failover_timeline.py` with:
  - `M1_REQUIRED_TIMELINE_EVENTS`
  - `M1_REQUIRED_TIMELINE_METRICS`
  - `M1_REQUIRED_FAULT_TYPES`
  - `build_fault_timeline_events(sample)`
  - `derive_fault_timeline_metrics(events, workload_windows=None)`
  - `build_failover_latency_sample_from_timeline(sample)`
  - `build_fault_timeline_report(samples, workload_windows)`
- Update `scripts/fault_failover_timeline_gate.py` to emit the common timeline artifacts while preserving current P44/P45 artifacts.
- Update `scripts/fault_failover_gate.py` so primary stop, scale curves, replica/host/AZ stop, network delay/loss/flap, partition, split-brain, and workload-impact paths write canonical timeline rows or structured skip/block rows.
- Update `src/valkey_scale_lab/fault/sandbox.py` only where necessary to expose apply/clear timing and effect-observation fields from the CLI fault lifecycle. Keep host-network safety checks fail-closed.
- Update `src/valkey_scale_lab/analysis/summary.py` and `src/valkey_scale_lab/analysis/workload_impact.py` to read the canonical timeline and linked workload windows.
- Update `src/valkey_scale_lab/report/render.py` and `src/valkey_scale_lab/report/final.py` in this stage, not later.

## 4. Schema 传播计划

Schema updates must follow: schema -> writer -> fixture -> reader -> aggregator -> renderer -> gate -> docs.

- Add `schemas/artifact/fault_timeline_event.schema.json`:
  - Required fields: `schema_version`, `artifact_type=fault_timeline_event`, `phase_id`, `run_id`, `scenario_name`, `sample_id`, `fault_id`, `fault_type`, `node_count`, `scale_rung`, `event_name`, `event_status`, `timestamp_unix_ms`, `monotonic_ms`, `source`, `subject_type`, `subject_id`, `real_valkey`, `execution_mode`, `reason`.
  - `event_name` enum must contain the 12 M1-S06 event names.
  - `event_status` enum: `OBSERVED`, `MISSING`, `SKIPPED_WITH_REASON`, `BLOCKED_WITH_REASON`, `FAIL`.
- Add `schemas/artifact/fault_timeline_report.schema.json`:
  - Required fields: `fault_rows`, `timeline_events_ref`, `failover_latency_samples_ref`, `fault_workload_impact_ref`, `required_fault_types`, `observed_fault_types`, `required_scale_rungs`, `observed_scale_rungs`, `missing_metrics`.
  - Every fault row must include all M1-S06 metrics, `metric_sources`, `timeline_event_refs`, `workload_window_refs`, `cleanup_ref`, `valkey_e2e_evidence_ref`, safety fields, and real/block/dry-run status.
- Extend `schemas/artifact/failover_latency_sample.schema.json` and `failover_latency_curve.schema.json`:
  - Add `timeline_ref`, `fault_type`, `fault_id`, `source_event_start`, `source_event_end`, `derived_from_timeline=true`, and `workload_recovery_ref`.
  - Require `node_count` values for 30/50/100/200 samples or structured blocked rows.
- Extend `schemas/artifact/fault_matrix_report.schema.json` and `fault_result.schema.json`:
  - Require `timeline_ref`/`timeline_status` for each row.
  - Require missing effect observed to be a structured object, not a bare string.
- Extend `schemas/artifact/workload_impact_report.schema.json` and `workload_impact_cross_stage.schema.json`:
  - Add `fault_timeline_ref`, `fault_event_window`, `client_unavailability_ms`, `cluster_down_window_ms`, `workload_recovery_ms`, and M1-S05 profile/slot fields.
- If M1 stage IDs appear in fixtures, widen relevant phase patterns conservatively to accept either `M1-S06` or existing `P.._...` without weakening required fields.

## 5. Artifact Writer 传播计划

Canonical artifact set for M1-S06 runtime/gate outputs under `runs/m1-s06-local/artifacts/` or a supplied artifact dir:

```text
fault_timeline_events.jsonl
fault_timeline_report.json
failover_latency_samples.jsonl
failover_latency_curve.json
fault_matrix_report.json
fault_workload_impact.json
workload_windows.json
events.jsonl
metrics_timeseries.jsonl
phase_summary.json
quant_summary.json
valkey_e2e_evidence.json
cleanup_report.json
```

Writer rules:

- `fault_planned` is written before a destructive or proxy action is attempted.
- `fault_apply_started`/`fault_apply_completed` wrap `python3 -m valkey_scale_lab.cli fault apply`.
- `fault_effect_observed` is written from live probe evidence; if not observed, write `MISSING` with reason and impact.
- `cluster_impact_started`, `failover_started`, `promotion_observed`, `cluster_recovered`, and `workload_recovered` are derived from observer/client/workload rows for primary failover and partition rows. For fault types where no promotion is expected, `promotion_observed` must be `SKIPPED_WITH_REASON` with `promotion_expected=false`.
- `fault_clear_started`/`fault_clear_completed` wrap `python3 -m valkey_scale_lab.cli fault clear`.
- `cleanup_verified` is sourced from `cleanup_report.json`.
- Metrics are derived only from event timestamps and workload windows:
  - `apply_duration_ms = fault_apply_completed - fault_apply_started`
  - `effect_observed_delay_ms = fault_effect_observed - fault_apply_completed`
  - `cluster_impact_ms = cluster_recovered - cluster_impact_started`
  - `failover_latency_ms = cluster_recovered - failover_started`
  - `promotion_latency_ms = promotion_observed - failover_started`
  - `client_unavailability_ms` from M1-S05-style workload/client probe windows
  - `workload_recovery_ms = workload_recovered - cluster_recovered`
  - `clear_duration_ms = fault_clear_completed - fault_clear_started`
  - `cleanup_duration_ms = cleanup_verified - fault_clear_completed`
  - `split_brain_window_ms` from side-view divergence start/end
  - `cluster_down_window_ms` from CLUSTERDOWN/client error window start/end
- Missing values must be objects or schema-accepted `MISSING` with `reason`; do not substitute cleanup duration for failover latency.

## 6. Artifact Reader / Analyzer 传播计划

- `src/valkey_scale_lab/analysis/summary.py`
  - Load optional `fault_timeline_report.json`, `fault_timeline_events.jsonl`, `failover_latency_samples.jsonl`, `failover_latency_curve.json`, and `fault_workload_impact.json`.
  - Add `fault_timeline` aggregate containing:
    - `fault_type_coverage`
    - `scale_coverage`
    - per-fault event completeness
    - failover latency p50/p95/max by scale
    - promotion latency p50/p95/max
    - client unavailability and workload recovery summaries
    - split-brain window summary
    - cleanup verification summary
    - missing/block/skipped reason counts
  - Add metrics: `fault_failover_latency_p95_ms`, `fault_client_unavailability_p95_ms`, `fault_workload_recovery_p95_ms`, `fault_split_brain_window_max_ms`, `fault_cluster_down_window_max_ms`.
  - Feed timeline missing metrics into `_collect_missing_metrics()`.
- `src/valkey_scale_lab/analysis/workload_impact.py`
  - Read `fault_workload_impact.json` and `workload_windows.json`.
  - Preserve M1-S05 `profile`, `workload_mode`, `hash_slot_coverage`, and canonical QPS/latency/error fields.
  - Emit cross-stage rows keyed by `fault_id` and `sample_id` with timeline refs.
- Reader must treat rendered Markdown/HTML as outputs only; no analysis may parse reports as metric sources.

## 7. 中文 Report Renderer 传播计划

Update `src/valkey_scale_lab/report/render.py` in M1-S06 to generate offline Chinese views:

- CSV exports:
  - `fault_timeline_events.csv`
  - `fault_timeline_summary.csv`
  - `failover_latency_distribution.csv`
  - `split_brain_windows.csv`
  - `fault_workload_impact.csv`
- SVG assets:
  - `fault_timeline.svg`
  - `failover_latency_distribution.svg`
  - `split_brain_window.svg`
  - `fault_workload_impact.svg`
- `report_index.json` adds `fault_timeline_report_inputs` with refs to timeline, latency, split-brain, workload-impact, evidence, and cleanup artifacts.
- Markdown/HTML sections:
  - `## 故障 Timeline`
  - `## Failover 延迟分布`
  - `## Split-brain 窗口`
  - `## 故障期间 Workload 影响`
  - Include Chinese labels for all event names and metrics.
  - When rows are blocked or missing, display the structured reason in Chinese and preserve the original status token.

`src/valkey_scale_lab/report/final.py` should preserve these fields in final/offline report exports so M1-S08 does not need to recover missing data later.

## 8. Fake Fixture / Smoke / Integration / Real Path 覆盖计划

Add fixture trees:

```text
tests/fixtures/fault_timeline/success/
tests/fixtures/fault_timeline/failure/
tests/fixtures/fault_timeline/timeout/
tests/fixtures/fault_timeline/missing_effect_observed/
tests/fixtures/fault_timeline/blocked/
tests/fixtures/fault_timeline/dry_run_200_plus/
tests/fixtures/fault_timeline/cleanup_residual/
tests/fixtures/fault_timeline/report_input_missing/
tests/fixtures/fault_timeline/scale_30/
tests/fixtures/fault_timeline/scale_50/
tests/fixtures/fault_timeline/scale_100/
tests/fixtures/fault_timeline/scale_200/
```

Tests to add or extend:

- Unit:
  - `tests/unit/test_fault_timeline_contract.py`: event completeness, metric derivation, monotonic timestamp rejection, missing effect observed reason required, no cleanup substitution.
  - Extend `tests/unit/test_failover_timeline_observer.py` for timeline-to-latency sample derivation.
- Artifact/schema:
  - `tests/artifacts/test_fault_timeline_artifacts.py`: validate all fixture directories and reject empty JSONL.
- Integration:
  - Extend `tests/integration/test_failover_timeline_artifacts.py` for schema-valid fake rows that fail real completeness gates.
  - Add `tests/integration/test_fault_timeline_pipeline.py` to prove fixture -> analysis -> report path.
- Fault/runtime:
  - Extend `tests/fault/test_sandbox_fault.py` and `tests/fault/test_network_proxy.py` for apply/clear timing and safety fields.
  - Extend `tests/failover/test_failover_contract.py` and `tests/failover/test_failover_timeline_assertions.py`.
- Analysis/report:
  - Extend `tests/analysis/test_analysis_summary.py`, `tests/analysis/test_workload_impact_cross_stage.py`, and `tests/report/test_report_rendering.py`.
- Real/smoke:
  - Attempt small real gate when possible through `scripts/fault_failover_gate.py` or `scripts/fault_failover_timeline_gate.py`.
  - 30/50/100/200 real heavy gates must be attempted only after resource preflight passes. If local port/Docker sandbox blocks them, write `BLOCKED_WITH_REASON`.

## 9. Dry-run / Blocked / Failure / Cleanup Path 处理计划

- Dry-run:
  - `scale_200_plus_dry_run_planning` emits planning artifacts only.
  - `real_valkey=false`, `runtime_resources_created=false`, and every timeline event is `SKIPPED_WITH_REASON` with reason `greater-than-200 dry-run planning only`.
- Blocked:
  - Real gate blocked by sandbox port bind, Docker unavailable, or preflight failure writes `runs/m1-s06-local/artifacts/goal_loop/M1-S06/real_fault_failover_gate_blocked.json`.
  - Include command, stdout/stderr refs, phase, scale, scenario, status `BLOCKED_WITH_REASON`, impact, and no fake Valkey version claims.
- Failure:
  - Command failure rows keep non-empty `fault_timeline_events.jsonl` and `metrics_timeseries.jsonl`.
  - Failed apply/clear must have `fault_apply_started` or `fault_clear_started` plus failure status and reason.
  - Timeout rows use outcome class `timeout` and do not invent recovery timestamps.
- Cleanup:
  - Cleanup residual fixtures must include `cleanup_verified=FAIL` and `cleanup_duration_ms=MISSING` or measured duration with residual resources.
  - Gate must fail unless cleanup is PASS or the run is explicitly blocked before resources were created.

## 10. Coverage Matrix 草案

| stage_id | change_id | field_or_behavior | execution_shape | scale_rung | functional_path | data_path | outcome_class | coverage_status | evidence_path | test_or_gate | missing_or_skipped_reason | owner_notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M1-S06 | timeline_events | 12 canonical fault/failover timeline events | fake,unit,integration,smoke,real_local_run,blocked_run,dry_run,cleanup,failure_path | small_cluster,scale_30,scale_50,scale_100,scale_200,scale_200_plus_dry_run_planning | fault,failover,metrics,cleanup | schema,artifact_writer,test_fixture,regression_check | success,command_failure,timeout,cleanup_residual | PASS or BLOCKED_WITH_REASON after gates | `tests/fixtures/fault_timeline/success/fault_timeline_events.jsonl` | `scripts/assert_fault_timeline_contract.py --fixtures tests/fixtures/fault_timeline` | real rows blocked only with structured evidence | One schema for every fault type. |
| M1-S06 | timeline_metrics | apply/effect/impact/failover/promotion/client/workload/clear/cleanup/split-brain/down-window metrics | fake,unit,integration,smoke,real_local_run,blocked_run | all rungs | fault,failover,metrics,analysis,report | schema,writer,reader,aggregator,renderer,gate | success,missing_metric,timeout | PASS or BLOCKED_WITH_REASON | `schemas/artifact/fault_timeline_report.schema.json` | pytest unit/artifact/analysis/report | missing metrics require reason | Derived from timestamps and windows only. |
| M1-S06 | fault_type_coverage | all 12 listed fault types | fake,integration,smoke,real_local_run,dry_run,blocked_run | small,30,50,100,200,200+ dry-run | fault,resource_preflight,cleanup | writer,fixture,gate | success,blocked_run | PASS or BLOCKED_WITH_REASON | `fault_timeline_report.json` | `scripts/assert_fault_timeline_contract.py --artifacts-dir ...` | unsupported platform path must be explicit | Prevents primary-stop-only completion. |
| M1-S06 | latency_from_timeline | failover latency samples derive/reference timeline | unit,integration,real_local_run,blocked_run | 30,50,100,200 | failover,analysis,report | schema,reader,aggregator,renderer,regression_check | success,missing_metric | PASS or BLOCKED_WITH_REASON | `failover_latency_samples.jsonl` | `scripts/assert_failover_latency_curve.py`; new timeline gate | missing timestamps block latency derivation | No invented samples. |
| M1-S06 | workload_impact_linkage | M1-S05 workload windows linked to fault periods | fake,integration,smoke,real_local_run,blocked_run | all rungs | workload,fault,failover,analysis,report | writer,reader,aggregator,renderer,test_fixture | success,report_input_missing | PASS | `fault_workload_impact.json` | `scripts/assert_workload_impact.py`; report test | missing workload input shown as SKIPPED_WITH_REASON | Preserve profile/slot fields. |
| M1-S06 | zh_fault_report | Chinese offline fault timeline and distributions | fake,integration,smoke | all fixture rungs | report,analysis | reader,aggregator,renderer,regression_check | success,report_input_missing | PASS | `reports/report_index.json` | `tests/report/test_report_rendering.py` | absent inputs rendered with reasons | Report integration happens now. |

## 11. Stage-specific Gates 设计

Add `scripts/assert_fault_timeline_contract.py` with two modes:

```bash
PYTHONPATH=src python3 scripts/assert_fault_timeline_contract.py --fixtures tests/fixtures/fault_timeline
PYTHONPATH=src python3 scripts/assert_fault_timeline_contract.py \
  --artifacts-dir runs/m1-s06-local/artifacts \
  --analysis runs/m1-s06-local/artifacts/analysis_summary.json \
  --report-index runs/m1-s06-local/reports/report_index.json \
  --require-fault-types primary_stop_failover,replica_stop,node_host_stop,az_stop,network_delay,network_loss,network_flap,network_partition,minority_partition,majority_partition,split_brain_window_detection,fault_period_workload_impact \
  --require-scales small,30,50,100,200
```

The gate must check:

- `fault_timeline_events.jsonl` is non-empty.
- Every fault row has all 12 events, with observed or structured reason status.
- Every fault row has apply/recovery/clear/cleanup evidence.
- `missing effect observed` rows include reason and impact.
- Failover latency samples reference timeline rows and derive from named events.
- Fault-period workload windows reference M1-S05-compatible metrics.
- Cleanup has PASS evidence or structured blocked-before-resource reason.
- Report index exposes fault timeline CSV/SVG/Markdown/HTML outputs.
- No host network mutation fields are true.

Proposed local commands:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m compileall -q scripts src
PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m pytest -q tests/unit tests/integration
PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m pytest -q tests/unit/test_fault_timeline_contract.py tests/unit/test_failover_timeline_observer.py tests/integration/test_failover_timeline_artifacts.py tests/analysis/test_analysis_summary.py tests/analysis/test_workload_impact_cross_stage.py tests/report/test_report_rendering.py
PYTHONPATH=src python3 scripts/assert_fault_timeline_contract.py --fixtures tests/fixtures/fault_timeline
PYTHONPATH=src python3 scripts/assert_fault_timeline_contract.py --artifacts-dir runs/m1-s06-local/artifacts --analysis runs/m1-s06-local/artifacts/analysis_summary.json --report-index runs/m1-s06-local/reports/report_index.json
PYTHONPATH=src python3 scripts/assert_failover_latency_curve.py --phase P20_FAILOVER_LATENCY_CURVE_30_50_100 --artifact-dir runs/m1-s06-local/artifacts
PYTHONPATH=src python3 scripts/assert_workload_impact.py --phase P25_FAULT_WORKLOAD_IMPACT_ANALYSIS
git diff --check
```

Real gate attempts, when resource preflight allows:

```bash
PYTHONPATH=src python3 scripts/fault_failover_timeline_gate.py \
  --phase P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY \
  --artifact-dir runs/m1-s06-local/artifacts/real_p44 \
  --scales 30,50,100,200 \
  --samples-per-scale 1 \
  --require-data-path

PYTHONPATH=src python3 scripts/fault_failover_gate.py \
  --phase P20_FAILOVER_LATENCY_CURVE_30_50_100 \
  --out runs/m1-s06-local/artifacts/real_p20/valkey_e2e_evidence.json \
  --failover-report runs/m1-s06-local/artifacts/real_p20/failover_report.json \
  --fault-report runs/m1-s06-local/artifacts/real_p20/fault_report.json \
  --workload-window-report runs/m1-s06-local/artifacts/real_p20/workload_window_report.json \
  --cleanup-report runs/m1-s06-local/artifacts/real_p20/cleanup_report.json \
  --config templates/configs/scale_30.yaml \
  --scenario scale_30_sample_01_fault_failover \
  --min-nodes 30 \
  --require-data-path
```

If these fail because of the known local sandbox port-bind issue, write `real_fault_failover_gate_blocked.json` and keep stage status as implementation-ready with real gate blocked evidence.

## 12. 风险与待验证点

- Scale 200 real runs are expensive and must pass resource preflight before execution. No default should become 200 or higher.
- Existing P44/P45 schemas and tests are intentionally strict for real evidence. M1-S06 should add a common M1 timeline contract without weakening P44/P45 real-only gates.
- Some fault types do not expect promotion. The design must distinguish `SKIPPED_WITH_REASON: promotion_expected=false` from missing failover evidence.
- Network delay/loss/flap and partition paths must use owned container namespace or sandbox proxy only. Review should scan for host firewall/routing/interface commands.
- Workload windows may be unavailable if the real gate is blocked before cluster setup. That is acceptable only with structured blocked reason and no fake QPS/latency values.
- Report integration must not be deferred to M1-S08; M1-S08 can polish visuals, but M1-S06 must already expose the fault timeline data and Chinese sections.
- Existing analysis currently requires `failover_report.json`; if fixtures only provide `fault_timeline_report.json`, the worker should either emit a compatibility `failover_report.json` or update analysis to support both while preserving old behavior.

## Clear Design Decision

Implement M1-S06 as a reusable fault timeline artifact contract shared by all fault/failover paths. The worker should add strict schemas, common writer/derivation helpers, fixtures across success/failure/timeout/missing/blocked/dry-run/cleanup/report-missing paths, analysis aggregation, Chinese offline report rendering, and a fail-closed stage gate. Primary stop RTO can be one producer of timeline rows, but the stage is not complete unless all listed fault types and all required scale rungs are represented by real evidence or structured blocked/skipped reasons.
