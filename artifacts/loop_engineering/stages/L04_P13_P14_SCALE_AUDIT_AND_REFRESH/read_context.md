# L04 Read Context

Stage: `L04_P13_P14_SCALE_AUDIT_AND_REFRESH`
Started: `2026-06-30T07:19:55Z`
Base commit: `cea85f24bdf6e16f7f75c8a76b4bd8c96e9ddb85`

## Files Read

- `README.md`: project remains an artifact-first local Valkey scale lab.
- `AGENTS.md`: P14 must not be run without explicit opt-in; default phases remain capped at 100 nodes; missing metrics must be explicit.
- `CODEX_START_HERE.md`: automatic completion is through `P13_SCALE_LADDER_50_100`; `P14_SCALE_1000_OPTIN_DRYRUN` requires explicit user opt-in and `VSLAB_ALLOW_1000_DRYRUN`.
- `codex/phase_manifest.json`: P13 is automatic and real-Valkey-required; P14 is non-automatic, real-Valkey-not-required, dry-run/resource/planner only.
- `.github/workflows/codex-gates.yml` and `.github/workflows/github-coverage-gates.yml`: static CI now includes audit, provenance, metric coverage, and loop-engineering gates.
- `codex/loop_engineering/START_MAIN_LOOP.md`: after a pushed stage, immediately begin the next stage with fresh read-context.
- `codex/loop_engineering/00_OPERATING_CONTRACT.md`: do not weaken existing harness; all subagent roles and stage artifacts are required.
- `codex/loop_engineering/01_STAGE_LOOP_PROTOCOL.md`: L04 must follow read-context, previous harness, design agents, harness-first work, implementation, review/validation/anti-regression, commit, push.
- `codex/loop_engineering/02_AGENT_PROTOCOL.md`: required subagent JSON paths and verdict rules.
- `codex/loop_engineering/03_HARNESS_POLICY.md`: P14 dry-run/resource/planner artifacts must never count as real coverage.
- `codex/loop_engineering/04_STAGE_MANIFEST.md`: L04 must audit P13 50/100 evidence, timing, cleanup, scale report, empty artifacts, postcheck compatibility, and P14 dry-run boundaries.
- `codex/loop_engineering/05_VALIDATION_COMMANDS.md`: baseline validation plus audit/provenance/metric coverage gates are relevant; real 30/50/100 wrappers are listed only when explicitly needed and must not be used to refresh artifacts without recording commands.
- `codex/loop_engineering/06_STATE_AND_ARTIFACT_CONTRACT.md`: stage artifacts must be machine-readable and committed.
- `artifacts/loop_engineering/global_loop_state.json`: current stage is `L04_P13_P14_SCALE_AUDIT_AND_REFRESH`; L03 is PASS and pushed.
- `artifacts/loop_engineering/stages/L03_METRIC_CATALOG_AND_COVERAGE_MATRIX/stage_result.json`: L03 passed, added metric catalog and coverage matrix, and did not execute P14 or real/fault wrappers.
- `artifacts/phases/P13_SCALE_LADDER_50_100/*`: P13 has 50/100 scale rung, real Valkey evidence, timing breakdown, runtime breakdown, setup timeline, cleanup, preflight, report, state, snapshots, logs, and node config artifacts.
- `artifacts/phases/P13O_CLUSTER_CREATE_AB/*` and `artifacts/phases/P13O_REPLICA_REPLICATE_BREAKDOWN/*`: related P13 optimization artifacts exist and may need explicit audit classification, but L04 must not rewrite them to hide historical boundaries.
- `artifacts/phases/P02_PLANNER/scale_1000_dryrun_plan.json`: existing 1000-node plan is planner dry-run evidence only, under P02, not P14 real coverage.
- `schemas/artifact/p13_timing_breakdown.schema.json`, `schemas/artifact/p13_fast_test_split.schema.json`, `schemas/artifact/p13_setup_exhaustive_timeline.schema.json`: existing P13 schemas are likely reusable/strengthenable for L04.
- `tests/scale`, `tests/audit`, `tests/ci/test_postcheck_compatibility.py`, `scripts/audit_committed_artifacts.py`, `scripts/build_metric_coverage_matrix.py`: existing tests and builders already inspect parts of P13/P14, but L04 requires stronger P13/P14-specific invariants.

## Constraints

- Do not run `P14_SCALE_1000_OPTIN_DRYRUN`; the user has not opted in for this session.
- Do not execute 1000-node real or dry-run commands; L04 may audit existing dry-run planner boundaries only.
- Do not modify historical P13/P14 phase or gate artifacts to manufacture consistency.
- If P13 artifacts are refreshed, the command must be recorded and produced by the correct wrapper/gate path; handwritten PASS is forbidden.
- Keep P13 real 50/100 evidence separate from P14 dry-run/resource/planner evidence.
- Preserve L00-L03 harness behavior.
- Any missing timing/cleanup/report field must become `MISSING`, `SKIPPED_WITH_REASON`, or a blocking finding; never invent numeric values.

## Initial Risks

- P13 has historical gate command/manifest mismatch noted by prior audit; L04 must audit it explicitly rather than hiding it.
- P13 timing artifacts may have partial field coverage; L04 must validate setup, cluster create, replica config, probe, cleanup, and accounting fields without broadening schemas weakly.
- Related `P13O_*` optimization artifacts can confuse main P13 evidence classification if not separated.
- P14 has no automatic gate directory by design; tests must assert that this absence is correct unless explicit opt-in is present.
- Existing static reports may read P13/P14 artifacts but must not become source-of-truth.
