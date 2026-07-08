# M1-S05 Design Brief

Stage: M1-S05
Role: design subagent
Repository HEAD inspected: `e4427dc7a180651b778a965409152dc7abbc54ac`
Decision: IMPLEMENT BENCHMARK WORKLOAD AS A COMMON CONTRACT, NOT A P05-ONLY PATCH

## 1. 当前 Stage 目标复述

M1-S05 must keep the existing smoke workload and add a benchmark workload layer that can quantify performance impact before, during, and after management/fault/failover events. The benchmark contract must support these profiles: `smoke`, `uniform`, `hotspot`, `mixed_rw`, `write_heavy`, and `read_heavy`.

The stage must add a full-slot-capable key generator, low-intensity benchmark defaults for small clusters, benchmark metrics, referenceable workload-impact artifacts for management/fault/failover, schema validation, fixtures, analysis aggregation, Chinese offline report rendering, gates, and docs/coverage updates. Missing or unavailable values must be encoded as `MISSING`, `SKIPPED_WITH_REASON`, or `BLOCKED_WITH_REASON` with reasons.

## 2. 当前仓库中相关代码路径

- Workload runtime: `src/valkey_scale_lab/workload/__init__.py`
- Metric helpers: `src/valkey_scale_lab/metrics/__init__.py`
- Runtime writers and real scenario hooks: `src/valkey_scale_lab/runtime/docker_runtime.py`
- CLI scenario/analyze/report entrypoints: `src/valkey_scale_lab/cli.py`
- Config schema/validation: `schemas/config/run_config.schema.json`, `src/valkey_scale_lab/config/validation.py`
- Artifact schemas: `schemas/artifact/workload_report.schema.json`, `schemas/artifact/workload_windows.schema.json`, `schemas/artifact/workload_impact_report.schema.json`, `schemas/artifact/workload_impact_cross_stage.schema.json`, `schemas/artifact/management_ops_matrix.schema.json`, `schemas/artifact/management_operation_result.schema.json`
- Management workload refs: `src/valkey_scale_lab/management_matrix.py`, `src/valkey_scale_lab/runtime/docker_runtime.py`
- Analysis readers/aggregators: `src/valkey_scale_lab/analysis/summary.py`, `src/valkey_scale_lab/analysis/workload_impact.py`
- Chinese/offline renderer: `src/valkey_scale_lab/report/render.py`, final report reader in `src/valkey_scale_lab/report/final.py`
- Existing workload gates/tests: `scripts/assert_workload_impact.py`, `scripts/audit_small_real_scenario_parity.py`, `tests/analysis/test_workload_impact_cross_stage.py`, `tests/report/test_report_rendering.py`, `tests/real_valkey/test_small_real_gate_contract.py`
- Previous stage artifacts to preserve: `runs/m1-s04-local/artifacts/goal_loop/M1-S04/HANDOFF.md`, `COMPLETION.md`, `REVIEW.md`

Current gaps observed:

- `run_windowed_workload()` uses fixed hash-tag keys like `{vslab-p16}`, so it does not prove full-slot distribution.
- `write_workload_report()` is P05 smoke-oriented and does not emit benchmark profiles, canonical `workload_windows.json`, full-slot coverage evidence, or management/fault/failover reference metadata.
- `workload_windows.schema.json` permits generic metric objects and only requires `window_name`, refs, and `metrics`; it does not enforce benchmark profile/config/key-slot evidence.
- `create_analysis_summary()` does not aggregate first-class workload benchmark rows into `analysis_summary.json`.
- `render_report()` writes management CSVs/SVGs, but lacks a Chinese workload benchmark section with QPS, p99, error-rate comparison, and full-slot coverage statement.

## 3. 需要修改的通用路径

Implement through shared runtime paths, not a stage-specific one-off:

- Extend `src/valkey_scale_lab/workload/__init__.py` with:
  - `WorkloadProfile` or plain structured profile builder for all six profiles.
  - `slot_for_key()` CRC16 hash-slot helper compatible with Valkey Cluster hash tags.
  - `generate_benchmark_keys()` that can intentionally cover all 16384 slots when `hash_slot_distribution=full_slot`.
  - `run_benchmark_workload()` that wraps smoke and benchmark modes and returns events, metric rows, window rows, profile metadata, and key-slot coverage evidence.
