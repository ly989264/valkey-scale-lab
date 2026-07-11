# L03_METRIC_CATALOG_AND_COVERAGE_MATRIX Read Context

## Files Read

- `README.md`: project is a local-first Valkey scale lab where machine-readable artifacts are the product.
- `AGENTS.md`: safety rules forbid default 1000-node execution, host network mutation, fake-only real evidence, and weakening harness controls.
- `CODEX_START_HERE.md`: automatic loop remains bounded before P14; reports and views must read artifacts.
- `codex/phase_manifest.json`: current committed phase artifacts and automatic phase boundaries remain the source for phase requirements.
- `.github/workflows/codex-gates.yml`: existing codex gates remain untouched.
- `.github/workflows/github-coverage-gates.yml`: L00/L01/L02 static loop/audit/provenance checks are now part of CI and must remain passing.
- `codex/loop_engineering/README.md`: loop-engineering artifacts under `artifacts/loop_engineering/` are persistent audit evidence.
- `codex/loop_engineering/00_OPERATING_CONTRACT.md`: harness controls must not be weakened; harness exceptions require explicit artifacts.
- `codex/loop_engineering/01_STAGE_LOOP_PROTOCOL.md`: run read-context, previous harness, design subagents, harness-first implementation, worker, review/validation/anti-regression, result, commit, and push.
- `codex/loop_engineering/02_AGENT_PROTOCOL.md`: required subagent roles and JSON response contract.
- `codex/loop_engineering/03_HARNESS_POLICY.md`: previous harness baseline, artifact-first behavior, missing-data semantics, real Valkey evidence boundaries, and anti-regression checks.
- `codex/loop_engineering/04_STAGE_MANIFEST.md`: L03 requires metric catalog and coverage matrix schemas, builder, tests, and generated JSON artifacts.
- `codex/loop_engineering/05_VALIDATION_COMMANDS.md`: L03 validation must run `build_metric_coverage_matrix.py` plus `tests/metrics tests/coverage`; previous harness remains mandatory.
- `codex/loop_engineering/06_STATE_AND_ARTIFACT_CONTRACT.md`: required stage state, command log, validation result, and stage result schemas.
- `artifacts/loop_engineering/global_loop_state.json`: L00, L01, and L02 are PASS and pushed; current stage is L03.
- `artifacts/loop_engineering/stages/L00_LOOP_ENGINE_HARNESS_BOOTSTRAP/stage_result.json`: loop harness bootstrap evidence is complete.
- `artifacts/loop_engineering/stages/L01_EXISTING_ARTIFACT_AUDIT_HARD_GATE/stage_result.json`: committed artifact audit evidence is complete.
- `artifacts/loop_engineering/stages/L02_EVIDENCE_PROVENANCE_DAG/stage_result.json`: provenance DAG evidence is complete at commit `3aeb587ede3364bd1158813ded6092f95580a990`.

## L03 Scope

L03 must establish a unified metric catalog and coverage matrix covering cluster build, management, workload, observability, fault, failover, stability, cleanup, scale, report, and visualization surfaces.

Required new or strengthened artifacts:

- `schemas/artifact/metric_catalog.schema.json`
- `schemas/artifact/coverage_matrix.schema.json`
- `scripts/build_metric_coverage_matrix.py`
- tests verifying fake plus real artifact coverage
- `artifacts/loop_engineering/reports/metric_catalog.json`
- `artifacts/loop_engineering/reports/coverage_matrix.json`

## Constraints

- Do not run or present P14 as real 1000-node evidence.
- Coverage matrix must explicitly layer fake, small-real, 30, 50, 100, and 1000-dry-run coverage.
- Every catalog metric must include name, unit, source artifact, scenario, node-count scope, and missing semantics.
- Missing values must be encoded as `MISSING` or `SKIPPED_WITH_REASON`, never invented.
- Preserve L00/L01/L02 behavior and CI coverage.
- Do not mutate historical phase/gate artifacts to make metric coverage look better.

## Risks

- Historical artifacts use different metric shapes, so the catalog builder must normalize from machine-readable artifacts instead of Markdown or report views.
- The coverage matrix can accidentally overstate P14 by treating 1000 dry-run planner evidence as real coverage.
- Generated report artifacts may tempt schema weakening; L03 must add schema-backed artifacts and negative tests.
- Previous harness now includes L02 provenance checks, so generated timestamp-only or pycache changes must be cleaned before commit.
