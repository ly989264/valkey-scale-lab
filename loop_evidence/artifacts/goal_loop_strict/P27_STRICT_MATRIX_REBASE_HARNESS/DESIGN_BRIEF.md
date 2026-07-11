# DESIGN_BRIEF — P27_STRICT_MATRIX_REBASE_HARNESS

## Fresh read confirmation

Read the strict design prompt, `AGENTS.md`, `CODEX_START_HERE.md`, `CODEX_GOAL_LOOP_START.md`, `CODEX_STRICT_MATRIX_LOOP_START.md`, baseline goal-loop docs `00_INDEX.md` through `10_AUDIT_AND_COMMIT_POLICY.md`, strict docs `00_INDEX.md` through `12_AUDIT_COMMIT_NO_BYPASS_POLICY.md`, current stage doc `docs/codex/goal-loop-strict/stages/P27_STRICT_MATRIX_REBASE_HARNESS.md`, and `artifacts/goal_loop_strict/P27_STRICT_MATRIX_REBASE_HARNESS/CONTEXT_RELOAD.md`.

## Stage objective

Implement P27 only: append strict automatic stages P27-P40 to `codex/phase_manifest.json`, set `automatic_stop_after` to `P40_STRICT_FINAL_AUDIT_CLOSEOUT`, preserve `default_max_nodes=100` and P14 non-automatic, add strict fail-closed harness/postcheck behavior and assertion script scaffolding, and emit P27 harness-only artifacts without claiming real Valkey runtime evidence.

## Current repository findings

- `codex/phase_manifest.json` currently has `automatic_stop_after: P26_FINAL_REPORT_REGRESSION`, `default_max_nodes: 100`, completed P15-P26 entries, and P14 present as `P14_SCALE_1000_OPTIN_DRYRUN`.
- `codex/status/phase_state.json` marks P00-P13 and P15-P26 complete, not P14, and no P27-P40 entries exist.
- `scripts/codex_gate.py` hard-codes `GOAL_LOOP_LAST = "P26_FINAL_REPORT_REGRESSION"`, `HARNESS_ONLY_NO_REAL_VALKEY = {"P15_GOAL_REBASE_HARNESS_EXTENSION"}`, `BOUNDED_SCALE_EXCEPTIONS = {"P21_FAILOVER_LATENCY_CURVE_200": 200}`, and `is_goal_loop_stage()` only recognizes P15-P26.
- Existing postcheck validates manifest, lock, gate result, required artifacts, real evidence, audit artifacts, and `artifacts/goal_loop/<P15-P26>/REVIEW.md`; it does not yet validate `artifacts/goal_loop_strict/<P27-P40>/REVIEW.md`, strict stage journal, strict review coverage IDs, or strict audit citations.
- Existing assertion scripts cover P15-P26 names only. Required strict scripts such as `scripts/assert_strict_stage_contract.py`, `scripts/assert_no_bypass.py`, and `scripts/assert_exact_scale_real_evidence.py` are absent.
- Existing schemas `phase_summary.schema.json` and `quant_summary.schema.json` allow extra properties and can support P27 harness-only summaries. New schemas are still needed for P27 `harness_extension_report.json`, `strict_manifest_report.json`, and later strict artifacts.
- All strict stage docs P27-P40 exist under `docs/codex/goal-loop-strict/stages/`.
- `codex/gate_lock.json` locks harness controls and will fail after manifest/script/schema edits unless P27 transparently updates lock hashes and documents why the edits strengthen the harness.

## Scope boundaries

- P27 must not implement P28-P40 runtime behavior beyond manifest entries, shared strict assertion interfaces, schemas, tests, and fail-closed harness checks needed for future stages.
- P27 must not run real 50/100/200 node clusters, must not start >200 real resources, and must not create fake Valkey evidence.
- P27 may emit harness-only P27 artifacts with `real_valkey_claimed=false`, `management_runtime_claimed=false`, `fault_runtime_claimed=false`, and skipped runtime metrics encoded as `SKIPPED_WITH_REASON`.
- P27 must not edit `codex/status/phase_state.json` except through later `mark-complete` by the main agent after review and postcheck.

## Implementation plan