- Update `src/valkey_scale_lab/runtime/docker_runtime.py` writers:
  - P05 `write_workload_report()` should continue writing `workload_report.json` for backward compatibility and also write/use the canonical benchmark contract.
  - P16/P29 `write_goal_loop_quant_telemetry_artifacts()` should call the common benchmark runner and include profile/key-slot fields in `workload_windows.json`.
  - P17/P18/P19 and P30/P31/P32 management writers should keep existing operation refs but point `workload_window_ref`/`workload_impact_ref` at benchmark windows with operation IDs.
  - P20/P21/P22/P23/P24/P33/P34/P35 fault/failover writers in `scripts/fault_failover_gate.py` should emit the same fields or explicit structured skipped reasons when old window names are being bridged.
- Update `src/valkey_scale_lab/management_matrix.py` fixture writer so fake fixtures are not ahead of runtime-only fields.

## 4. Schema 传播计划

Schema changes should be common and strict enough to catch partial implementation:

- `schemas/config/run_config.schema.json`: define workload fields from the stage file:
  - `enabled`, `mode` (`smoke`, `benchmark`), `profiles`, `target_qps`, `duration_seconds`, `warmup_seconds`, `connections`, `pipeline`, `keyspace`, `value_size`, `hash_slot_distribution`, `read_ratio`, `write_ratio`, `timeout_ms`.
  - Accept legacy `uniform_qps`, `hotspot_qps`, `hotspot_key_fraction`, and `timing` for compatibility, but normalize them into benchmark fields.
- `src/valkey_scale_lab/config/validation.py`: validate:
  - profile in the six allowed profiles.
  - ratios sum to 1.0.
  - low-intensity profiles are allowed for small clusters.
  - `duration_seconds`, `warmup_seconds`, `connections`, `pipeline`, `keyspace`, `value_size`, `timeout_ms` are positive where required.
  - `hash_slot_distribution` enum includes at least `single_tag`, `multi_slot`, `full_slot`, `hotspot`.
- `schemas/artifact/workload_windows.schema.json`: require top-level `workload_mode`, `profiles_covered`, `hash_slot_coverage`, and per-window fields:
  - `profile`, `workload_mode`, `operation_id` or `sample_id` when linked, `window_name`, refs, `status`, `metrics`, `key_slot_coverage`, `config`.
  - Metrics must include stage fields: `requested_qps`, `achieved_qps`, `throughput_ratio`, `ok_ops`, `error_ops`, `error_rate`, `latency_p50_ms`, `latency_p90_ms`, `latency_p95_ms`, `latency_p99_ms`, `latency_p999_ms`, `timeout_count`, `connection_error_count`, `moved_count`, `ask_count`, `cluster_down_count`, `readonly_count`, `tryagain_count`.
  - Keep aliases for current names (`moved_redirection_count`, etc.) during transition, but gates should enforce canonical names and alias consistency.
- `schemas/artifact/workload_report.schema.json`: add benchmark summary fields: `workload_mode`, `profiles`, `canonical_window_refs`, `hash_slot_coverage`, `benchmark_metrics`, `management_refs`, `fault_refs`, `failover_refs`.
- `schemas/artifact/workload_impact_report.schema.json` and `workload_impact_cross_stage.schema.json`: add profile, slot coverage, and derived fields for QPS ratio, p99 delta, and error-rate delta.

## 5. Artifact Writer 传播计划

Writers must produce both source artifacts and referenceable impact artifacts:

- `src/valkey_scale_lab/workload/__init__.py`
  - Return `workload_windows` rows for `baseline`, `pre_event`, `event`, `recovery`, `post_recovery`, `all_run`.
  - Include `profile`, `workload_mode`, `hash_slot_distribution`, `slot_count_observed`, `slot_sample`, `full_slot_requested`, `full_slot_covered`, and `fixed_hash_tag_only=false` for benchmark paths.
  - Compute `throughput_ratio = achieved_qps / requested_qps` when possible; otherwise `MISSING` with reason.
