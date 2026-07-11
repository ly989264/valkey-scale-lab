# DESIGN_BRIEF — P25_FAULT_WORKLOAD_IMPACT_ANALYSIS

## Objective

Consolidate workload impact from P17-P24 into machine-readable cross-stage artifacts and CSV exports. P25 must derive QPS, latency, error-rate, and recovery-duration comparisons only from existing JSON/JSONL artifacts; it must not rerun P17-P24 scenarios or parse logs for report numbers. The stage still preserves the manifest real-Valkey smoke gate for current-stage evidence and cleanup.

## Repository findings

- `codex/phase_manifest.json` already defines P25 as automatic, real-Valkey required, max 100, with gates for precheck, safety scan, compile, unit/integration tests, goal-loop assertion, `scripts/valkey_e2e_gate.py`, quant assertion, workload-impact assertion, and cleanup assertion.
- P25 required manifest artifacts are common real-stage files plus `workload_impact_cross_stage.json`, `csv_export_index.json`, and `missing_data_summary.json`. The stage doc additionally requires the CSV files `workload_impact_by_operation.csv`, `workload_impact_by_fault.csv`, `latency_delta_table.csv`, `error_delta_table.csv`, and `recovery_duration_table.csv`.
- `src/valkey_scale_lab/analysis/summary.py` only supports the older P09 single-source `analysis_summary.json`. `src/valkey_scale_lab/cli.py analyze` only calls that path today, so P25 needs either a backward-compatible analyze mode or a dedicated builder script.
- P17-P19 management stages provide per-operation windows in `workload_windows.json` keyed by `operation_id`, and operation metadata in `management_operation_results.jsonl`. `management_workload_impact.json` is more aggregate and should not be the only source for per-operation rows.
- P20-P21 failover stages provide per-sample windows in `workload_impact_report.json`, with sample metadata in `failover_latency_samples*.jsonl` and curve/report artifacts. P20 comparisons are mostly refs, so P25 should recompute common deltas from windows rather than trusting precomputed fields.
- P22-P24 fault stages provide per-sample `workload_impact_report.json` plus `fault_results.jsonl`. P22 includes 6, 10, and 30-node rows; P23/P24 appear to include 6/10 mandatory rows. Exact row counts are 待验证.
- `scripts/assert_workload_impact.py` currently has strong P20-P24 checks and P24 corrected error-taxonomy checks, but P25 only receives loose generic validation through `workload_impact_cross_stage.schema.json`; it does not yet enforce source-stage representation, source refs, CSV row counts, or traceability.
- `scripts/assert_quant_artifacts.py` has detailed P16 and P20-P24 semantic checks but no P25-specific checks.
- Existing schemas for `workload_impact_cross_stage`, `missing_data_summary`, and `csv_export_index` are intentionally loose. They validate artifact type and top-level presence, but not P25-specific row semantics.
- `scripts/valkey_e2e_gate.py` writes `valkey_e2e_evidence.json` and `cleanup_report.json`; it does not generate P25 analysis artifacts, `events.jsonl`, `metrics_timeseries.jsonl`, or `workload_windows.json`. The P25 worker needs an analysis generation gate that writes those without overwriting real smoke evidence or cleanup.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `src/valkey_scale_lab/analysis/workload_impact.py` | Add | Implement P25 cross-stage loader, normalizer, derived metric calculator, missing-data collector, common artifact writer, and CSV exporter. |
| `src/valkey_scale_lab/analysis/__init__.py` | Update | Export the P25 builder and error type. |
| `src/valkey_scale_lab/cli.py` | Update | Add a backward-compatible `analyze --kind workload-impact` or equivalent option that calls the P25 builder while preserving current `analyze --input ... --out ...` behavior. |
| `codex/phase_manifest.json` | Update | Add a P25 analysis-generation gate before `quant_artifact_assertion`; ensure required artifacts and gate order match generated outputs. |
| `codex/gate_lock.json` | Update | Refresh harness lock entries only because manifest/scripts/schemas are strengthened; do not weaken lock coverage. |
| `schemas/artifact/workload_impact_cross_stage.schema.json` | Strengthen | Require P25 top-level structure such as `source_stage_statuses`, `rows`, `row_counts`, `csv_exports`, and traceability fields. |
| `schemas/artifact/missing_data_summary.schema.json` | Strengthen | Require source stage, source artifact, pointer/sample/window identifiers where applicable. |
| `schemas/artifact/csv_export_index.schema.json` | Strengthen | Require export path, role/table name, row count, JSON source count, source artifact, and sha256. |
| `scripts/assert_workload_impact.py` | Update | Add P25-specific fail-closed checks for source coverage, derivation from artifacts, canonical window presence per included row, CSV/JSON row parity, and P24 taxonomy preservation. |
| `scripts/assert_quant_artifacts.py` | Update | Add P25 checks for common artifact counts, source-stage coverage, quant summary consistency, missing-data reasons, and no false management/fault runtime claim for P25 itself. |
| `tests/analysis/test_workload_impact_cross_stage.py` | Add | Unit-test normalization, delta calculation, missing encoding, CSV exports, source refs, and no log parsing/rerun dependency. |
| `tests/unit/test_goal_loop_assertions.py` | Update | Add P25 assertion pass/fail fixtures for missing source stage, missing reason, CSV row mismatch, missing source refs, and P24 taxonomy regression. |
| `tests/unit/test_cli_contract.py` | Update | Cover the new analyze mode and preserve existing analyze command behavior. |
| `tests/integration/test_goal_loop_manifest.py` | Update if needed | Assert P25 manifest includes the generation gate before assertion gates. |
| `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/*` | Generate | P25 gate outputs: cross-stage JSON, CSVs, missing summary, common artifacts, quant summary, smoke evidence, cleanup. |

