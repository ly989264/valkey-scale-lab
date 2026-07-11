# WORKER_SUMMARY — P20_FAILOVER_LATENCY_CURVE_30_50_100

## Changes

- Added a P20 controller in `scripts/fault_failover_gate.py` for `failover_curve_30_50_100`.
- The controller runs exact rungs 30, 50, and 100 with three fresh single-sample primary-stop failover runs per rung.
- Added P20 resource preflight normalization to top-level `resource_preflight_30.json`, `resource_preflight_50.json`, and `resource_preflight_100.json`; preflight failure writes `BLOCKED.md` and exits nonzero.
- Aggregates real single-sample outputs into `failover_latency_samples.jsonl`, `failover_latency_curve.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `quant_summary.json`, `phase_summary.json`, `valkey_e2e_evidence.json`, `fault_matrix_report.json`, `workload_impact_report.json`, `cleanup_report.json`, and `failover_report.json`.
- Preserved existing single-sample failover behavior for earlier phases while appending additional timestamp and workload-window fields.
- Allowed only P20 `scale_30_sample_NN`, `scale_50_sample_NN`, and `scale_100_sample_NN` setup aliases through the existing docker-process runtime.
- Strengthened P20 assertions for unique sample/run/state refs, real-Valkey status, exact rung coverage, cleanup refs, timestamp-derived latencies, workload refs, resource preflights, and curve statistics derived from raw sample rows.
- Added focused tests for P20 assertion acceptance/rejection and P20 sample scenario aliasing.

## Tests Run

- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache python3 -m compileall -q scripts src tests/unit/test_goal_loop_assertions.py tests/failover/test_failover_contract.py`
- `python3 -m pytest -q tests/unit/test_goal_loop_assertions.py tests/failover/test_failover_contract.py`
- `python3 -m pytest -q tests/ci/test_fault_failover_scale_gate.py`
- `python3 scripts/safety_scan.py`

## Notes

- The full P20 real Docker gate was intentionally not run here; it is long-running and left for the main stage gate.
- No commit or push was performed.