- `src/valkey_scale_lab/runtime/docker_runtime.py`
  - P05: write `workload_report.json`, `workload_windows.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `quant_summary.json`, and preserve `valkey_e2e_evidence.json` behavior through the wrapper.
  - P16/P29: upgrade existing window rows without losing telemetry metrics.
  - P17/P18/P19/P30/P31/P32: use common window rows keyed by `operation_id`; `management_workload_impact.json` should aggregate benchmark windows, not ad hoc baseline/during fields only.
  - P20/P21/P22/P23/P24/P33/P34/P35: rows keyed by `sample_id`/`fault_id`; `fault_workload_impact.json` and `workload_impact_report.json` include benchmark refs and profile/slot evidence.
- Cleanup/failure writers:
  - If benchmark command fails, emit a non-empty `events.jsonl` and `metrics_timeseries.jsonl` with classified error counts and status `FAIL`.
  - If real local run is blocked by sandbox port bind, write `BLOCKED_WITH_REASON` artifact under `runs/m1-s05-local/artifacts/goal_loop/M1-S05/`.

## 6. Artifact Reader / Analyzer 传播计划

- `src/valkey_scale_lab/analysis/summary.py`
  - Add `_workload_aggregates()` reading `workload_windows.json`, `workload_report.json`, and `management_workload_impact.json` if present.
  - Add findings named `workload_benchmark` and metrics for aggregate requested/achieved QPS, throughput ratio, p99, error rate, profile coverage, full-slot coverage, and missing counts.
  - Include workload missing metrics in `_collect_missing_metrics()`.
- `src/valkey_scale_lab/analysis/workload_impact.py`
  - Preserve existing P17-P24 cross-stage contract.
  - Add profile and slot coverage fields to each row.
  - Derive `fault_or_operation_qps_ratio`, `latency_p99_delta_ms`, and `error_rate_delta` from benchmark metrics and record missing reasons per row.
  - Accept both management/fault/failover source refs, but never parse rendered reports as metric sources.

## 7. 中文 Report Renderer 传播计划

- `src/valkey_scale_lab/report/render.py`
  - Add offline outputs:
    - `workload_benchmark_windows.csv`
    - `workload_profile_summary.csv`
    - `workload_qps_p99_error.svg`
  - Add `workload_report_inputs` to `report_index.json` with refs to `workload_windows.json`, `workload_report.json`, and workload-impact artifacts.
  - Add Chinese Markdown/HTML sections:
    - `## Workload Benchmark` should be changed or paired with Chinese title `## Workload 基准压测`
    - Show `baseline / event / recovery / post_recovery` QPS, p99, error_rate comparison.
    - Show `profile` coverage and state whether `hash_slot_distribution=full_slot` covered all slots or why it was skipped.
    - When report inputs are missing, show `SKIPPED_WITH_REASON`/`MISSING` reason in Chinese.
- `src/valkey_scale_lab/report/final.py`
  - Preserve P25/P26 final-report workload impact rows, but include profile and slot coverage columns in exports when present.

## 8. Fake Fixture / Smoke / Integration / Real Path 覆盖计划

Fixtures:

- Add `tests/fixtures/workload_benchmark/success/` with one fixture per profile.
- Add blocked/failure/dry-run/missing-metric/cleanup-residual fixtures:
  - `tests/fixtures/workload_benchmark/blocked/`
  - `tests/fixtures/workload_benchmark/failure/`
  - `tests/fixtures/workload_benchmark/dry_run_200_plus/`
  - `tests/fixtures/workload_benchmark/missing_metric/`
  - `tests/fixtures/workload_benchmark/cleanup_residual/`
- Update management fixtures under `tests/fixtures/management_matrix/{success,scale_30,scale_50,scale_100,scale_200,dry_run_200_plus,blocked,...}` so `management_workload_impact.json` and `workload_windows.json` carry benchmark metadata or structured skipped reasons.

Tests:

- Unit:
  - `tests/unit/test_workload_benchmark.py`: profile normalization, ratio validation, latency/error taxonomy, throughput ratio, no empty JSONL.
  - `tests/unit/test_workload_key_generator.py`: CRC16 slot calculation, full-slot generator covers 0-16383, uniform profile covers multiple slots, hotspot concentrates as configured, fixed hash tag is not sole benchmark path.
- Artifact/schema:
  - `tests/artifacts/test_workload_benchmark.py`: validate fixture artifacts against workload schemas.
  - Extend `tests/artifacts/test_management_matrix.py` for benchmark workload refs.
- Integration:
  - `tests/integration/test_workload_benchmark_contract.py`: run common writer with fake command callback and verify schema -> writer -> reader -> aggregator -> renderer path.
  - Extend `tests/integration/test_docker_runtime_contract.py` for P05 benchmark outputs without requiring heavy real run.
- Analysis/report:
  - Extend `tests/analysis/test_analysis_summary.py` and `tests/analysis/test_workload_impact_cross_stage.py`.
  - Extend `tests/report/test_report_rendering.py` for Chinese workload section, CSV/SVG outputs, and report index refs.
- Real/smoke:
  - `scripts/valkey_e2e_gate.py --phase P05_WORKLOAD_ENGINE --scenario workload_smoke` remains the real wrapper.
  - Add or update wrapper assertion so P05 evidence validates benchmark artifacts when environment permits.

## 9. Dry-run / Blocked / Failure / Cleanup Path 处理计划

- Dry-run and 200+:
  - Config/planner can describe benchmark profiles for `scale_200_plus_dry_run_planning`, but runtime must not execute >200 nodes. Artifact rows should be `SKIPPED_WITH_REASON` with reason: planning-only dry run, no workload executed.
- Blocked:
  - Real local gate blocked by sandbox port binding must write `BLOCKED_WITH_REASON`, stderr/stdout refs, command, stage ID, and impact. No fake Valkey PASS.
- Failure:
  - Simulate command exceptions in unit/integration tests and require non-empty workload events/metrics with error classification fields.
  - `timeout_count`, `connection_error_count`, `moved_count`, `ask_count`, `cluster_down_count`, `readonly_count`, and `tryagain_count` must be counted or explicitly zero.
- Cleanup:
  - Benchmark worker should not leave background processes. If future implementation uses a threaded/process workload runner, it needs deterministic stop/join state and cleanup evidence.
  - Cleanup report references must be carried into `quant_summary.json` and report index when benchmark failed or was blocked.

## 10. Coverage Matrix 草案

| change_id | field_or_behavior | execution_shape | scale_rung | functional_path | data_path | outcome_class | required evidence |
|---|---|---|---|---|---|---|---|
| workload_profiles | six profiles plus smoke/benchmark distinction | fake, unit, integration, smoke, real_local_run, blocked_run | small, 30, 50, 100, 200, 200+ dry-run | config, workload, metrics | schema, writer, fixture, gate | success, missing_metric | schema validation, profile fixtures, P05/P16/P30/P33 refs |
| full_slot_generator | full-slot and multi-slot key evidence | unit, integration, smoke, real_local_run, dry_run | small, 30, 50, 100, 200 | workload | writer, regression_check | success, command_failure | slot coverage object proves not fixed hash-tag-only |
| benchmark_metrics | QPS, throughput ratio, latency p50/p90/p95/p99/p999, error taxonomy | fake, unit, integration, smoke, real_local_run, blocked_run | all rungs | workload, metrics, analysis, report | schema, writer, reader, aggregator, renderer | success, timeout, missing_metric | non-empty JSONL, aggregate metrics, Chinese report |
| workload_impact_refs | operation/fault/failover refs into benchmark windows | integration, smoke, real_local_run, blocked_run | small, 30, 50, 100, 200 | management_ops, fault, failover | writer, reader, aggregator, renderer | success, report_input_missing | `operation_id`/`sample_id` window refs in source artifacts |
| zh_report_workload | offline Chinese benchmark section | fake, integration, smoke | all rungs represented by fixtures | report, analysis | reader, aggregator, renderer, regression_check | success, report_input_missing | CSV, SVG, Markdown/HTML Chinese text |