1. Update `codex/phase_manifest.json`.
   - Change `automatic_stop_after` to `P40_STRICT_FINAL_AUDIT_CLOSEOUT`.
   - Append P27-P40 in the exact order from `docs/codex/goal-loop-strict/02_STRICT_STAGE_MANIFEST.md`.
   - Keep `default_max_nodes` exactly `100`.
   - Keep P14 `automatic=false`.
   - Mark P27 as automatic, fake-only allowed, no real Valkey required, max_nodes `0`.
   - Mark P28/P37/P38/P39/P40 according to stage docs: non-runtime or provenance/report/dry-run gates as appropriate, without requiring live Valkey unless a stage doc requires a small real proof.
   - Mark P30/P31/P32/P33/P34/P35/P36 as real Valkey required at exact scale, with P32/P35/P36 as explicit bounded 200-node exceptions.
   - Add strict common gates to every P27-P40 entry: precheck, safety scan, compile, unit/integration tests, `assert_strict_stage_contract.py`, and `assert_no_bypass.py`.
   - Add stage-specific strict gates named in each strict stage doc, but do not use recursive `codex_gate.py run/postcheck` commands inside manifest gates.

2. Extend `scripts/codex_gate.py`.
   - Replace P15-P26 constants with named legacy and strict ranges, e.g. `LEGACY_GOAL_LOOP_LAST`, `STRICT_GOAL_LOOP_FIRST`, `STRICT_GOAL_LOOP_LAST`.
   - Set manifest validation to require `automatic_stop_after == P40_STRICT_FINAL_AUDIT_CLOSEOUT` once strict stages are present.
   - Allow harness-only/no-real stages only by explicit set, including P15 and P27, and possibly P28/P37/P38/P39/P40 only when their manifest semantics and stage docs justify no new live cluster.
   - Extend bounded exceptions to exactly `P21:200`, `P32:200`, `P35:200`, and `P36:200`; reject all other automatic phases with `max_nodes > 100`.
   - Enforce exact-scale real gate command requirements for P30-P36: `--nodes 50/100/200` or equivalent exact-scale assertion, no `--min-nodes 6` smoke-only substitution for those real-scale stages.
   - Add `is_strict_stage()` and `check_strict_review()` for `artifacts/goal_loop_strict/<STAGE_ID>/REVIEW.md`; require `Decision: PASS`, gate result relative path, gate sha256, required artifacts, and coverage IDs for coverage-owning stages.
   - Extend postcheck to require strict Markdown handoffs for P27-P40: `CONTEXT_RELOAD.md`, `DESIGN_BRIEF.md`, `WORKER_SUMMARY.md`, and `REVIEW.md`; P27 postcheck should not require `COMPLETION.md` before mark-complete because completion is written after mark-complete/commit/push.
   - Extend audit checks for P27-P40 to require `fresh_context=true`, gate result path/sha, required artifact paths, and strict stage journal entry when applicable after worker/review create it.

3. Add strict assertion scripts with shared helpers.
   - Prefer a small shared module such as `scripts/strict_harness_lib.py` for JSON/JSONL loading, manifest/stage lookup, missing-data checks, coverage row validation, and fail-closed error printing.
   - `assert_strict_stage_contract.py`: validate P27-P40 manifest order, stage docs exist, strict handoff paths exist for the phase, required manifest gates/artifacts are declared, P14 remains non-automatic, default cap is 100, P32/P35/P36 are the only new automatic 200-node exceptions, P37 is dry-run-only.
   - `assert_no_bypass.py`: scan manifest, gate result, audit/review text, changed strict artifacts, scripts, and command logs for manual PASS shortcuts, phase-state edits, fake-only gates for real stages, host networking mutation terms, sudo network commands, >200 real execution, and 200-node downshift. Use explicit test-fixture allowlists only in tests.
   - `assert_coverage_registry.py`: in `--bootstrap-only`, verify strict docs and expected coverage dimensions/IDs can be generated or are represented in a bootstrap report without requiring the P28 registry artifact yet. Future modes should fail on missing registry rows.
   - `assert_exact_scale_real_evidence.py`: fail closed for missing evidence; support `--nodes` exact checks for P30-P36 and `--min-nodes 6` for P29 collector smoke if required by its stage doc.
   - `assert_quant_completeness.py`, `assert_management_matrix_strict.py`, `assert_fault_matrix_strict.py`, `assert_full_flow_e2e.py`, `assert_200_plus_dry_run.py`, `assert_analysis_provenance.py`, `assert_report_quality.py`, and `assert_final_strict_closeout.py`: add fail-closed CLIs and core validation skeletons/tests in P27; do not make them pass on missing artifacts except where P27 explicitly runs only bootstrap modes.

4. Add P27 harness-only artifact emitter.
   - Create `scripts/strict_harness_artifacts.py --phase P27_STRICT_MATRIX_REBASE_HARNESS`.
   - Emit `phase_summary.json`, `quant_summary.json`, `harness_extension_report.json`, and `strict_manifest_report.json`.
   - Record manifest changes, strict assertion scripts added, schemas added, lock update reason, P14 preservation, default cap preservation, exact 200 exceptions, and `no_real_runtime_claimed=true`.
   - Encode absent runtime data as `SKIPPED_WITH_REASON` with reasons.

