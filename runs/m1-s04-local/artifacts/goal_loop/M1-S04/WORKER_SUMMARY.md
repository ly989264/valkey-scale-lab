# M1-S04 Worker Summary

Decision: IMPLEMENTED

## Files Changed

- `src/valkey_scale_lab/management_matrix.py`: added reusable management matrix writer/helper, required operation list, topology snapshot/diff builders, structured missing helpers, fixture-scale artifact writer, and artifact loader.
- `src/valkey_scale_lab/runtime/docker_runtime.py`: preserved the strict management runtime path while adding the new M1-S04 operation result fields, matrix refs, topology diff JSONL output, workload impact refs, cleanup refs, and schema-compatible matrix metadata.
- `schemas/artifact/management_ops_matrix.schema.json`: strengthened matrix contract with operation refs, command refs, workload refs, cleanup refs, and required operation list.
- `schemas/artifact/management_operation_result.schema.json`: strengthened operation result contract with topology snapshots/diffs, timing, command counts, workload/cleanup refs, and structured missing `bytes_migrated`.
- `schemas/artifact/management_topology_diff.schema.json`: added schema for management topology diff JSONL rows.
- `src/valkey_scale_lab/analysis/summary.py`: added management artifact readers and aggregation for operation count, required operation coverage, duration ranking, slow/error/retry operations, command traceability, topology diff summary, reshard/rebalance summary, and rolling restart summary.
- `src/valkey_scale_lab/report/render.py`: added Chinese management report sections and CSV/SVG outputs for matrix rows, operation durations, topology diffs, rolling restart, and reshard/rebalance.
- `scripts/assert_management_matrix_m1.py`: added M1-S04 gate enforcing schema, non-empty artifacts, all required operations, snapshot/diff/workload/cleanup refs, command-log ref resolution, operation-specific extras, analysis propagation, and Chinese report sections.
- `tests/artifacts/test_management_matrix.py`: added writer and analysis/report propagation tests.
- `tests/analysis/test_analysis_summary.py`: added management aggregation coverage.
- `tests/report/test_report_rendering.py`: updated expected report outputs and report index checks.
- `tests/fixtures/management_matrix/**`: added success, 30/50/100/200, 200+ dry-run planning, blocked, cleanup residual, and negative fixtures.
- `runs/m1-s04-local/artifacts/**`: generated M1-S04 stage artifacts, analysis summary, and offline report outputs.
- `runs/m1-s04-local/artifacts/goal_loop/M1-S04/coverage_matrix.md`: finalized coverage matrix for execution shape, scale, function path, data path, and outcome classes.
- `runs/m1-s04-local/artifacts/goal_loop/M1-S04/real_heavy_gate_blocked.json`: recorded real Valkey gate block without claiming PASS.

## Commands Run

