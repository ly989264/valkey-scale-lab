# L00_LOOP_ENGINE_HARNESS_BOOTSTRAP Read Context

## Files Read

- `README.md`: bootstrap repository overview; original automatic phase loop stops after `P13_SCALE_LADDER_50_100`; `P14_SCALE_1000_OPTIN_DRYRUN` is not automatic.
- `AGENTS.md`: controlling repository contract; requires `CODEX_START_HERE.md` before edits, preserves harness files, forbids host network mutation, caps default development at 100 nodes, and requires real Valkey evidence from P03 onward.
- `CODEX_START_HERE.md`: original phase loop entry; `python3 scripts/codex_gate.py next` reports `COMPLETE_AUTOMATIC_PHASES`; P14 requires explicit opt-in environment variable and is not automatic.
- `codex/phase_manifest.json`: P00-P13 are automatic; P14 is `automatic: false`; default max nodes is 100; Valkey version evidence must be 9.1.x where real gates are required.
- `.github/workflows/codex-gates.yml`: CI runs harness precheck, safety scan, and unit tests.
- `.github/workflows/github-coverage-gates.yml`: CI also runs postcheck compatibility, unit/CLI, config/planner, runtime/fault/failover/orchestration, analysis/report/stability/scale tests.
- `codex/loop_engineering/README.md`: loop-engineering layer adds stricter audit, state persistence, multi-agent outputs, and stage validation on top of the existing harness.
- `codex/loop_engineering/00_OPERATING_CONTRACT.md`: each stage must pass previous harness, design current harness first, produce subagent JSON outputs, validate, run anti-regression review, commit, and push.
- `codex/loop_engineering/01_STAGE_LOOP_PROTOCOL.md`: defines Phase A-H stage workflow; L00 must begin with read context and previous harness baseline.
- `codex/loop_engineering/02_AGENT_PROTOCOL.md`: defines required subagent JSON schemas and verdict gating.
- `codex/loop_engineering/03_HARNESS_POLICY.md`: previous baseline commands include codex precheck, safety scan, compileall, and pytest suites; L00 must provide loop validator coverage.
- `codex/loop_engineering/04_STAGE_MANIFEST.md`: no global loop state exists, so the first stage is `L00_LOOP_ENGINE_HARNESS_BOOTSTRAP`.
- `codex/loop_engineering/05_VALIDATION_COMMANDS.md`: L00 must make `scripts/loop_engineering_validate.py` and `tests/loop_engineering tests/ci/test_loop_engineering_pack.py` pass in addition to baseline commands.
- `codex/loop_engineering/06_STATE_AND_ARTIFACT_CONTRACT.md`: defines expected loop artifact layout, state JSON, command JSONL, and stage result JSON structure.
- `artifacts/loop_engineering/global_loop_state.json`: absent.
- `artifacts/loop_engineering/stages/*/stage_result.json`: absent.

## Current Stage

`L00_LOOP_ENGINE_HARNESS_BOOTSTRAP` is selected because `artifacts/loop_engineering/global_loop_state.json` does not exist and no prior loop-engineering stage result exists.

## Constraints

- Do not execute `P14_SCALE_1000_OPTIN_DRYRUN`; only audit its dry-run and opt-in boundary unless the user explicitly opts in during this Codex App session.
- Preserve pre-authored harness controls; any harness change must strengthen or preserve requirements.
- Do not modify host network configuration, global firewall, routing, host interfaces, or unrelated processes.
- Default development phases remain capped at 100 nodes.
- All loop state, commands, subagent outputs, validation results, and anti-regression decisions must be persisted under `artifacts/loop_engineering`.
- Completion requires commit and push to `origin/codex/valkey-scale-lab-loop`.

## Observed Repository State

- Startup check found branch `codex/valkey-scale-lab-loop` at the same commit as `origin/codex/valkey-scale-lab-loop`.
- `python3 scripts/codex_gate.py next` returned `COMPLETE_AUTOMATIC_PHASES` for the original P00-P13 phase loop.
- Existing untracked files before loop work: `artifacts/.DS_Store` and `codex/.DS_Store`.
- Loop-engineering artifacts are newly initialized in this stage.
- Existing source tree lacks `schemas/loop_engineering/*.schema.json`, `scripts/loop_engineering_validate.py`, `tests/loop_engineering/test_loop_state_contract.py`, and `tests/ci/test_loop_engineering_pack.py`.

## Stage Risks

- Baseline tests may fail before L00 work; protocol requires fixing baseline failures before current harness design.
- `commands.jsonl` must remain valid JSONL with command arrays and output tails; malformed command logs would undermine the loop audit.
- Subagent outputs are required even if implemented with isolated local artifacts rather than external agent tooling.
- Anti-regression checks must not mistake new loop harness files for a bypass of the original phase harness.
- P14 dry-run material can be audited in later stages, but it must not be run automatically in L00.
