# M1-S01 Worker Summary

stage_id: M1-S01
worker: worker subagent plus main-agent integration fixes
status: IMPLEMENTED

## Modified Files

- `src/valkey_scale_lab/artifacts/__init__.py`: added run context, run metadata, manifest writer/reader, structured missing/skipped helpers, and artifact input resolver.
- `src/valkey_scale_lab/cli.py`: added `run init` to create `runs/<run_id>/artifacts|logs|reports|state` with state-scoped metadata and manifest.
- `src/valkey_scale_lab/analysis/summary.py`: analysis now accepts legacy artifact dirs, run roots, and `run_manifest.json` inputs and carries metadata refs forward.
- `src/valkey_scale_lab/report/render.py`: report index and rendered body include run metadata/manifest references and a Chinese run metadata section.
- `schemas/artifact/run_metadata.schema.json`: new metadata schema.
- `schemas/artifact/run_manifest.schema.json`: new manifest schema.
- `schemas/artifact/analysis_summary.schema.json`: now requires run metadata refs and embedded run metadata or structured reason.
- `schemas/artifact/report_index.schema.json`: now requires run metadata and manifest refs.
- `scripts/assert_run_metadata_contract.py`: M1-S01 stage-specific metadata gate.
- `tests/artifacts/test_run_metadata.py`: fixture-style unit/integration coverage for writer, reader, analyzer, renderer, CLI, and legacy compatibility.
- `tests/fixtures/run_metadata/*/run_metadata.json`: blocked, dry-run, and failure fixtures with structured reasons.
- `README.md`: rewritten for milestone1 scope, run directories, commands, reports, gates, and limitations.

## Propagation

- schema: `run_metadata.schema.json`, `run_manifest.schema.json`.
- writer: `create_run_context`, `build_run_metadata`, `write_run_metadata`, `write_run_manifest`.
- reader: `load_run_manifest`, `resolve_artifact_input`.
- analyzer: `create_analysis_summary` includes `run_manifest_ref`, `run_metadata_ref`, and `run_metadata`.
- renderer: `render_report` writes metadata refs to `report_index.json` and displays metadata in Markdown/HTML.
- fixture/tests: fake/smoke-style run roots, legacy artifact dir, CLI init, structured skipped metadata.
- gate: `scripts/assert_run_metadata_contract.py`.

## Commands Run

- `PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m compileall -q scripts src`: PASS.
- `python3 -m pytest -q tests/artifacts/test_run_metadata.py tests/analysis/test_analysis_summary.py tests/report/test_report_rendering.py`: PASS, 8 passed.
- `python3 -m pytest -q tests/unit tests/integration`: PASS, 218 passed.
- `python3 scripts/assert_run_metadata_contract.py`: PASS.
- `PYTHONPATH=src python3 -m valkey_scale_lab.cli run init --run-id m1-s01-local`: PASS.
- `PYTHONPATH=src python3 -m valkey_scale_lab.cli analyze --input runs/m1-s01-local --out runs/m1-s01-local/artifacts/analysis_summary.json`: PASS.
- `PYTHONPATH=src python3 -m valkey_scale_lab.cli report --analysis runs/m1-s01-local/artifacts/analysis_summary.json --out-dir runs/m1-s01-local/reports --index-out runs/m1-s01-local/reports/report_index.json`: PASS.
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/run_metadata.schema.json --instance runs/m1-s01-local/state/run_metadata.json`: PASS.
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/run_manifest.schema.json --instance runs/m1-s01-local/state/run_manifest.json`: PASS.
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/analysis_summary.schema.json --instance runs/m1-s01-local/artifacts/analysis_summary.json`: PASS.
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/report_index.schema.json --instance runs/m1-s01-local/reports/report_index.json`: PASS.
- New-run identity check: `analysis_summary.json` and `report_index.json` both use `run_id=m1-s01-local` and `created_at` from `state/run_metadata.json`, not the legacy P09 fixed constants.

## Real Heavy Gate

`python3 scripts/valkey_e2e_gate.py --phase P03_LOCAL_DOCKER_VALKEY --scenario cluster_smoke --config templates/configs/single_mac_6node.yaml --out runs/m1-s01-local/artifacts/goal_loop/M1-S01/valkey_e2e_evidence.json --min-nodes 6 --setup-timeout 180 --cleanup-timeout 120 --probe-timeout 60 --wait-cluster-timeout 60`: BLOCKED_WITH_REASON.

Reason: sandbox denied local port preflight bind for `127.0.0.1:7000` with `Operation not permitted` before Valkey could start. Evidence is recorded in `real_heavy_gate_blocked.json`; this is not a real PASS.
