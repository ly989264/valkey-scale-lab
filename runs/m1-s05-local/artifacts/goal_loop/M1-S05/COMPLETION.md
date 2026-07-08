# M1-S05 Completion

Stage: M1-S05 workload 从 smoke 升级为 benchmark

Decision: COMPLETE_WITH_REAL_GATE_BLOCKED

## Completed Work

- Preserved smoke workload while adding benchmark workload profiles: `smoke`, `uniform`, `hotspot`, `mixed_rw`, `write_heavy`, and `read_heavy`.
- Added CRC16 Valkey Cluster hash-slot calculation and a full-slot key generator that can prove coverage of slots `0..16383`.
- Added canonical workload benchmark metrics: requested/achieved QPS, throughput ratio, ok/error ops, error rate, p50/p90/p95/p99/p999 latency, timeout, connection, MOVED, ASK, CLUSTERDOWN, READONLY, and TRYAGAIN counts.
- Updated workload schemas, config validation, runtime writers, fixtures, analysis aggregation, cross-stage workload-impact preservation, Chinese report rendering, and stage-specific gate.
- Preserved M1-S04 management workload refs while adding benchmark metadata and slot coverage to workload windows.
- Generated local M1-S05 run artifacts, analysis summary, and offline Chinese report outputs.
- Maintained M1-S05 coverage matrix across execution shape, scale rung, functional path, data path, and outcome class.

## Gates

- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m pytest -q tests/unit/test_workload_key_generator.py tests/unit/test_workload_benchmark.py tests/artifacts/test_workload_benchmark_artifacts.py tests/analysis/test_analysis_summary.py tests/analysis/test_workload_impact_cross_stage.py tests/report/test_report_rendering.py` -> PASS, 17 tests.
- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 scripts/assert_workload_benchmark_contract.py --fixtures tests/fixtures/workload_benchmark` -> PASS.
- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 scripts/assert_workload_benchmark_contract.py --artifacts-dir runs/m1-s05-local/artifacts --analysis runs/m1-s05-local/artifacts/analysis_summary.json --report-index runs/m1-s05-local/reports/report_index.json` -> PASS.
- `PYTHONPATH=src python3 -m pytest -q tests/unit tests/integration` -> PASS, 226 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m compileall -q scripts src` -> PASS.
- `git diff --check` -> PASS.
- Schema validation for `workload_windows.json` and `workload_report.json` -> PASS.
- Direct generated-config manifest smoke for `_write_generated_valkey_configs_manifest()` -> PASS.

## Real Heavy Gate

The real P05 Valkey workload gate was attempted and remains blocked by the local sandbox:

```text
ERROR: gate scenario: port 127.0.0.1:7000 is not available: [Errno 1] Operation not permitted
```

Evidence is recorded in `real_heavy_gate_blocked.json` and `valkey_e2e_evidence_p05.json`. The stage does not claim a fake real PASS.

## Harness Postcheck

- `python3 scripts/codex_gate.py postcheck --phase M1-S05` -> BLOCKED_WITH_REASON: `unknown phase: M1-S05`.
- `python3 scripts/codex_gate.py mark-complete --phase M1-S05` -> BLOCKED_WITH_REASON: `unknown phase: M1-S05`.

The M1 stage-specific gates and review are authoritative for this milestone loop because the legacy phase gate has not been extended with M1-S05 phase IDs.

## Review

Fresh review subagent wrote `REVIEW.md`.

Decision: PASS
