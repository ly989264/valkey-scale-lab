# M1-S06 Worker Summary

## Files Changed

- `src/valkey_scale_lab/observer/failover_timeline.py`: added M1-S06 required events, metrics, fault types, scale rungs, event builder, metric derivation, timeline report builder, and latency-sample derivation.
- `src/valkey_scale_lab/analysis/summary.py`: reads `fault_timeline_report.json`, `fault_timeline_events.jsonl`, `failover_latency_samples.jsonl`, and `fault_workload_impact.json`; aggregates coverage, latency, unavailability, split-brain, cluster-down, cleanup, and missing metrics.
- `src/valkey_scale_lab/analysis/workload_impact.py`: propagates `fault_timeline_ref`, `fault_event_window`, `client_unavailability_ms`, `cluster_down_window_ms`, and `workload_recovery_ms`.
- `src/valkey_scale_lab/report/render.py`: renders Chinese fault sections and CSV/SVG exports for timeline, failover distribution, split-brain windows, and fault-period workload impact.
- `schemas/artifact/fault_timeline_event.schema.json`, `schemas/artifact/fault_timeline_report.schema.json`: new M1-S06 schemas.
- `schemas/artifact/failover_latency_sample.schema.json`: allows timeline propagation fields.
- `scripts/assert_fault_timeline_m1.py`: new contract gate.
- `tests/unit/test_fault_timeline_contract.py`, `tests/artifacts/test_fault_timeline_artifacts.py`, `tests/integration/test_fault_timeline_pipeline.py`, `tests/report/test_report_rendering.py`: focused coverage.
- `tests/fixtures/fault_timeline/`: success, failure, timeout, missing effect observed, blocked, dry-run 200+, cleanup residual, report-input missing, and scale 30/50/100/200 fixtures.
- `runs/m1-s06-local/artifacts/` and `runs/m1-s06-local/reports/`: generated local analysis/report artifacts.
- `runs/m1-s06-local/artifacts/goal_loop/M1-S06/coverage_matrix.md`: updated from design-pending to implementation evidence.
- `runs/m1-s06-local/artifacts/goal_loop/M1-S06/real_fault_failover_gate_blocked.json`: structured blocked evidence for heavy real Valkey runs.

## Commands Run

- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m compileall -q scripts src` - PASS
- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m pytest -q tests/unit/test_fault_timeline_contract.py tests/artifacts/test_fault_timeline_artifacts.py tests/integration/test_fault_timeline_pipeline.py tests/analysis/test_analysis_summary.py tests/report/test_report_rendering.py` - PASS, 13 passed
- `PYTHONPATH=src python3 scripts/assert_fault_timeline_m1.py --fixtures tests/fixtures/fault_timeline` - PASS
- `PYTHONPATH=src python3 -m valkey_scale_lab.cli analyze --input runs/m1-s06-local/artifacts --out runs/m1-s06-local/artifacts/analysis_summary.json` - PASS
- `PYTHONPATH=src python3 -m valkey_scale_lab.cli report --analysis runs/m1-s06-local/artifacts/analysis_summary.json --out-dir runs/m1-s06-local/reports --index-out runs/m1-s06-local/reports/report_index.json` - PASS
- `PYTHONPATH=src python3 scripts/assert_fault_timeline_m1.py --artifacts-dir runs/m1-s06-local/artifacts --analysis runs/m1-s06-local/artifacts/analysis_summary.json --report-index runs/m1-s06-local/reports/report_index.json` - PASS
- `git diff --check` - PASS
- `PYTHONPATH=src python3 scripts/validate_json_schema.py --schema schemas/artifact/fault_timeline_report.schema.json --instance tests/fixtures/fault_timeline/success/fault_timeline_report.json` - PASS after main-agent fixture regeneration.
- `PYTHONPATH=src python3 scripts/validate_json_schema.py --schema schemas/artifact/fault_timeline_event.schema.json --instance tests/fixtures/fault_timeline/success/fault_timeline_events.jsonl --jsonl` - PASS after main-agent schema alignment for structured unobserved timestamps.
- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m pytest -q tests/unit tests/integration tests/artifacts/test_fault_timeline_artifacts.py tests/report/test_report_rendering.py tests/analysis/test_analysis_summary.py` - PASS, 239 passed.
- `PYTHONPATH=src python3 scripts/validate_json_schema.py` over every `tests/fixtures/fault_timeline/*` timeline report and event JSONL - PASS.
- `PYTHONPATH=src python3 scripts/fault_failover_gate.py --phase P20_FAILOVER_LATENCY_CURVE_30_50_100 --scenario scale_30_sample_01_fault_failover --config templates/configs/scale_30.yaml ...` - PASS after elevated local-port permission; observed Valkey `9.1.0`, 30 nodes, promotion, data path recovery, and cleanup.
- `PYTHONPATH=src python3 -m pytest -q` - FAIL due pre-existing/full-suite CI provenance and committed-artifact audit tests outside M1-S06 scope; focused unit/integration/artifact/report gates above PASS.

## Blocked Results

- Worker did not execute real 30/50/100/200 Valkey fault/failover gates. Main agent later executed a real 30-node primary-stop failover gate successfully with Valkey `9.1.0`; evidence is `runs/m1-s06-local/artifacts/goal_loop/M1-S06/real_fault_failover_gate.json`.
- Real 50/100/200 rows remain explicitly `BLOCKED_WITH_REASON` in `runs/m1-s06-local/artifacts/goal_loop/M1-S06/real_fault_failover_gate_blocked.json`; no real PASS is claimed for those rungs.

## Known Risks

- Main agent resolved the schema-validation risk by regenerating fixture/report rows with `timeline_status` and `clean_cluster_evidence`, and by allowing structured unobserved timestamp fields in the event schema.
- Main agent consolidated the duplicated standalone `src/valkey_scale_lab/fault_timeline.py` helper back into `observer/failover_timeline.py`; the shared contract now has one production import path.
- Heavy real Valkey evidence still requires main-agent resource preflight and Docker/port availability.

No commit or push was performed.
