# L01_EXISTING_ARTIFACT_AUDIT_HARD_GATE Read Context

## Files Read

- `README.md`: original phase loop stops after `P13_SCALE_LADDER_50_100`; `P14_SCALE_1000_OPTIN_DRYRUN` is not automatic.
- `AGENTS.md`: machine-readable artifacts are the product; harness controls must not be weakened; missing metrics must use `MISSING` or `SKIPPED_WITH_REASON`; P14 must not run without explicit opt-in.
- `CODEX_START_HERE.md`: original P00-P13 loop is complete; P14 requires `VSLAB_ALLOW_1000_DRYRUN=I_UNDERSTAND_THIS_IS_NOT_A_DEFAULT_GATE`.
- `codex/phase_manifest.json`: read in full for L01; `default_max_nodes` is 100, `automatic_stop_after` is P13, P00-P13 are automatic, P14 is `automatic: false`, and real Valkey requirements apply from P03 through P13.
- `.github/workflows/codex-gates.yml`: locked workflow still runs harness precheck, safety scan, and unit tests.
- `.github/workflows/github-coverage-gates.yml`: now also runs loop-engineering validator and loop-engineering tests from L00.
- `codex/loop_engineering/README.md`: loop-engineering layer requires stage-by-stage persistent audit evidence.
- `codex/loop_engineering/00_OPERATING_CONTRACT.md`: L01 must pass previous harness first, design current harness, implement, validate, review, anti-regression check, commit, and push.
- `codex/loop_engineering/01_STAGE_LOOP_PROTOCOL.md`: defines required stage artifacts and subagent sequence.
- `codex/loop_engineering/02_AGENT_PROTOCOL.md`: requires seven subagent JSON outputs.
- `codex/loop_engineering/03_HARNESS_POLICY.md`: baseline commands remain required; anti-regression must block harness weakening.
- `codex/loop_engineering/04_STAGE_MANIFEST.md`: L01 must add `scripts/audit_committed_artifacts.py`, `schemas/artifact/audit_report.schema.json`, `tests/audit/test_committed_artifact_audit.py`, and `tests/ci/test_committed_artifact_audit_gate.py`.
- `codex/loop_engineering/05_VALIDATION_COMMANDS.md`: L01 audit validation commands are `python3 scripts/audit_committed_artifacts.py --out artifacts/loop_engineering/reports/audit_report.json`, `python3 -m pytest -q tests/audit`, and `python3 -m pytest -q tests/ci/test_committed_artifact_audit_gate.py`.
- `codex/loop_engineering/06_STATE_AND_ARTIFACT_CONTRACT.md`: L01 must persist read context, stage state, previous harness result, design, harness plan, commands, subagents, validation result, anti-regression report, and stage result.
- `artifacts/loop_engineering/global_loop_state.json`: L00 is PASS and pushed; current stage is `L01_EXISTING_ARTIFACT_AUDIT_HARD_GATE`.
- `artifacts/loop_engineering/stages/L00_LOOP_ENGINE_HARNESS_BOOTSTRAP/stage_result.json`: L00 completed with all subagent verdicts approved and loop-engineering validation harness in place.

## Current Stage

`L01_EXISTING_ARTIFACT_AUDIT_HARD_GATE` is selected because it is the first loop-engineering stage not marked PASS in `artifacts/loop_engineering/global_loop_state.json`.

## Constraints

- Do not run `P14_SCALE_1000_OPTIN_DRYRUN`; L01 may audit its dry-run/opt-in boundary only.
- Do not weaken original harness controls, codex gates, schemas, docs, templates, or locked workflow files.
- L01 audit must be artifact-first: it may inspect committed JSON/JSONL artifacts, gate results, schemas, manifests, and audit decisions, not infer truth from Markdown reports.
- P00-P13 automatic phase artifacts must be auditable.
- P13 must not be excluded solely due to historical command mismatch; such mismatches must be explicit findings.
- P14 must be identified as opt-in dry-run and must not count as real 1000-node Valkey evidence.
- Empty JSON artifacts, missing schema, missing producer, missing run_id, and missing status must be detected.

## Risks

- Existing committed artifacts may contain historical mismatches; L01 must classify them without hiding them or mutating historical gate results.
- The audit gate must distinguish blocking findings from informational or historical findings.
- The audit report schema must not be so loose that empty artifacts or dry-run evidence pass silently.
- Anti-regression must ensure L01 does not weaken `tests/ci/test_postcheck_compatibility.py` or phase manifest requirements to make historical artifacts look better.
