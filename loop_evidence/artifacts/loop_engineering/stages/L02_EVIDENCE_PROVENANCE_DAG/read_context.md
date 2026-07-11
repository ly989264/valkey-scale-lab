# L02_EVIDENCE_PROVENANCE_DAG Read Context

## Files Read

- `README.md`: automatic work stops after `P13_SCALE_LADDER_50_100`; `P14_SCALE_1000_OPTIN_DRYRUN` is not automatic.
- `AGENTS.md`: machine-readable artifacts are the product; reports are views; no invented metrics; P14 cannot run without explicit opt-in; real Valkey evidence requires wrapper-produced 9.1.x proof.
- `CODEX_START_HERE.md`: P00-P13 automatic loop is the completion boundary; 1000-node behavior is opt-in dry-run/resource-check only.
- `codex/phase_manifest.json`: P00-P13 are automatic and required artifacts are schema-declared; P14 is `automatic=false`; P09, P11, P12, and P13 produce analysis/report/stability/scale artifacts relevant to L02 provenance.
- `.github/workflows/codex-gates.yml`: existing CI compiles scripts, runs precheck, safety scan, and unit tests.
- `.github/workflows/github-coverage-gates.yml`: fast CI now runs precheck, safety scan, phase compatibility, unit/config/planner/runtime/report/scale tests, loop validation, L01 committed artifact audit, and audit tests.
- `codex/loop_engineering/README.md`: every stage must re-read context, create persistent artifacts, use subagents, validate, commit, and push.
- `codex/loop_engineering/START_MAIN_LOOP.md`: current stage must follow `01_STAGE_LOOP_PROTOCOL.md`; after push, continue to the next stage.
- `codex/loop_engineering/00_OPERATING_CONTRACT.md`: do not weaken harness; all subagent roles and stage artifacts are required.
- `codex/loop_engineering/01_STAGE_LOOP_PROTOCOL.md`: L02 must run previous harness first, then design harness, implement, review, validate, anti-regression, stage result, commit, and push.
- `codex/loop_engineering/02_AGENT_PROTOCOL.md`: required JSON subagent outputs and verdict handling.
- `codex/loop_engineering/03_HARNESS_POLICY.md`: baseline commands, artifact-first rules, missing semantics, and anti-regression checks.
- `codex/loop_engineering/04_STAGE_MANIFEST.md`: L02 requires a provenance graph builder, DAG schema, source artifact hash check, and tests proving reports read artifacts but are not source of truth.
- `codex/loop_engineering/05_VALIDATION_COMMANDS.md`: baseline, loop validation, audit validation, and later metric/report command families.
- `codex/loop_engineering/06_STATE_AND_ARTIFACT_CONTRACT.md`: required stage state, commands, subagents, validation, anti-regression, and stage result artifacts.
- `artifacts/loop_engineering/global_loop_state.json`: L00 and L01 are PASS and pushed; current stage is `L02_EVIDENCE_PROVENANCE_DAG`.
- `artifacts/loop_engineering/stages/L00_LOOP_ENGINE_HARNESS_BOOTSTRAP/stage_result.json`: loop validation harness is established and pushed.
- `artifacts/loop_engineering/stages/L01_EXISTING_ARTIFACT_AUDIT_HARD_GATE/stage_result.json`: committed artifact audit is established and pushed.

## Current Stage Summary

L02 must build an artifact provenance DAG. The graph must trace analysis, report, scale, stability, and visualization-like artifacts back to machine-readable source artifacts with SHA256, schema, phase, producer, and run ID metadata where available. Reports must never become source-of-truth.

## Constraints

- Do not run `P14_SCALE_1000_OPTIN_DRYRUN`.
- Do not run real Valkey or fault wrappers unless a later L02 design requires it and it is safe; L02 is expected to be artifact/static validation.
- Do not edit historical `artifacts/gates`, `artifacts/phases`, or audit decisions to hide missing provenance.
- Missing provenance or metadata must be encoded as findings with `MISSING` or `SKIPPED_WITH_REASON`, not invented.
- Existing L00/L01 harness and CI coverage must remain intact.

## Risks

- Treating rendered HTML/Markdown reports as source artifacts instead of views would violate artifact-first discipline.
- Existing historical artifacts may lack producer or run_id; L02 must classify that gap without mutating committed artifacts.
- A broad graph builder can become too permissive unless tests prove missing source edges and SHA drift are blocking.
- P14 dry-run artifacts from P02 must not be represented as real 1000-node provenance.
