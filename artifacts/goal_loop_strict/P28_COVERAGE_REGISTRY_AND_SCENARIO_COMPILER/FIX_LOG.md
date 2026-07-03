# FIX_LOG - P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER

## Review failure addressed

Fresh-context review returned `Decision: FAIL` because `artifacts/coverage/strict_scenario_plan.json` omitted explicit `telemetry_policy` entries, all real scenarios omitted `events.jsonl` and `metrics_timeseries.jsonl`, and P36 full-flow scenarios omitted `workload_windows.json`.

## Fix

- Added `telemetry_policy` to every generated scenario.
- Added required real-stage telemetry artifacts to `expected_artifacts`:
  - `events.jsonl`
  - `metrics_timeseries.jsonl`
  - `workload_windows.json`
- Strengthened `schemas/artifact/strict_scenario_plan.schema.json` so `telemetry_policy` is required.
- Strengthened `scripts/assert_coverage_registry.py` so `--require-all` fails when telemetry policy or required real telemetry artifacts are absent.
- Added regression tests in `tests/unit/test_strict_coverage_registry.py`.
- Regenerated `artifacts/coverage/strict_scenario_plan.json` and P28 summary artifacts.
- Updated `codex/gate_lock.json` hashes for the intentionally strengthened locked files.

## Verification

```text
python3 scripts/build_strict_coverage_registry.py --out-dir artifacts/coverage --phase P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER
PASS

PYTHONPYCACHEPREFIX=.pycache python3 -m pytest -q tests/unit/test_strict_coverage_registry.py
7 passed

python3 scripts/assert_coverage_registry.py --registry artifacts/coverage/strict_coverage_registry.json --require-all
PASS coverage registry assertion

python3 scripts/validate_json_schema.py --schema schemas/artifact/strict_scenario_plan.schema.json --instance artifacts/coverage/strict_scenario_plan.json
PASS

python3 scripts/safety_scan.py
PASS safety_scan

python3 scripts/codex_gate.py precheck --phase P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER
PASS precheck

PYTHONPYCACHEPREFIX=.pycache python3 -m pytest -q tests/unit tests/integration
144 passed
```
