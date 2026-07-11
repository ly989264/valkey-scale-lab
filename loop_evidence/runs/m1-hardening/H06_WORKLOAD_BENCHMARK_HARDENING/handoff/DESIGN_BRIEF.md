role: design
agent_invocation: real_subagent
stage_id: H06_WORKLOAD_BENCHMARK_HARDENING
source_commit_before: 038bf1cf50aa04b1c575352e4f326eeb91886e74
source_commit_after: MISSING

# DESIGN_BRIEF

## Recommendation

Implement H06 as a workload-specific, fail-closed C08 gate. Current repository workload claims should stay `BLOCKED_WITH_REASON` until exact-scale real Valkey 9.1.x benchmark artifacts prove the full profile/window/metric matrix.

## Code Changes

- In `scripts/m1h/manifest.py`, add C08 constants for six profiles, six windows, 18 required metrics, minimum row count 648, and minimum operations per window.
- Add `evaluate_workload_benchmark_claim(...)` and store diagnostics in `diagnostics.workload_h06_acceptance`.
- Evaluate one phase directory at a time. Do not combine workload windows, metrics, and Valkey evidence across directories.
- Promote workload `evidence_kind` to `REAL_EXACT_SCALE` only when H06 diagnostics are accepted.
- Replace `scripts/m1h/assert_workload_benchmark_strength.py` with a dedicated gate modeled on H05 management hardening.
- Register `H06_REQUIRED_GATE_RESULTS` in `scripts/m1h/assert_stage_exit.py`.
- Strengthen workload writers and schema so future runs can emit `profiles_covered`, `hash_slot_coverage`, per-window config, operation counts, and observed connection/pipeline evidence.

## Required Semantics

A workload benchmark PASS requires all of the following in one evidence bundle:

- exact node scale 30, 50, 100, or 200;
- real Valkey evidence with Valkey 9.1.x;
- `workload_windows.json` schema-valid and `status: PASS`;
- profiles: `smoke`, `uniform`, `hotspot`, `mixed_rw`, `write_heavy`, `read_heavy`;
- windows per profile: `baseline`, `pre_event`, `event`, `recovery`, `post_recovery`, `all_run`;
- every C08 metric present and numeric in every profile/window;
- `metrics_timeseries.jsonl` rows for each profile/window/metric and row count >= 648;
- `ok_ops + error_ops` meets the configured minimum per window;
- observed connection and pipeline evidence, not config-only intent;
- full-slot coverage for every non-smoke profile;
- no fixture, historical-only, dry-run, smaller-scale, synthetic, or incomplete evidence used for PASS.

## Tests

Add tests for:

- a fully valid exact-scale workload bundle passing;
- missing profile;
- missing window;
- shallow metric rows;
- missing required metric;
- missing/skipped required metric value;
- string metric value;
- operation count below minimum;
- missing connection evidence;
- missing pipeline evidence;
- non-smoke profile without full-slot coverage;
- fixed hash-tag non-smoke profile;
- fixture-only workload artifacts;
- old real evidence plus incomplete workload artifacts;
- split directories that only pass if incorrectly combined;
- H06 stage exit requiring `assert_workload_benchmark_strength.json`.

## Gates

Run compile, pytest, manifest build, taxonomy, workload strength, fixture/legacy/subagent scans, and stage exit:

```text
PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h06 python3 -m compileall -q scripts src tests
python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h tests/unit/test_workload_benchmark.py tests/artifacts/test_workload_benchmark_artifacts.py
python3 scripts/m1h/build_evidence_manifest.py --stage H06_WORKLOAD_BENCHMARK_HARDENING --out runs/m1-hardening/evidence_manifest.json
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H06_WORKLOAD_BENCHMARK_HARDENING
python3 scripts/m1h/assert_workload_benchmark_strength.py --stage H06_WORKLOAD_BENCHMARK_HARDENING
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H06_WORKLOAD_BENCHMARK_HARDENING
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H06_WORKLOAD_BENCHMARK_HARDENING
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H06_WORKLOAD_BENCHMARK_HARDENING
python3 scripts/m1h/assert_stage_exit.py --stage H06_WORKLOAD_BENCHMARK_HARDENING
```

## Expected Current State

The H06 workload gate should exit 0 only because blocked claims are explicit and safe. The gate JSON should report `workload_claim_status: BLOCKED_WITH_REASON`, with all four workload claims blocked and no milestone PASS promotion.

## Review Risks

- Do not let management workload impact rows masquerade as C08 benchmark evidence.
- Do not accept config-only connection/pipeline fields.
- Do not rely on schema validation alone; numeric and coverage semantics must be checked in Python.
- Keep evidence grouping directory-scoped to prevent accidental assembly of a PASS from unrelated artifacts.