- `PYTHONPATH=src python3 -m pytest -q tests/artifacts/test_management_matrix.py tests/analysis/test_analysis_summary.py tests/report/test_report_rendering.py` -> PASS, 7 tests.
- `PYTHONPATH=src python3 scripts/assert_management_matrix_m1.py --fixtures tests/fixtures/management_matrix` -> PASS.
- `PYTHONPATH=src python3 -m valkey_scale_lab.cli analyze --input runs/m1-s04-local --out runs/m1-s04-local/artifacts/analysis_summary.json` -> PASS.
- `PYTHONPATH=src python3 -m valkey_scale_lab.cli report --analysis runs/m1-s04-local/artifacts/analysis_summary.json --out-dir runs/m1-s04-local/reports --index-out runs/m1-s04-local/reports/report_index.json` -> PASS.
- `PYTHONPATH=src python3 scripts/assert_management_matrix_m1.py --artifacts-dir runs/m1-s04-local/artifacts --analysis runs/m1-s04-local/artifacts/analysis_summary.json --report-index runs/m1-s04-local/reports/report_index.json` -> PASS.
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/management_ops_matrix.schema.json --instance runs/m1-s04-local/artifacts/management_ops_matrix.json` -> PASS.
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/management_operation_result.schema.json --instance runs/m1-s04-local/artifacts/management_operation_results.jsonl --jsonl` -> PASS.
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/management_topology_diff.schema.json --instance runs/m1-s04-local/artifacts/management_topology_diffs.jsonl --jsonl` -> PASS.
- `PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m compileall -q scripts src` -> PASS.
- `PYTHONPATH=src python3 -m pytest -q tests/unit tests/integration` -> PASS, 219 tests.
- `PYTHONPATH=src python3 -m pytest -q tests/artifacts/test_management_matrix.py tests/analysis/test_analysis_summary.py tests/report/test_report_rendering.py tests/integration/test_docker_runtime_contract.py` -> PASS, 77 tests.
- Fixture schema loop for management matrix/results/topology diff success scale fixtures -> PASS.
- `python3 scripts/valkey_e2e_gate.py --phase P04_CLUSTER_MANAGEMENT_OPS --scenario management_ops --config templates/configs/single_mac_6node.yaml --out runs/m1-s04-local/artifacts/goal_loop/M1-S04/valkey_e2e_evidence_p04.json --min-nodes 6 --setup-timeout 180 --cleanup-timeout 120 --probe-timeout 60 --wait-cluster-timeout 60` -> BLOCKED_WITH_REASON due sandbox port bind denial.

## Real Heavy Gate

Real local Valkey management execution remains blocked in this environment:

```text
ERROR: gate scenario: port 127.0.0.1:7000 is not available: [Errno 1] Operation not permitted
```

The stage records this as `BLOCKED_WITH_REASON` in `real_heavy_gate_blocked.json` and does not claim fake real evidence.

## Main Agent Follow-up

- Normalized `coverage_matrix.md` scale and outcome vocabulary to the global M1 terms (`scale_30`, `scale_50`, `scale_100`, `scale_200`, `scale_200_plus_dry_run_planning`, `missing_metric`, `command_failure`, `timeout`, `report_input_missing`).
- Independently reran focused M1-S04 tests, fixture gate, stage artifact/report gate, schema validation for run artifacts, compileall, unit/integration tests, and broader management/runtime focused suite.
- Raw schema validation over the intentionally invalid `empty/` negative fixture prints expected errors; the authoritative fixture gate treats that case as an expected failure and passes only if it is rejected.
- Addressed the first review failure by wiring the legacy `P04_CLUSTER_MANAGEMENT_OPS` real gate path to emit M1-S04 contract artifacts (`management_ops_matrix.json`, operation results JSONL, topology snapshots/diffs, workload impact, rebalance and rolling restart placeholders) without inventing destructive-operation PASS evidence.
- Addressed the second review failure by making the strict real management runtime write `management_topology_diffs.jsonl` for the refs already advertised by operation and matrix rows.
- Addressed the third review failure by attaching setup command-audit refs from `command_log.jsonl` to setup-derived strict rows, or downgrading to `PASS_NOOP_VERIFIED` with structured missing command refs when no command evidence is available.
- Added a focused P04 contract regression test proving setup rows have command evidence while destructive rows are explicitly `SKIPPED_WITH_REASON`.
- Reran focused management/runtime tests, fixture gate, run-artifact gate, schema validations, compileall, unit/integration tests, `git diff --check`, and the real P04 gate attempt. The real gate remains `BLOCKED_WITH_REASON` by sandbox denial of `127.0.0.1:7000`.
- After a fresh review caught that the helper had been applied to earlier writers but not the strict P30 writer, patched `write_p30_management_matrix_artifacts()` directly to attach setup command refs, synchronize matrix row refs, and write `management_topology_diffs.jsonl`.
- Reran `compileall`, the 78-test management/runtime focused suite, and `git diff --check` after the strict P30 patch.