## Implementation plan

1. Add a P25 analysis builder that accepts a source phases root, output directory, stage id, and run id. It should load only P17-P24 JSON/JSONL artifacts and never call runtime/fault scripts or read `.log` files.
2. Define source stage specs in code: P17-P19 management (`workload_windows.json` + `management_operation_results.jsonl`), P20 (`workload_impact_report.json` + `failover_latency_samples.jsonl`), P21 (`workload_impact_report.json` + `failover_latency_samples_200.jsonl`), P22-P24 (`workload_impact_report.json` + `fault_results.jsonl` plus stage reports where useful for metadata).
3. Normalize each included comparison entity into one cross-stage row:
   - management: `operation_id`, `operation_name`, `node_count`, `operation_status`;
   - failover/fault: `sample_id`, `fault_type`, `node_count`, `fault_id` where available;
   - all rows: `source_stage_id`, category, source artifact path(s), source line/pointer/ref, source window IDs, and status.
4. For every row, require canonical windows `baseline`, `event`, `recovery`, `post_recovery`; keep `pre_event` and `all_run` refs when present. Missing windows become `MISSING` rows with explicit reasons unless the source stage itself is absent, in which case the source stage is represented as `MISSING`.
5. Compute derived values from window metrics, not from report prose or logs:
   - `fault_or_operation_qps_ratio = event.achieved_qps / baseline.achieved_qps`;
   - `latency_p50/p95/p99_delta_ms = event - baseline`;
   - `error_rate_delta = event.error_rate - baseline.error_rate`;
   - `recovery_duration_ms` from recovery `duration_seconds`, or recovery start/end timestamps when available, otherwise `MISSING` with reason;
   - `post_recovery_qps_ratio = post_recovery.achieved_qps / baseline.achieved_qps`.
6. Preserve error taxonomy fields from source metrics: timeout, connection, MOVED, ASK, CLUSTERDOWN, READONLY, TRYAGAIN, unknown, and total `error_ops`. For P24 rows, keep the corrected taxonomy invariant that classified error counts match `error_ops` where that source invariant applies; do not collapse CLUSTERDOWN into unknown.
7. Write `workload_impact_cross_stage.json` with source stage statuses, source artifact sha256s, rows, row counts, CSV export metadata, derivation rules, and missing-data summary refs.
8. Write required CSVs from the JSON rows:
   - operation CSV: management rows only;
   - fault CSV: failover and fault rows only;
   - latency/error/recovery CSVs: all included comparison rows.
   Record exact row counts in `csv_export_index.json`; assertions must compare each CSV count with the corresponding JSON count.
