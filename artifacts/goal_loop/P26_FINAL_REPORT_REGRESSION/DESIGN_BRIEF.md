# DESIGN_BRIEF - P26_FINAL_REPORT_REGRESSION

## Objective

Generate the final P26 report package and regression hardening from versioned JSON/JSONL artifacts only. The stage must produce machine-readable indexes, Markdown reports, CSV exports, common quant artifacts, and fail-closed checks proving required management, failover, fault, and workload-impact rows remain present. P26 must not rerun P17-P25 source scenarios, must keep P14 opt-in, and must not invent missing metrics.

## Repository findings

- `src/valkey_scale_lab/report/render.py` is P09-specific. It renders `analysis_summary.json` into generic metrics tables/HTML/Markdown and writes a P09 `report_index`; it is not shaped for the P26 management/fault/failover/workload report set.
- `src/valkey_scale_lab/analysis/workload_impact.py` already implements artifact-only P25 consolidation across P17-P24 and emits 49 source-derived rows plus CSV exports and missing-data summary. P26 should reuse these artifacts rather than recomputing workload impact from logs.
- `codex/phase_manifest.json` has P26 with common gates, real smoke gate, `assert_quant_artifacts.py`, and cleanup check. It does not yet run a final report generation command or a final report regression assertion, and it does not require the Markdown/CSV files listed in the stage document.
- `schemas/artifact/final_report_index.schema.json` exists but is permissive. It requires only basic `reports` and `source_artifacts` fields. It should be strengthened to encode report/export coverage and provenance.
- `schemas/artifact/csv_export_index.schema.json` can already describe table exports. It may be sufficient if P26 exports carry table names and row/json counts, but exact coverage semantics need a P26 assertion.
- `scripts/assert_quant_artifacts.py` has detailed stage-specific checks through P25 only. P26 currently receives only common schema/existence checks.
- `scripts/assert_management_ops_coverage.py`, `scripts/assert_failover_latency_curve.py`, `scripts/assert_fault_matrix_coverage.py`, and `scripts/assert_workload_impact.py` are strong source-stage assertions but mostly return "not required" for P26. P26 needs a cross-stage report guard that checks final output coverage, not just source-stage artifacts.
- P17-P19 management sources are `management_ops_matrix.json`, `management_operation_results.jsonl`, `management_workload_impact.json`, `management_topology_snapshots.jsonl`, and command/rolling/reshard sidecars.
- P04 contains the older real setup evidence for create/meet/add-replica style rows (`tree_fanout_meet_primaries`, `tree_fanout_meet_replicas`, `parallel_add_replicas`, plus slot assignment/convergence). P16 is real telemetry foundation but does not expose detailed setup operation rows. Mapping final `create_cluster`, `meet_nodes`, and `add_replica` rows exactly is `待验证`.
- P20/P21 provide raw failover samples and curves: P20 has 9 samples for 30/50/100, P21 has 3 samples for 200 and a combined `failover_latency_curve_combined_30_50_100_200.json`.
- P22-P24 provide fault rows through `fault_matrix_report.json`/`fault_results.jsonl`, with P23 `network_fault_report.json`, P24 `partition_report.json`, and P24 `split_brain_report.json`.
- No `artifacts/phases/P26_FINAL_REPORT_REGRESSION/` directory exists yet.
- CI currently runs precheck, P15 goal-loop assertion, safety scan, and unit tests. It does not yet run a P26 final report assertion.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `src/valkey_scale_lab/report/final.py` | add | Dedicated P26 artifact-only final report builder. |
| `src/valkey_scale_lab/report/__init__.py` | update | Export the final report builder/error without breaking existing P09 renderer exports. |
| `src/valkey_scale_lab/cli.py` | update | Add backward-compatible `report --kind final-goal-loop --input ... --out-dir ... --phase ...` or equivalent while preserving existing `report --analysis` behavior. |
| `scripts/assert_final_report_regression.py` | add | Fail-closed P26 assertion for required report/export rows, provenance, missing-data reasons, P14 boundary, and artifact-only derivation. |
| `scripts/assert_quant_artifacts.py` | update | Add P26 semantics for common quant counts, artifact refs, analysis-only runtime claims, and final report index/export references. |
| `scripts/assert_goal_loop_stage.py` | update if needed | Only if P26 manifest/report requirements need a stage-specific required-artifact check beyond manifest validation. |
| `schemas/artifact/final_report_index.schema.json` | strengthen | Require generator metadata, report/export entries, source artifact records with sha256, coverage summary, and derivation policy. |
| `schemas/artifact/csv_export_index.schema.json` | update if needed | Tighten only if existing schema cannot express P26 export index parity. |
| `codex/phase_manifest.json` | update | Add a P26 report-generation gate before assertions; add final report regression assertion; declare required P26 report/export artifacts with schemas where applicable. |
| `.github/workflows/codex-gates.yml` | update | Add a lightweight P26 final report regression/unit assertion step if committed P26 artifacts make it practical in CI. |
| `tests/report/test_final_report_regression.py` | add | Unit tests for final builder using fixture artifacts and mutation cases. |
| `tests/ci/test_final_report_regression_gate.py` | add | Test manifest gate order and assertion CLI behavior. |
| `tests/unit/test_goal_loop_assertions.py` | update if useful | Add focused failure cases for the new P26 assertion, such as missing required rows and fabricated view-sourced metrics. |
| `docs/codex/goal-loop/RUN_COMPLETE_LOOP_LOCALLY.md` or `docs/codex/goal-loop/RUNBOOK_PLACE_AND_LAUNCH.md` | add/update | Document running the complete loop locally and final P26 report locations. |
| `artifacts/phases/P26_FINAL_REPORT_REGRESSION/**` | generate | Required P26 common artifacts, final indexes, reports, exports, fixtures/golden summaries. |
| `artifacts/goal_loop/P26_FINAL_REPORT_REGRESSION/WORKER_SUMMARY.md` | generate later | Worker handoff after implementation. |

