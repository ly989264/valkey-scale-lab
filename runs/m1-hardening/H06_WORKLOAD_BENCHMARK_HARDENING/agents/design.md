role: design
agent_invocation: real_subagent
stage_id: H06_WORKLOAD_BENCHMARK_HARDENING
source_commit_before: 038bf1cf50aa04b1c575352e4f326eeb91886e74
source_commit_after: MISSING

# H06 Workload Benchmark Design

## Context Summary

H06 must close the workload benchmark gap that allowed weak workload evidence to appear acceptable. The current repository should stay honest: `workload_benchmark.real_exact.30`, `.50`, `.100`, and `.200` must remain `BLOCKED_WITH_REASON` until exact-scale, M1-format, real Valkey 9.1.x benchmark evidence exists.

Current state inspected:

- `scripts/m1h/assert_workload_benchmark_strength.py` is still a generic capability wrapper.
- `scripts/m1h/manifest.py` only checks `exact_scale_observed`, `workload_windows_present`, and `qps_latency_error_metrics_present` for workload claims.
- Current manifest already blocks workload claims, but the reasons are generic and the semantics are too weak for C08.
- Existing 50/100/200 artifacts include workload windows and metrics, but they are operation-scoped management/full-flow workload rows, not full C08 benchmark evidence. They lack the required profile matrix, often lack `profiles_covered` and top-level slot coverage, and do not prove full benchmark profile/window depth.
- 30-node workload evidence is only fixture-sourced in the current manifest.

## Proposed Code Changes

1. Add C08 constants and evaluator plumbing in `scripts/m1h/manifest.py`.

   Add:

   - `C08_WORKLOAD_PROFILES = ("smoke", "uniform", "hotspot", "mixed_rw", "write_heavy", "read_heavy")`
   - `C08_WORKLOAD_WINDOWS = ("baseline", "pre_event", "event", "recovery", "post_recovery", "all_run")`
   - `C08_REQUIRED_WORKLOAD_METRICS` with the canonical 18 required metric names from C08.
   - `C08_REQUIRED_METRIC_ROW_COUNT = 6 * 6 * 18`
   - `C08_DEFAULT_MIN_OPERATIONS_PER_WINDOW = 6`, with stricter per-artifact override support only when the artifact records a higher configured minimum.

   Replace the workload entry in `CAPABILITY_REQUIRED_CHECKS` with semantic checks such as:

   - `real_valkey_verified`
   - `exact_scale_observed`
   - `valkey_9_1_verified`
   - `workload_windows_present`
   - `workload_windows_schema_valid`
   - `workload_artifact_status_pass`
   - `profiles_complete`
   - `windows_complete_per_profile`
   - `required_metrics_present`
   - `required_metrics_numeric`
   - `metric_rows_present`
   - `metric_rows_schema_consistent`
   - `metric_row_count_sufficient`
   - `operations_per_window_sufficient`
   - `connections_evidence_present_or_blocked`
   - `pipeline_evidence_present_or_blocked`
   - `full_slot_coverage_non_smoke`
   - `no_fixture_workload_artifacts`
   - `synthetic_or_partial_not_promoted`

2. Add `evaluate_workload_benchmark_claim(root, scale, paths, evidence)` in `scripts/m1h/manifest.py`.

   The evaluator should group candidate artifacts by directory and score each group independently. A single claim must not be assembled by mixing profiles, windows, or metric rows from multiple phase directories. Each candidate group should include:

   - `workload_windows.json`
   - `metrics_timeseries.jsonl`
   - `valkey_e2e_evidence.json`

   A candidate is accepted only when all C08 checks pass against that same directory. The manifest should store diagnostics under `diagnostics.workload_h06_acceptance`, mirroring the H03/H04/H05 pattern:

   ```json
   {
     "accepted": false,
     "checks": {},
     "reasons": [],
     "artifact_path": ".../workload_windows.json",
     "metrics_path": ".../metrics_timeseries.jsonl",
     "required_profiles": [],
     "required_windows": [],
     "required_metrics": [],
     "required_metric_row_count": 648
   }
   ```

   `_evidence_kind` should return `REAL_EXACT_SCALE` for workload only when `workload_h06_acceptance.accepted` is true. `_claim_passes` already requires `hardening_stage_accepted`, so set `hardening_stage_accepted` from the workload H06 diagnostic just as setup/command/management do.

