# M1-S06 Completion Record

Stage: M1-S06
Status: PASS_WITH_LEGACY_CODEX_GATE_BLOCKED

## Summary

M1-S06 implemented the shared fault/failover timeline contract and propagated it through schema, writer/model helpers, fixtures, analysis, report rendering, gates, and docs. The stage is not primary-stop-only: fixtures and the stage report cover all required M1 fault types plus small/30/50/100/200 and 200+ dry-run planning evidence.

## Required Outputs

- `schemas/artifact/fault_timeline_event.schema.json`
- `schemas/artifact/fault_timeline_report.schema.json`
- `scripts/assert_fault_timeline_m1.py`
- `tests/fixtures/fault_timeline/*`
- `runs/m1-s06-local/artifacts/fault_timeline_events.jsonl`
- `runs/m1-s06-local/artifacts/fault_timeline_report.json`
- `runs/m1-s06-local/artifacts/failover_latency_samples.jsonl`
- `runs/m1-s06-local/artifacts/fault_workload_impact.json`
- `runs/m1-s06-local/artifacts/analysis_summary.json`
- `runs/m1-s06-local/reports/report_index.json`
- `runs/m1-s06-local/reports/report.md`

## Gates

- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m compileall -q scripts src` - PASS
- `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m pytest -q tests/unit tests/integration tests/artifacts/test_fault_timeline_artifacts.py tests/report/test_report_rendering.py tests/analysis/test_analysis_summary.py` - PASS, 239 passed
- `PYTHONPATH=src python3 scripts/assert_fault_timeline_m1.py --fixtures tests/fixtures/fault_timeline` - PASS
- `PYTHONPATH=src python3 scripts/assert_fault_timeline_m1.py --artifacts-dir runs/m1-s06-local/artifacts --analysis runs/m1-s06-local/artifacts/analysis_summary.json --report-index runs/m1-s06-local/reports/report_index.json` - PASS
- `PYTHONPATH=src python3 scripts/validate_json_schema.py` over every `tests/fixtures/fault_timeline/*` timeline report and event JSONL - PASS
- `git diff --check` - PASS
- Full `PYTHONPATH=src PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m pytest -q` - FAIL due existing CI/provenance/committed artifact audit tests outside M1-S06 scope; M1-S06 focused gates and unit/integration checks pass.

## Real Valkey Evidence

- Real 30-node primary-stop failover gate: PASS.
- Evidence: `runs/m1-s06-local/artifacts/goal_loop/M1-S06/real_fault_failover_gate.json`
- Valkey version: `9.1.0`
- Nodes observed before fault: 30
- Nodes observed after clear: 30
- Failover latency: 49137.254 ms
- Cleanup: PASS with no `resources_remaining`
- 50/100/200 real rows: `BLOCKED_WITH_REASON` in `real_fault_failover_gate_blocked.json`; no real PASS is claimed for those rungs.

## Review

Review subagent wrote `REVIEW.md` with `Decision: PASS`.

## Legacy Codex Gate

`python3 scripts/codex_gate.py postcheck --phase M1-S06` returned `unknown phase: M1-S06`.

`python3 scripts/codex_gate.py mark-complete --phase M1-S06` returned `unknown phase: M1-S06`.

This is recorded as `BLOCKED_WITH_REASON` for the legacy phase gate only. The M1-S06 stage-specific strong harness gates passed.