## Implementation plan

1. Add a P26 final report builder that loads only JSON/JSONL source artifacts from P04/P16-P25 and writes a normalized in-memory model with source refs and sha256s.
2. Build `reports/management_ops_matrix.md` and `exports/management_ops_matrix.csv` with rows for `create_cluster`, `meet_nodes`, `add_replica`, `remove_replica`, `remove_primary_drained`, `remove_failed_node`, `reshard_slot_range`, `reshard_with_keys`, `rebalance_after_imbalance`, `rolling_restart_replica_first`, and `rolling_restart_primary_safe`.
3. Build `reports/failover_latency_curve.md` and `exports/failover_latency_curve.csv` from P20/P21 raw samples and combined curve only. Require rungs 30, 50, 100, 200 and sample count 3 per rung.
4. Build `reports/fault_matrix.md` and `exports/fault_matrix.csv` from P20-P24 fault/failover/fault-result artifacts. Include primary stop failover, replica stop, node-host stop, AZ stop, network delay, network loss, network flap, network partition/minority/majority, split-brain window, and fault-workload-impact row references.
5. Build `reports/workload_impact.md` and `exports/workload_impact.csv` from P25 `workload_impact_cross_stage.json`; do not parse logs or rendered Markdown/CSV as metric sources.
6. Build `reports/final_goal_loop_report.md` summarizing source stages, row coverage, P14 opt-in preservation, P21 bounded 200-node exception, missing-data policy, cleanup status, and final automatic loop stop at P26.
7. Write `final_report_index.json` and, to satisfy the stage document wording, either also write `report_index.json` as the same object or update manifest/docs consistently to use the exact final index filename. Prefer emitting both if schema validation and assertions remain simple.
8. Write `csv_export_index.json`, `quant_summary.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, and `phase_summary.json` for P26. P26 workload windows should be `SKIPPED_WITH_REASON` analysis/report windows with reasons, like P25.
9. Add regression fixtures/golden summaries under the P26 artifact directory or a tests fixture path. Golden summaries should be compact machine-readable coverage snapshots, not copied large source artifacts.
10. Add a manifest gate sequence: real Valkey smoke first, final report generation second, quant/final-report assertions after generation, cleanup assertion last.

## Harness, schema, and gate plan

- Add manifest gate `p26_final_report_generation` before `quant_artifact_assertion`, e.g. `python3 -m valkey_scale_lab.cli report --kind final-goal-loop --input artifacts/phases --out-dir artifacts/phases/P26_FINAL_REPORT_REGRESSION --phase P26_FINAL_REPORT_REGRESSION`.
- Add manifest gate `final_report_regression_assertion`, e.g. `python3 scripts/assert_final_report_regression.py --phase P26_FINAL_REPORT_REGRESSION`, after generation and before cleanup check.
- Strengthen `final_report_index.schema.json` to require:
  - `artifact_type=final_report_index`;
  - `phase_id=P26_FINAL_REPORT_REGRESSION`;
  - `created_at`, `producer`, `status`, `generator_version`;
  - `derivation_policy` with `artifact_only=true`, `log_parsing=false`, `rendered_views_as_metric_sources=false`, `source_scenarios_rerun=false`;
  - `reports` entries for all required Markdown reports;
  - `exports` or `csv_export_index_ref` entries for all required CSV exports;
  - `source_artifacts` as objects with `path`, `sha256`, `artifact_type` or role;
  - `coverage_summary` counts for management, failover, fault, workload, missing data, and cleanup.
- Keep `csv_export_index.json` row counts equal to source row counts. Required tables: `management_ops_matrix`, `failover_latency_curve`, `fault_matrix`, `workload_impact`.
- `assert_final_report_regression.py` should fail if:
  - any required Markdown/CSV/index artifact is absent;
  - final reports cite values without source refs;
  - any measured metric source path is a rendered view (`.md`, `.html`, `.svg`, `.csv`) instead of JSON/JSONL;
  - required management rows disappear;
  - failover rungs 30/50/100/200 or 3 samples per rung disappear;
  - required fault rows disappear;
  - P25 workload-impact row coverage drops below expected source rows or loses P24 error taxonomy;
  - any `MISSING`, `SKIPPED_WITH_REASON`, or `UNSUPPORTED_WITH_REASON` lacks a reason;
  - `P14_SCALE_1000_OPTIN_DRYRUN` is automatic, P14 real evidence appears, or any P26 default exceeds 100 nodes;
  - cleanup report is missing, non-PASS, or has residual resources.
- `assert_quant_artifacts.py` P26 semantics should verify quant refs include every final report/export/index, common artifacts, real smoke evidence, and P17-P25/P04 source artifacts used by the final report.

## Test plan

- Unit test final builder with small synthetic P04/P17-P25 source artifacts and assert all required outputs are written.
- Unit test P26 builder rejects or marks with explicit missing reasons when a source artifact is absent; no blank/null/zero placeholder should represent missing data.
- Unit test management coverage mutation: remove `rolling_restart_primary_safe` or `add_replica` source row and ensure assertion fails.
- Unit test failover mutation: remove rung 200 or reduce a rung to two samples and ensure assertion fails.
- Unit test fault mutation: remove `network_flap`, `network_partition_minority`, or `split_brain_window_detection` and ensure assertion fails.
- Unit test workload mutation: remove a P25 row or source ref and ensure assertion fails.
- Unit test P14 boundary mutation: make P14 automatic or add fake P14 real evidence and ensure assertion fails.
- Integration/CI test manifest gate order: real smoke -> final report generation -> quant/final assertions -> cleanup.
- Run focused tests before full gates: `python3 -m pytest -q tests/report/test_final_report_regression.py tests/ci/test_final_report_regression_gate.py tests/unit/test_goal_loop_assertions.py`.
- Full required gates remain `python3 scripts/codex_gate.py run --phase P26_FINAL_REPORT_REGRESSION`, fresh review, postcheck, mark-complete.

## Required artifacts

P26 must produce at least:

```text
artifacts/phases/P26_FINAL_REPORT_REGRESSION/phase_summary.json
artifacts/phases/P26_FINAL_REPORT_REGRESSION/valkey_e2e_evidence.json
artifacts/phases/P26_FINAL_REPORT_REGRESSION/cleanup_report.json
artifacts/phases/P26_FINAL_REPORT_REGRESSION/events.jsonl
artifacts/phases/P26_FINAL_REPORT_REGRESSION/metrics_timeseries.jsonl
artifacts/phases/P26_FINAL_REPORT_REGRESSION/workload_windows.json
artifacts/phases/P26_FINAL_REPORT_REGRESSION/quant_summary.json
artifacts/phases/P26_FINAL_REPORT_REGRESSION/final_report_index.json
artifacts/phases/P26_FINAL_REPORT_REGRESSION/report_index.json
artifacts/phases/P26_FINAL_REPORT_REGRESSION/csv_export_index.json
artifacts/phases/P26_FINAL_REPORT_REGRESSION/reports/management_ops_matrix.md
artifacts/phases/P26_FINAL_REPORT_REGRESSION/reports/failover_latency_curve.md
artifacts/phases/P26_FINAL_REPORT_REGRESSION/reports/fault_matrix.md
artifacts/phases/P26_FINAL_REPORT_REGRESSION/reports/workload_impact.md
artifacts/phases/P26_FINAL_REPORT_REGRESSION/reports/final_goal_loop_report.md
artifacts/phases/P26_FINAL_REPORT_REGRESSION/exports/management_ops_matrix.csv
artifacts/phases/P26_FINAL_REPORT_REGRESSION/exports/failover_latency_curve.csv
artifacts/phases/P26_FINAL_REPORT_REGRESSION/exports/fault_matrix.csv
artifacts/phases/P26_FINAL_REPORT_REGRESSION/exports/workload_impact.csv
```

Recommended regression sidecars:

```text
artifacts/phases/P26_FINAL_REPORT_REGRESSION/regression/coverage_golden_summary.json
artifacts/phases/P26_FINAL_REPORT_REGRESSION/regression/source_artifact_manifest.json
artifacts/phases/P26_FINAL_REPORT_REGRESSION/regression/missing_data_rendering_cases.json
```

## Safety considerations

- P26 should be report generation plus the existing bounded real-Valkey smoke gate. It must not run 30/50/100/200-node scenarios again.
- No host networking, firewall, routing, interface mutation, or `sudo` should be introduced.
- The final report builder must treat rendered reports as views only. CSV/Markdown may be outputs, never measured metric sources.
- P14 must remain non-automatic and dry-run-only unless the user explicitly opts in with the existing environment guard.
- Any missing metric or absent source must be represented as `MISSING` or `SKIPPED_WITH_REASON` with a reason; never use `null`, empty string, or `0` to imply absence.

## Resource considerations

- P26 should consume committed artifacts and perform only lightweight parsing/rendering, plus the 6-node smoke gate already in the manifest.
- The 200-node data should be read from P21 artifacts only. P26 must not start 200 nodes or reinterpret that exception as a new default.
- CSV/Markdown generation should be deterministic and small enough for CI. Avoid embedding full raw JSONL content in Markdown reports; cite paths and summarize rows.
- Hashing source artifacts is acceptable; copying large source artifact trees into P26 regression fixtures is unnecessary.

## `待验证`

- Exact final index filename: stage doc says `report_index.json`, manifest says `final_report_index.json`. Best likely outcome is to emit both or update manifest/docs consistently while preserving schema validation.
- Exact source for final `create_cluster`, `meet_nodes`, and `add_replica` rows. P04 has real setup/management smoke rows; P16 does not expose detailed setup operation rows.
- Whether `.github/workflows/codex-gates.yml` should run the P26 final report assertion directly after P26 artifacts are committed, or whether unit tests plus manifest gate are enough for CI.
- Whether `csv_export_index.schema.json` needs tightening or whether all P26 export parity should live in `assert_final_report_regression.py`.
- Whether P26 `quant_summary.runtime_claims.management_runtime_claimed` and `fault_runtime_claimed` should be `false` because P26 does not rerun management/fault runtime, while `real_valkey_claimed` is `true` from the current-stage smoke gate.

## Worker instructions

- Implement only P26 final report/regression hardening.
- Do not rerun P17-P25 source scenarios to manufacture report data.
- Keep existing CLI `report --analysis ...` behavior backward-compatible.
- Add fail-closed assertions before marking the stage complete.
- Do not commit.
- Do not weaken harness or safety rules.