3. Implement strict workload artifact checks.

   The evaluator should:

   - validate `workload_windows.json` against `schemas/artifact/workload_windows.schema.json`;
   - require top-level `artifact_type: workload_windows`, `status: PASS`, exact `scale` or `node_count` when present, and no fixture path;
   - require `profiles_covered` to contain exactly or at least all six C08 profiles;
   - require one row for every profile/window pair;
   - require every required metric in each row's `metrics`;
   - require every required metric value to be numeric in a real PASS;
   - reject `MISSING`, `SKIPPED_WITH_REASON`, dict-style missing placeholders, booleans, nulls, strings, NaN-like values, and absent missing reasons in a real PASS;
   - require `ok_ops + error_ops` to meet the configured minimum per window;
   - require `metrics_timeseries.jsonl` rows for every profile/window/metric triple, with `source_type: workload`, exact `scale` or `node_count`, numeric `metric_value`, matching labels, and no missing reason for required metrics;
   - require metric row count >= 648 for the C08 minimum set;
   - require non-smoke profiles to prove full slot coverage using `hash_slot_coverage[profile]` and per-window `key_slot_coverage`: `full_slot_requested: true`, `full_slot_covered: true`, `slot_count_observed: 16384`, and `fixed_hash_tag_only: false`;
   - require `smoke` to be allowed to use narrower coverage, but still require all metrics and windows;
   - require connection and pipeline evidence. For current writers this can be added as top-level `client_execution` or per-window `config` plus explicit `connection_evidence` and `pipeline_evidence`. A real PASS needs numeric observed values; if unavailable, mark the claim blocked rather than accepting the run.

4. Replace `scripts/m1h/assert_workload_benchmark_strength.py` with a workload-specific gate.

   Follow `assert_management_exact_scale.py` structure. The gate should:

   - read `runs/m1-hardening/evidence_manifest.json`;
   - inspect required scales `{30, 50, 100, 200}`;
   - treat honest blocked claims as stage-gate PASS, while exposing `workload_claim_status: BLOCKED_WITH_REASON` in the gate JSON;
   - reject any workload claim that says `PASS` without `REAL_EXACT_SCALE`, complete C08 semantic checks, and `diagnostics.workload_h06_acceptance.accepted: true`;
   - require blocked claims to include H06 diagnostics and concrete missing evidence reasons;
   - summarize blocked claims with scale, reason, failed C08 reasons, and selected candidate artifact paths.

5. Update `scripts/m1h/assert_stage_exit.py`.

   Add:

   ```python
   H06_REQUIRED_GATE_RESULTS = [
       "build_evidence_manifest",
       "assert_evidence_taxonomy",
       "assert_workload_benchmark_strength",
       "assert_no_fixture_fallback",
       "assert_no_legacy_m1_pass",
       "assert_no_simulated_subagents",
   ]
   ```

   Register it under `STAGE_REQUIRED_GATE_RESULTS["H06_WORKLOAD_BENCHMARK_HARDENING"]`.

6. Strengthen runtime writers for future evidence, without promoting existing artifacts.

   In `src/valkey_scale_lab/workload/__init__.py` and the runtime writers that emit `workload_windows.json`:

   - record `operations_per_window_min`, actual per-window operation count, `profiles_covered`, `hash_slot_coverage`, and `workload_mode`;
   - emit connection and pipeline observation fields, not just requested config;
   - ensure metric rows include labels for `profile` and `window_name`, exact scale/node count, and all required C08 metric names;
   - keep current generated evidence blocked if it lacks actual connection/pipeline or full profile/window depth.

   This writer work is useful so future real runs can produce acceptable artifacts, but H06 should not manufacture new exact-scale evidence.

