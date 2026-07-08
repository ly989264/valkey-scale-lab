# M1-S03 Worker Summary

## Scope

Implemented command-level audit logging as a common runtime facility for M1-S03. The implementation covers the propagation chain required by the stage:

```text
schema -> writer -> fixture -> reader -> aggregator -> renderer -> gate -> docs
```

## Files Changed

- Added `src/valkey_scale_lab/runtime/command_recorder.py` with reusable `CommandRecorder`, context attachment, sidecar stdout/stderr logs, JSONL writer, and summary builder.
- Strengthened `schemas/artifact/command_log_entry.schema.json` and added `schemas/artifact/command_audit_summary.schema.json`.
- Wired recorder context through `src/valkey_scale_lab/cli.py` for `gate scenario`, `gate cleanup`, `fault apply`, and `fault clear`.
- Added common recording at `run_docker(...)` and host Valkey `_node_command(...)` paths in `src/valkey_scale_lab/runtime/docker_runtime.py`.
- Added audited fault apply/clear docker calls in `src/valkey_scale_lab/fault/sandbox.py`.
- Updated `src/valkey_scale_lab/analysis/summary.py` to read `command_log.jsonl` and aggregate slow/failure/timeout/retry/by-kind/traceability data.
- Updated `src/valkey_scale_lab/report/render.py` to emit Chinese command audit sections plus `command_slowest.csv`, `command_failures.csv`, `command_retries.csv`, and `command_latency.svg`.
- Added `scripts/assert_command_log_nonempty_and_schema.py`.
- Added fixtures under `tests/fixtures/command_log/` for success, failure, timeout, retry, cleanup residual, and empty log rejection.
- Added/updated tests:
  - `tests/artifacts/test_command_log.py`
  - `tests/unit/test_command_recorder_runtime.py`
  - `tests/analysis/test_analysis_summary.py`
  - `tests/report/test_report_rendering.py`

## Stage Artifacts

- `runs/m1-s03-local/artifacts/command_log.jsonl`
- `runs/m1-s03-local/artifacts/command_audit_summary.json`
- `runs/m1-s03-local/artifacts/analysis_summary.json`
- `runs/m1-s03-local/reports/report_index.json`
- `runs/m1-s03-local/reports/report.md`
- `runs/m1-s03-local/reports/index.html`
- `runs/m1-s03-local/artifacts/goal_loop/M1-S03/real_heavy_gate_blocked.json`
- `runs/m1-s03-local/artifacts/goal_loop/M1-S03/coverage_matrix.md`

## Commands Run

- `PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m compileall -q scripts src` -> PASS
- `PYTHONPATH=src python3 -m pytest -q tests/artifacts/test_command_log.py tests/unit/test_command_recorder_runtime.py tests/analysis/test_analysis_summary.py tests/report/test_report_rendering.py` -> PASS, 8 passed
- `PYTHONPATH=src python3 scripts/assert_command_log_nonempty_and_schema.py --fixtures tests/fixtures/command_log` -> PASS
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/command_log_entry.schema.json --instance tests/fixtures/command_log/success/command_log.jsonl --jsonl` -> PASS
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/command_audit_summary.schema.json --instance tests/fixtures/command_log/success/command_audit_summary.json` -> PASS
- `PYTHONPATH=src python3 -m valkey_scale_lab.cli analyze --input runs/m1-s03-local/artifacts --out runs/m1-s03-local/artifacts/analysis_summary.json` -> PASS
- `PYTHONPATH=src python3 -m valkey_scale_lab.cli report --analysis runs/m1-s03-local/artifacts/analysis_summary.json --out-dir runs/m1-s03-local/reports --index-out runs/m1-s03-local/reports/report_index.json` -> PASS
- `PYTHONPATH=src python3 scripts/assert_command_log_nonempty_and_schema.py --artifacts-dir runs/m1-s03-local/artifacts --analysis runs/m1-s03-local/artifacts/analysis_summary.json --report-index runs/m1-s03-local/reports/report_index.json` -> PASS
- `PYTHONPATH=src python3 -m pytest -q tests/unit tests/integration` -> PASS, 219 passed
- `python3 scripts/valkey_e2e_gate.py --phase P03_LOCAL_DOCKER_VALKEY --scenario cluster_smoke --config templates/configs/single_mac_6node.yaml --out runs/m1-s03-local/artifacts/goal_loop/M1-S03/valkey_e2e_evidence.json --min-nodes 6 --setup-timeout 180 --cleanup-timeout 120 --probe-timeout 60 --wait-cluster-timeout 60` -> FAIL due sandbox port bind; recorded as `BLOCKED_WITH_REASON`.

## Main Agent Follow-up

- Strengthened `scripts/assert_command_log_nonempty_and_schema.py` after worker implementation so the gate proves the empty fixture is rejected, verifies stage command kinds, checks summary counts against JSONL rows, requires nonempty slow-command TopN when rows exist, and verifies operation traceability covers every command id.
- Regenerated `runs/m1-s03-local/artifacts/command_audit_summary.json` and `tests/fixtures/command_log/success/command_audit_summary.json` from `build_command_audit_summary(...)`.
- Reran analysis/report so `analysis_summary.json`, `report_index.json`, Markdown, HTML, CSV, and SVG outputs reflect the refreshed command audit summary.

## Real Gate Status

Real Valkey smoke did not pass because this environment rejects binding `127.0.0.1:7000` during preflight:

```text
ERROR: gate scenario: port 127.0.0.1:7000 is not available: [Errno 1] Operation not permitted
```

No fake PASS was created. The structured blocked artifact is `runs/m1-s03-local/artifacts/goal_loop/M1-S03/real_heavy_gate_blocked.json`.

## Notes For Review

- The recorder is reusable for later M1-S04 management and M1-S06 fault/failover stages.
- The empty command log fixture is intentionally invalid and is rejected by the stage gate.
- Real blocked setup fails before any live Valkey/Docker commands are executed under the recorder, so there are no invented real command rows.