The main agent should update `runs/m1-s05-local/artifacts/goal_loop/M1-S05/coverage_matrix.md` from `BLOCKED_WITH_REASON` to PASS/SKIPPED/BLOCKED based on actual gate results, not by assumption.

## 11. Stage-specific Gates 设计

Add `scripts/assert_workload_benchmark_contract.py` with two modes:

- `--fixtures tests/fixtures/workload_benchmark`
  - Requires all six profiles.
  - Validates schemas.
  - Rejects empty JSONL.
  - Rejects missing reasons without reason.
- `--artifacts-dir <dir> --analysis <analysis_summary.json> --report-index <report_index.json>`
  - Validates `workload_windows.json`, `workload_report.json` when present, workload metrics JSONL, impact refs, analysis fields, report CSV/SVG/Markdown/HTML refs.
  - Ensures `uniform` covers multiple slots and `full_slot` covers all 16384 slots or is `SKIPPED_WITH_REASON`.
  - Ensures fixed hash tag is not the only benchmark path.
  - Ensures management/fault/failover workload refs resolve to real artifact rows or structured skipped rows.

Proposed commands:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m compileall -q scripts src
PYTHONPATH=src python3 -m pytest -q tests/unit tests/integration
PYTHONPATH=src python3 -m pytest -q tests/unit/test_workload_benchmark.py tests/unit/test_workload_key_generator.py tests/artifacts/test_workload_benchmark.py tests/analysis/test_analysis_summary.py tests/analysis/test_workload_impact_cross_stage.py tests/report/test_report_rendering.py
PYTHONPATH=src python3 scripts/assert_workload_benchmark_contract.py --fixtures tests/fixtures/workload_benchmark
PYTHONPATH=src python3 scripts/assert_workload_benchmark_contract.py --artifacts-dir runs/m1-s05-local/artifacts --analysis runs/m1-s05-local/artifacts/analysis_summary.json --report-index runs/m1-s05-local/reports/report_index.json
PYTHONPATH=src python3 scripts/assert_management_matrix_m1.py --fixtures tests/fixtures/management_matrix
PYTHONPATH=src python3 scripts/assert_workload_impact.py --phase P25_FAULT_WORKLOAD_IMPACT_ANALYSIS
git diff --check
```

Real/smoke attempt, if environment permits:

```bash
PYTHONPATH=src python3 scripts/valkey_e2e_gate.py --phase P05_WORKLOAD_ENGINE --scenario workload_smoke
```

If blocked, capture stdout/stderr and write `runs/m1-s05-local/artifacts/goal_loop/M1-S05/real_heavy_gate_blocked.json` with `status=BLOCKED_WITH_REASON`.

## 12. 风险与待验证点

- Full-slot generation can be expensive if it performs one operation per slot per window. The design should separate generated key coverage evidence from low-intensity benchmark execution: a small run can prove generator coverage while sampling a bounded subset for actual operations.
- Valkey Cluster redirections require `valkey-cli -c` or equivalent client behavior. The writer should classify MOVED/ASK rather than masking redirection errors.
- Existing P17-P24/P30-P35 artifacts use both `workload_windows.json` and `workload_impact_report.json`; implementation must preserve old readers while adding fields.
- Metric aliases are inconsistent today: `moved_redirection_count` vs `moved_count`, `cluster_down_error_count` vs `cluster_down_count`. M1-S05 should either write both with consistency checks or migrate schemas/gates carefully.
- Existing `workload_windows.schema.json` phase pattern only accepts `P...` IDs; M1 run artifacts may use `M1-S05`. Either keep runtime artifacts under P phase IDs or intentionally widen schema without weakening validation.
- Report integration must be done in this stage. A report-only future defer is not acceptable.

## Clear Design Decision

Implement M1-S05 by promoting workload benchmark semantics into the common workload module and canonical artifact schemas, then wire that same contract through runtime writers, fixtures, analysis, Chinese report rendering, and gates. Do not add an M1-S05-only script that merely fabricates benchmark fields; the worker should make benchmark workload a reusable artifact contract for smoke, management, fault, failover, real, dry-run, blocked, failure, and cleanup paths.
