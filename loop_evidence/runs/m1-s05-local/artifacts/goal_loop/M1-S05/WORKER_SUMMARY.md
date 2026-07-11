# M1-S05 Worker Summary

## Files Changed

- `src/valkey_scale_lab/workload/__init__.py`
- `src/valkey_scale_lab/metrics/__init__.py`
- `src/valkey_scale_lab/runtime/docker_runtime.py`
- `src/valkey_scale_lab/config/validation.py`
- `src/valkey_scale_lab/analysis/summary.py`
- `src/valkey_scale_lab/analysis/workload_impact.py`
- `src/valkey_scale_lab/report/render.py`
- `schemas/config/run_config.schema.json`
- `schemas/artifact/workload_windows.schema.json`
- `schemas/artifact/workload_report.schema.json`
- `scripts/assert_workload_benchmark_contract.py`
- `tests/unit/test_workload_key_generator.py`
- `tests/unit/test_workload_benchmark.py`
- `tests/artifacts/test_workload_benchmark_artifacts.py`
- `tests/analysis/test_analysis_summary.py`
- `tests/report/test_report_rendering.py`
- `tests/fixtures/workload_benchmark/**`
- `runs/m1-s05-local/artifacts/goal_loop/M1-S05/coverage_matrix.md`

## Schema

- Added workload benchmark config fields and enums for mode, profiles, hash-slot distribution, QPS, ratios, timeouts, keyspace, value size, connections, and pipeline.
- Strengthened `workload_windows` to include benchmark mode/profile/slot evidence and the canonical metrics requested by M1-S05.
- Extended `workload_report` with benchmark summary fields, canonical window refs, slot coverage, and management/fault/failover ref arrays.

## Runtime Writer

- Added common workload benchmark profiles, CRC16 slot calculation, full-slot key generation, profile normalization, and benchmark window execution in the workload module.
- Added canonical metric aliases: `throughput_ratio`, `moved_count`, `ask_count`, `cluster_down_count`, `readonly_count`, and `tryagain_count`.
- Updated P05 workload writing to emit canonical `workload_windows.json`, non-empty `events.jsonl`, non-empty `metrics_timeseries.jsonl`, and `quant_summary.json` in addition to the legacy `workload_report.json`.
- Updated P16/P29 telemetry workload path to use the common benchmark runner and include profile/hash-slot coverage fields.
- Fixed the P05 benchmark writer placement so generated Valkey config manifests stay config-only and P05 workload artifacts are emitted from `write_workload_report()`.
- Extended management workload window rows with benchmark metadata and canonical alias metrics so management workload-impact refs carry profile and slot evidence.

## Analyzer

- Added first-class `workload_benchmark` aggregation to `analysis_summary.json`.
- Added aggregate requested/achieved QPS, throughput ratio, p99, error rate, profile coverage, full-slot coverage, and workload missing-metric propagation.
- Preserved profile, workload mode, and key-slot coverage through cross-stage workload-impact rows for management/failover/fault analysis.

## Report Renderer

- Added Chinese/offline workload benchmark reporting to Markdown and HTML.
- Added `workload_benchmark_windows.csv`, `workload_profile_summary.csv`, and `workload_qps_p99_error.svg`.
- Added `workload_report_inputs` to `report_index.json`.

## Tests And Fixtures

- Added unit coverage for profile normalization, ratio validation, failure classification, canonical metrics, CRC16 hash slots, full-slot generation, and fixed-hash-tag detection.
- Added workload benchmark fixtures for success, blocked, failure, 200+ dry-run, missing metric, and cleanup residual.
- Added artifact schema/gate tests and extended analysis/report tests.

## Gates Run

- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m pytest -q tests/unit/test_workload_key_generator.py tests/unit/test_workload_benchmark.py tests/artifacts/test_workload_benchmark_artifacts.py tests/analysis/test_analysis_summary.py tests/report/test_report_rendering.py`
  - Result: PASS, 15 passed.
- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m pytest -q tests/unit/test_workload_key_generator.py tests/unit/test_workload_benchmark.py tests/artifacts/test_workload_benchmark_artifacts.py tests/analysis/test_analysis_summary.py tests/analysis/test_workload_impact_cross_stage.py tests/report/test_report_rendering.py`
  - Result: PASS, 17 passed.
- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 scripts/assert_workload_benchmark_contract.py --fixtures tests/fixtures/workload_benchmark`
  - Result: PASS.
- `PYTHONPATH=src python3 -m valkey_scale_lab.cli analyze --input runs/m1-s05-local/artifacts --out runs/m1-s05-local/artifacts/analysis_summary.json`
  - Result: PASS.
- `PYTHONPATH=src python3 -m valkey_scale_lab.cli report --analysis runs/m1-s05-local/artifacts/analysis_summary.json --out-dir runs/m1-s05-local/reports --index-out runs/m1-s05-local/reports/report_index.json`
  - Result: PASS.
- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 scripts/assert_workload_benchmark_contract.py --artifacts-dir runs/m1-s05-local/artifacts --analysis runs/m1-s05-local/artifacts/analysis_summary.json --report-index runs/m1-s05-local/reports/report_index.json`
  - Result: PASS.
- Direct generated-config manifest smoke for `_write_generated_valkey_configs_manifest()`
  - Result: PASS; confirms benchmark writer is no longer wired into the generated-config manifest path with undefined workload variables.
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/workload_windows.schema.json --instance runs/m1-s05-local/artifacts/workload_windows.json`
  - Result: PASS.
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/workload_report.schema.json --instance runs/m1-s05-local/artifacts/workload_report.json`
  - Result: PASS.
- `PYTHONPATH=src python3 -m pytest -q tests/unit tests/integration`
  - Result: PASS, 226 passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m compileall -q scripts src`
  - Result: PASS.
- `git diff --check`
  - Result: PASS.

## Review Fixes Applied

- Removed the erroneous `_write_p05_workload_benchmark_artifacts()` call from `_write_generated_valkey_configs_manifest()` and kept benchmark artifact writing in the P05 workload report path.
- Strengthened `scripts/assert_workload_benchmark_contract.py` to require all canonical windows (`baseline`, `pre_event`, `event`, `recovery`, `post_recovery`, `all_run`) for every covered profile.
- Regenerated workload benchmark fixtures and local M1-S05 run artifact with complete window coverage.
- Localized the new workload benchmark Markdown, HTML, and SVG text for QPS, p99, error-rate, profile coverage, and full-slot coverage.

## Real Gate Status

- Real Valkey P05 workload smoke gate was attempted by the main agent:

```text
python3 scripts/valkey_e2e_gate.py --phase P05_WORKLOAD_ENGINE --scenario workload_smoke --config templates/configs/single_mac_6node.yaml --out runs/m1-s05-local/artifacts/goal_loop/M1-S05/valkey_e2e_evidence_p05.json --min-nodes 6 --setup-timeout 180 --cleanup-timeout 120 --probe-timeout 60 --wait-cluster-timeout 60
```

  - Result: BLOCKED_WITH_REASON due sandbox port bind denial on `127.0.0.1:7000`.
  - Evidence: `runs/m1-s05-local/artifacts/goal_loop/M1-S05/real_heavy_gate_blocked.json`.

## Coverage Matrix Update

- Updated `runs/m1-s05-local/artifacts/goal_loop/M1-S05/coverage_matrix.md`.
- Most M1-S05 contract rows are now PASS under focused/unit/fixture/report gates.
- `workload_impact_refs` is PASS for artifact-contract coverage: common runtime windows and M1-S04 management refs are preserved/upgraded, and cross-stage workload-impact analysis now preserves profile/slot coverage for management/failover/fault rows.