5. Add schemas.
   - Add `schemas/artifact/harness_extension_report.schema.json`.
   - Add `schemas/artifact/strict_manifest_report.schema.json`.
   - Add `schemas/artifact/strict_coverage_registry.schema.json`, `strict_coverage_ledger.schema.json`, and `strict_no_runtime_created_proof.schema.json` if needed by P27 assertion tests and future manifest declarations.
   - Add report/provenance schemas for future strict gates only as minimal fail-closed interfaces if their manifest entries require schema validation now.

6. Add tests.
   - Update or add unit tests for strict manifest validation, bounded 200 exceptions, P14 non-automatic preservation, strict review requirement, strict stage contract failure on missing docs/handoffs, and anti-bypass detection.
   - Add integration tests that `scripts/assert_strict_stage_contract.py --phase P27_STRICT_MATRIX_REBASE_HARNESS` passes after P27 artifacts exist and fails on a temp manifest missing P40 or with `default_max_nodes != 100`.
   - Add tests proving strict assertion scripts fail on missing artifacts/empty JSONL/null missing values.

7. Update `codex/gate_lock.json`.
   - Recompute lock hashes only after all harness edits are complete.
   - Add new strict docs/scripts/schemas/templates that are harness controls if the lock policy requires them.
   - Ensure tests or a focused command prove a changed locked file is detected before the lock update, then passes after update. Document this in `harness_extension_report.json` and `WORKER_SUMMARY.md`.

## Harness plan

- P27 manifest gates should include:
  - `harness_precheck`: `python3 scripts/codex_gate.py precheck --phase P27_STRICT_MATRIX_REBASE_HARNESS`
  - `safety_static_scan`: `python3 scripts/safety_scan.py`
  - `scripts_compile`: `python3 -m compileall -q scripts src`
  - `unit_integration_tests`: `python3 -m pytest -q tests/unit tests/integration`
  - `strict_stage_contract`: `python3 scripts/assert_strict_stage_contract.py --phase P27_STRICT_MATRIX_REBASE_HARNESS`
  - `anti_bypass`: `python3 scripts/assert_no_bypass.py --phase P27_STRICT_MATRIX_REBASE_HARNESS`
  - `coverage_registry_bootstrap`: `python3 scripts/assert_coverage_registry.py --bootstrap-only`
  - `strict_harness_artifacts`: `python3 scripts/strict_harness_artifacts.py --phase P27_STRICT_MATRIX_REBASE_HARNESS`
- `codex_gate.py postcheck` must independently validate P27 required artifacts and strict review/audit, not trust worker summaries.
- Gate result files must be produced only by `scripts/codex_gate.py run`; no script should write `artifacts/gates/<STAGE_ID>/gate_result.json` directly.

## Schema and artifact plan

P27 required artifacts:

- `artifacts/phases/P27_STRICT_MATRIX_REBASE_HARNESS/phase_summary.json` using `schemas/artifact/phase_summary.schema.json`
- `artifacts/phases/P27_STRICT_MATRIX_REBASE_HARNESS/quant_summary.json` using `schemas/artifact/quant_summary.schema.json`
- `artifacts/phases/P27_STRICT_MATRIX_REBASE_HARNESS/harness_extension_report.json` using new strict schema
- `artifacts/phases/P27_STRICT_MATRIX_REBASE_HARNESS/strict_manifest_report.json` using new strict schema
- `artifacts/goal_loop_strict/P27_STRICT_MATRIX_REBASE_HARNESS/CONTEXT_RELOAD.md`
- `artifacts/goal_loop_strict/P27_STRICT_MATRIX_REBASE_HARNESS/DESIGN_BRIEF.md`
- `artifacts/goal_loop_strict/P27_STRICT_MATRIX_REBASE_HARNESS/WORKER_SUMMARY.md`
- `artifacts/goal_loop_strict/P27_STRICT_MATRIX_REBASE_HARNESS/REVIEW.md`
- `audit/P27_STRICT_MATRIX_REBASE_HARNESS/AUDIT.md`
- `audit/P27_STRICT_MATRIX_REBASE_HARNESS/audit_decision.json`
- `artifacts/gates/P27_STRICT_MATRIX_REBASE_HARNESS/gate_result.json`

Future strict schema interfaces likely needed by manifest declarations:

- `schemas/artifact/strict_coverage_registry.schema.json`
- `schemas/artifact/strict_coverage_ledger.schema.json`
- `schemas/artifact/strict_manifest_report.schema.json`
- `schemas/artifact/harness_extension_report.schema.json`
- `schemas/artifact/telemetry_completeness_report.schema.json`
- `schemas/artifact/no_runtime_created_proof.schema.json`
- `schemas/artifact/analysis_provenance.schema.json`
- `schemas/artifact/report_quality_report.schema.json`
- `schemas/artifact/final_strict_audit_report.schema.json`