9. Write `missing_data_summary.json` from all missing/skipped/unsupported findings, including source stage, artifact, field, sample/window/operation ID, and reason.
10. Write P25 common artifacts around analysis execution: `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `phase_summary.json`, and `quant_summary.json`. These should describe the analysis run and derived metrics, while `valkey_e2e_evidence.json` and `cleanup_report.json` remain produced by the real smoke gate.

## Harness, schema, and gate plan

- Add a manifest gate such as `p25_workload_impact_analysis` after `real_valkey_e2e` and before `quant_artifact_assertion`. Candidate command:
  `python3 -m valkey_scale_lab.cli analyze --kind workload-impact --input artifacts/phases --out-dir artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS --phase P25_FAULT_WORKLOAD_IMPACT_ANALYSIS`.
- Keep the existing `real_valkey_e2e` gate. It proves current-stage Valkey 9.1.x endpoints and cleanup, but P25 comparison numbers must still cite P17-P24 source artifacts only.
- Strengthen `assert_workload_impact.py` for P25 to require:
  - all source stages P17-P24 represented or explicitly missing with reason;
  - each non-missing source row has source artifact path(s), sha256, and sample/window/operation refs;
  - no derived metric is numeric when source value is `MISSING`;
  - canonical windows are present or missing with reason per row;
  - CSV counts match JSON row counts;
  - P24 error taxonomy fields are preserved and CLUSTERDOWN samples remain classified.
- Strengthen `assert_quant_artifacts.py` for P25 to require:
  - common artifact files exist and validate;
  - `quant_summary.artifact_refs` cites every P25 required artifact and source-stage families used;
  - counts in `quant_summary` match events/metrics line counts and cross-stage row counts;
  - `runtime_claims.real_valkey_claimed` is true for the P25 smoke evidence, while P25 does not claim it reran management/fault runtime behavior.
- Tighten schemas enough to catch malformed top-level P25 artifacts, but leave relational invariants to assertion scripts.
- Update `codex/gate_lock.json` only after strengthening manifest/scripts/schemas so precheck remains meaningful.

## Test plan

- Unit tests for the P25 builder:
  - builds rows from minimal P17 management fixtures with operation windows;
  - builds rows from P20/P21 failover fixtures and computes deltas from windows;
  - builds rows from P22-P24 fault fixtures and preserves taxonomy counts;
  - emits `MISSING` with reason for absent windows, absent source stage, zero baseline denominator, and missing latency percentiles;
  - writes all CSVs and `csv_export_index.json` with matching row counts.
- Assertion tests:
  - `assert_workload_impact.py --phase P25...` passes for a complete fixture;
  - fails on missing P17-P24 representation;
  - fails on CSV row mismatch;
  - fails on row without source artifact/pointer/sample/window refs;
  - fails when P24 event `error_ops` differs from taxonomy sum or CLUSTERDOWN is lost.
- CLI tests:
  - existing `analyze --input ... --out ...` behavior remains intact;
  - new P25 analyze mode creates the expected artifact set in a temp output directory.
- Manifest/gate tests:
  - P25 includes the analysis generation gate before quant/workload assertions;
  - P25 still has real-Valkey smoke gate and cleanup assertion.
- Focused local commands for the worker:
  - `python3 -m pytest -q tests/analysis tests/unit/test_goal_loop_assertions.py tests/unit/test_cli_contract.py tests/integration/test_goal_loop_manifest.py`
  - `python3 -m compileall -q scripts src`
  - `python3 scripts/assert_workload_impact.py --phase P25_FAULT_WORKLOAD_IMPACT_ANALYSIS`
  - `python3 scripts/assert_quant_artifacts.py --phase P25_FAULT_WORKLOAD_IMPACT_ANALYSIS`

## Required artifacts

P25 must produce at least:

- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/phase_summary.json`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/valkey_e2e_evidence.json`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/cleanup_report.json`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/events.jsonl`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/metrics_timeseries.jsonl`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/workload_windows.json`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/quant_summary.json`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/workload_impact_cross_stage.json`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/workload_impact_by_operation.csv`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/workload_impact_by_fault.csv`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/latency_delta_table.csv`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/error_delta_table.csv`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/recovery_duration_table.csv`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/csv_export_index.json`
- `artifacts/phases/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS/missing_data_summary.json`

## Safety considerations

- P25 analysis must not invoke P17-P24 gate wrappers, runtime scenario creation, fault injection, Docker network operations, host networking commands, or log parsing for metrics.
- The only runtime side effect should be the existing P25 6-node real-Valkey smoke gate through owned project controls; cleanup must pass with no remaining owned resources.
- CSVs are report views over JSON and must not become source of truth. `csv_export_index.json` should cite `workload_impact_cross_stage.json` as the JSON source.
- Do not invent values for absent windows, absent samples, missing percentiles, or division-by-zero denominators. Use `MISSING`/`SKIPPED_WITH_REASON` with reasons.
- Avoid overwriting P25 `valkey_e2e_evidence.json` or `cleanup_report.json` produced by the real smoke gate when the analysis builder writes its artifacts.

## Resource considerations

- P25 should not run 30/50/100/200-node source scenarios. It reads existing artifacts and therefore has low CPU/memory cost.
- The real smoke gate remains a 6-node current-stage proof; it is bounded by `templates/configs/single_mac_6node.yaml` and existing cleanup logic.
- CSV/JSON generation may read large P20-P24 artifacts but should stream JSONL where reasonable. Current artifact sizes appear modest enough for in-memory JSON loads, but streaming JSONL is still cleaner.

## `待验证`

- Exact source row counts for P22, P23, and P24 after loading their complete source artifacts.
- Whether P21 source artifacts are always present in the worker environment or need an explicit source-stage `MISSING` row if a previous run is absent.
- Whether P25 should include P17-P19 aggregate `management_workload_impact.json` as a cited secondary artifact, or only per-operation `workload_windows.json` plus `management_operation_results.jsonl`.
- Whether strengthening `workload_impact_cross_stage.schema.json` will require adjusting any P15-era tests that assumed the schema was intentionally permissive.
- Whether `codex_gate.py` postcheck requires `csv_export_index.json` to cite the CSV paths in audit text even though raw CSVs are not manifest `required_artifacts`.
- Whether the new CLI mode should be `analyze --kind workload-impact` or a separate script invoked by the manifest while sharing package implementation.

## Worker instructions

- Implement only P25.
- Do not commit.
- Do not weaken harness or safety rules.
- Keep all P25 comparison numbers traceable to P17-P24 JSON/JSONL artifact paths and sample/window/operation identifiers.
- Preserve P24 corrected workload error taxonomy.
- Keep the P25 real-Valkey smoke evidence and cleanup artifacts separate from cross-stage analysis outputs.