7. Schema changes.

   `schemas/artifact/workload_windows.schema.json` already contains the C08 metric names, but it is permissive. Tighten it carefully:

   - require `profiles_covered`, `hash_slot_coverage`, and `workload_mode` for benchmark-mode artifacts;
   - define required metrics as numbers or structured missing placeholders for general schema compatibility;
   - leave final real-PASS numeric enforcement in `scripts/m1h/manifest.py`, because blocked and test artifacts may legitimately encode missing values with reasons.

## Tests

Add focused tests in `tests/m1h/test_gate_framework.py`.

Required positive test:

- `test_workload_benchmark_valid_exact_scale_can_pass_after_h06_hardening`: construct a temporary 30-node phase with real Valkey 9.1.x evidence, all six profiles, all six windows, 648+ required metric rows, numeric metrics, sufficient operations, connection/pipeline evidence, and full-slot coverage for all non-smoke profiles. Assert the claim becomes `PASS`, `evidence_kind` is `REAL_EXACT_SCALE`, and `assert_workload_benchmark_strength` reports that scale as passed.

Required negative tests:

- missing profile blocks;
- missing window for one profile blocks;
- one metric row or shallow row count blocks;
- required metric missing blocks;
- required metric set to `MISSING` or `SKIPPED_WITH_REASON` blocks real PASS;
- string metric values block;
- `ok_ops + error_ops` below the configured minimum blocks;
- absent connection evidence blocks;
- absent pipeline evidence blocks;
- non-smoke profile without full slot coverage blocks;
- fixed hash-tag non-smoke profile blocks;
- fixture-sourced workload artifacts remain blocked;
- old real Valkey evidence plus incomplete workload artifacts remains blocked;
- candidate grouping test: profile rows split across two directories must not combine into a single PASS;
- H06 stage exit requires `assert_workload_benchmark_strength.json`.

Keep fixture/schema tests for `scripts/assert_workload_benchmark_contract.py`, but do not let fixture success imply exact-scale acceptance.

## Gates To Run

Run these during the worker stage:

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

Expected current-repository outcome before new real benchmark runs: the H06 workload gate exits 0 with gate `status: PASS`, while `workload_claim_status` and all four workload claims remain `BLOCKED_WITH_REASON` with explicit missing C08 reasons.

## Acceptance Criteria

H06 is acceptable when:

- exact-scale workload claims exist for 30, 50, 100, and 200 nodes;
- a claim can pass only with one same-directory evidence bundle that proves exact node scale, real Valkey, Valkey 9.1.x, M1 workload windows, metrics JSONL, and complete C08 benchmark semantics;
- all C08 profiles, windows, metrics, metric rows, numeric values, operation counts, connection/pipeline observations, and slot-coverage rules are enforced;
- fixture, historical-only, dry-run, smaller-scale, synthetic, or incomplete evidence cannot promote a workload benchmark claim;
- current repository evidence remains blocked rather than passing by accident;
- `assert_stage_exit.py` requires the H06 workload gate result.

## Blocked-State Expectations

Current H06 claims should remain blocked because:

- scale 30 lacks non-fixture exact-scale workload benchmark artifacts;
- scale 50/100/200 artifacts are real Valkey context plus workload windows, but do not satisfy the C08 benchmark profile/window/metric-depth contract;
- current artifacts do not prove the complete profile matrix, full-slot non-smoke coverage, and observed connection/pipeline behavior required for real PASS.

Blocked claim detail should include:

- `capability: workload_benchmark`;
- scale;
- selected candidate artifact paths;
- required artifacts;
- failed C08 checks;
- missing fields;
- a rerun hint such as running the exact-scale benchmark scenario that emits `workload_windows.json`, `metrics_timeseries.jsonl`, and `valkey_e2e_evidence.json` in one phase directory.

## Review Risks

- The biggest risk is accidentally evaluating workload windows from one directory and Valkey evidence or metrics from another. Keep candidate evaluation directory-scoped.
- Current runtime artifacts may use management workload rows that look benchmark-like. The H06 gate must distinguish management impact windows from C08 benchmark coverage.
- `workload_windows.schema.json` is permissive by design; semantic checks must do the real acceptance work.
- Connection and pipeline config fields alone are not enough. Require observed execution evidence or block.
- The stage gate should pass an honest blocked state, not require scarce exact-scale runs during H06 implementation.
