# M1-S02 Completion

stage_id: M1-S02
stage_status: PASS
run_id: m1-s02-local
review_status: PASS

## Completed Scope

- Added common `setup_telemetry.json` schema and artifact writer for local cluster setup telemetry.
- Collected config parse, config validate, plan, port check, nodehost/process, cluster meet/slot, replica, convergence, full probe, cleanup, and total setup metrics.
- Added per-node readiness samples, per-nodehost samples, slow node TopN, and slow replica TopN.
- Wired setup telemetry through CLI scenario/cleanup, analysis summary aggregation, Chinese offline Markdown/HTML report sections, CSV, and SVG outputs.
- Added success, blocked, dry-run, missing-metric, cleanup-residual, and timeout fixtures.
- Added `scripts/assert_setup_timeline_coverage.py` to enforce required setup metrics, scale-rung schema coverage, fixture-suite outcomes, analysis propagation, and report outputs.
- Preserved P13 legacy setup timeline behavior while emitting common setup telemetry for all `gate scenario` runs.

## Gates Run

- `PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m compileall -q scripts src`: PASS
- `PYTHONPATH=src python3 -m pytest -q tests/artifacts/test_setup_telemetry.py tests/analysis/test_analysis_summary.py tests/report/test_report_rendering.py tests/unit/test_p13_setup_exhaustive_timeline.py`: PASS, 13 passed
- `PYTHONPATH=src python3 -m pytest -q tests/unit tests/integration`: PASS, 218 passed
- `for f in tests/fixtures/setup_telemetry/*/setup_telemetry.json runs/m1-s02-local/artifacts/setup_telemetry.json runs/m1-s02-local/artifacts/goal_loop/M1-S02/setup_telemetry.json; do python3 scripts/validate_json_schema.py --schema schemas/artifact/setup_telemetry.schema.json --instance "$f"; done`: PASS
- `PYTHONPATH=src python3 scripts/assert_setup_timeline_coverage.py --artifacts-dir tests/fixtures/setup_telemetry/success --fixture-suite tests/fixtures/setup_telemetry`: PASS
- `PYTHONPATH=src python3 scripts/assert_setup_timeline_coverage.py --artifacts-dir runs/m1-s02-local/artifacts --analysis runs/m1-s02-local/artifacts/analysis_summary.json --report-index runs/m1-s02-local/reports/report_index.json --fixture-suite tests/fixtures/setup_telemetry`: PASS
- `PYTHONPATH=src python3 scripts/assert_setup_timeline_coverage.py --artifacts-dir runs/m1-s02-local/artifacts/goal_loop/M1-S02 --fixture-suite tests/fixtures/setup_telemetry`: PASS

## Blocked Real Heavy Gate

`python3 scripts/valkey_e2e_gate.py --phase P03_LOCAL_DOCKER_VALKEY --scenario cluster_smoke --config templates/configs/single_mac_6node.yaml --out runs/m1-s02-local/artifacts/goal_loop/M1-S02/valkey_e2e_evidence.json --min-nodes 6 --setup-timeout 180 --cleanup-timeout 120 --probe-timeout 60 --wait-cluster-timeout 60`: BLOCKED_WITH_REASON.

Reason: local sandbox denied port preflight bind for `127.0.0.1:7000` with `Operation not permitted` before Valkey startup. `valkey_e2e_evidence.json` is `FAIL`, and `real_heavy_gate_blocked.json` records `not_a_real_pass: true`.

## Harness Note

`python3 scripts/codex_gate.py postcheck --phase M1-S02` returned `unknown phase: M1-S02`; M1-S02 uses the milestone1 stage-specific gate above instead of the legacy phase gate.

## Next Stage Handoff

M1-S03 should reuse the run-scoped artifact layout from M1-S01 and the setup telemetry propagation path from M1-S02. Command-level audit fields must propagate through schema, writer, fixtures, reader, aggregator, Chinese report renderer, gates, coverage matrix, and blocked/timeout paths without claiming fake real Valkey evidence.