## Coverage IDs targeted

P27 should not satisfy real user matrix coverage IDs for management or fault rows. It should target only harness/bootstrap coverage IDs in `harness_extension_report.json` or `strict_manifest_report.json`, for example:

- `strict.harness.manifest_p27_p40_appended`
- `strict.harness.automatic_stop_after_p40`
- `strict.harness.p14_non_automatic_preserved`
- `strict.harness.default_max_nodes_100_preserved`
- `strict.harness.bounded_200_exceptions_declared`
- `strict.harness.strict_review_required`
- `strict.harness.assertions_fail_closed`
- `strict.harness.p37_dry_run_only_declared`
- `strict.harness.no_real_runtime_claimed_by_p27`

All real scale IDs such as `50.management.remove_replica`, `100.fault.network_delay`, `200.lifecycle.cleanup_verify`, and >200 dry-run IDs such as `500.dry_run.no_runtime_created_proof` remain `PENDING` or not-yet-materialized until P28+.

## Test and gate plan

Run after implementation:

```bash
python3 scripts/codex_gate.py precheck --phase P27_STRICT_MATRIX_REBASE_HARNESS
python3 scripts/safety_scan.py
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
python3 scripts/assert_strict_stage_contract.py --phase P27_STRICT_MATRIX_REBASE_HARNESS
python3 scripts/assert_no_bypass.py --phase P27_STRICT_MATRIX_REBASE_HARNESS
python3 scripts/assert_coverage_registry.py --bootstrap-only
python3 scripts/codex_gate.py run --phase P27_STRICT_MATRIX_REBASE_HARNESS
python3 scripts/codex_gate.py postcheck --phase P27_STRICT_MATRIX_REBASE_HARNESS
```

Do not run `mark-complete`, commit, or push until worker summary, strict review, audit artifacts, gate result, postcheck, and required artifacts all pass.

## Safety constraints

- No `sudo` network, host firewall, route, PF, nftables, iptables, host interface, or OS network service changes.
- No real execution above 200 nodes; P37 must be dry-run-only.
- No default above 100 nodes; 200 is allowed only for P32/P35/P36 and existing P21 bounded exception.
- No downshifting of future 200-node real stages in manifest commands.
- No fake-only gates for real strict stages.
- No manual edits to `codex/status/phase_state.json` or `artifacts/gates/*/gate_result.json`.
- Every missing P27 runtime value must be `SKIPPED_WITH_REASON` with a reason.

## Blocked conditions

- Manifest validation cannot be made to pass with P27-P40 appended and `automatic_stop_after=P40_STRICT_FINAL_AUDIT_CLOSEOUT`.
- Strict postcheck cannot require `artifacts/goal_loop_strict/<STAGE_ID>/REVIEW.md` and audit citations without weakening P15-P26 behavior.
- Assertion scripts pass when required files are missing, malformed, empty, or contain silent missing values.
- P14 becomes automatic or `default_max_nodes` changes from 100.
- Any manifest gate permits real >200 execution by default.
- P27 artifacts claim real Valkey, management, fault, or large-scale runtime evidence.

## Risks

- Existing tests may assume `automatic_stop_after=P26_FINAL_REPORT_REGRESSION` and last 12 phases are P15-P26; update tests to distinguish legacy and strict loops.
- `codex_gate.py validate_manifest()` currently requires all automatic P03+ stages except P15 to require real Valkey; strict dry-run/report/provenance stages need explicit, narrow exemptions without opening fake-only real stages.
- Updating `codex/gate_lock.json` is necessary but sensitive; the worker must document before/after lock behavior.
- Future stage manifest gates may be too specific before implementation exists; P27 should declare fail-closed interfaces and required artifacts, not pretend future commands already produce evidence.

## 待验证

- 待验证: exact real-wrapper commands available for future P30-P36 exact 50/100/200 runs; P27 can require assertion gates but should avoid inventing runtime command semantics beyond existing CLI contract.
- 待验证: whether P28 should create the canonical coverage registry artifact or P27 should only bootstrap coverage expectations.
- 待验证: which new strict schemas should be minimal P27 interfaces versus deferred to the worker stage that first emits the artifact.
- 待验证: whether postcheck should require `STRICT_STAGE_JOURNAL.md` for P27 before completion, or only for P28+ after P27 completion is recorded.
- 待验证: exact allowlist needed for `assert_no_bypass.py` so tests with malicious fixture strings fail production checks without causing false positives in historical docs.
