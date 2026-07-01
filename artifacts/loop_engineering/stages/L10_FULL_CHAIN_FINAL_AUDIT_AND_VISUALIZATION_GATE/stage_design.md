# L10 Stage Design

## Goal

Add a final full-chain audit gate covering the committed artifact audit, provenance DAG, metric catalog, coverage matrix, report views, scale/fault/stability rollups, and P14 dry-run boundary.

## Required Harness

- `scripts/final_audit_gate.py`
- `schemas/artifact/final_audit_report.schema.json`
- `tests/final_audit/test_final_audit_gate.py`
- `tests/ci/test_final_audit_gate.py`
- CI integration in `.github/workflows/github-coverage-gates.yml`

## Required Invariants

- P14 remains opt-in dry-run/resource/planner only and is never counted as real Valkey coverage.
- Coverage matrix has fake, small-real, 30, 50, 100, and 1000-dry-run layers across all ten surfaces.
- All source audit artifacts are schema-valid `PASS` JSON artifacts.
- Rendered HTML/SVG/CSV views are `source_of_truth=false` and link back to machine-readable source artifacts.
- Every `MISSING`, `SKIPPED_WITH_REASON`, or `NO_BASELINE_YET` metric carries both reason and impact.
- Final HTML exposes root commit SHA and source artifact paths/hashes.

## Non-Goals

- Do not run P14 or set `VSLAB_ALLOW_1000_DRYRUN`.
- Do not run new real Valkey gates.
- Do not use rendered views as measured metric sources.
