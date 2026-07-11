# L00_LOOP_ENGINE_HARNESS_BOOTSTRAP Stage Design

## Stage Scope

L00 establishes the loop-engineering harness itself. It does not add Valkey runtime behavior, does not refresh P00-P13 phase artifacts, and does not run `P14_SCALE_1000_OPTIN_DRYRUN`.

## Inputs

- Previous harness baseline passed after using a temporary venv for pytest.
- `requirements_analyst`, `harness_architect`, and `risk_auditor` all returned `APPROVED`.
- Current repository lacks the required L00 schema pack, validator CLI, loop-engineering tests, and CI pack test.

## Harness To Add

1. Add JSON schemas under `schemas/loop_engineering/` for:
   - command log entries;
   - subagent responses;
   - stage state;
   - previous harness results;
   - current harness plans;
   - validation results;
   - stage results;
   - global loop state.
2. Add `scripts/loop_engineering_validate.py`, reusing the existing dependency-free schema validator.
3. Add `tests/loop_engineering/test_loop_state_contract.py` with positive and negative validation coverage.
4. Add `tests/ci/test_loop_engineering_pack.py` to protect the L00 validation pack and workflow coverage.
5. Strengthen `.github/workflows/github-coverage-gates.yml` so CI runs the loop validator and loop tests without adding P14 or real Valkey gates to default CI.

## Validator Behavior

The validator must:

- validate optional `global_loop_state.json` when present;
- validate each stage directory's `stage_state.json`, `previous_harness_result.json`, `current_harness_plan.json`, `validation_result.json`, `stage_result.json`, `commands.jsonl`, and `subagents/*.json` when present;
- enforce filename/stage/role consistency for subagent outputs;
- reject empty or malformed command JSONL;
- reject `PASS` command entries with non-zero exit code;
- reject `FAIL` command entries with zero exit code;
- allow in-progress stages to omit completion-only artifacts;
- reject completed `PASS` stage results unless previous/current harness passed, all required subagent verdicts are `APPROVED`, `commands_log` exists, and referenced artifacts exist;
- provide a runnable `--anti-regression --base-ref <sha> --head-ref <sha>` mode that inspects protected diffs and fails on clear harness weakening patterns.

## Anti-Regression Scope

The L00 anti-regression entrypoint is read-only. It checks diffs in protected paths for obvious weakening patterns:

- `real_valkey_required` changed to `false`;
- required gates or artifacts changed to optional;
- P14 changed to automatic;
- `VSLAB_ALLOW_1000_DRYRUN` removed from protected diffs;
- test skip/xfail additions without an explicit reason;
- hand-written gate `PASS` artifacts under `artifacts/gates`;
- `.DS_Store` staged or tracked under controlled paths.

## Expected Initial Failures

Before implementation, these commands are expected to fail because the L00 harness files do not exist:

- `python3 scripts/loop_engineering_validate.py --root artifacts/loop_engineering`
- `python3 -m pytest -q tests/loop_engineering tests/ci/test_loop_engineering_pack.py`

These failures are harness gaps, not accepted completion state.

## Acceptance Criteria

- Previous harness remains PASS.
- L00 validator and tests pass.
- `python3 scripts/loop_engineering_validate.py --root artifacts/loop_engineering` passes for the completed L00 artifact tree.
- Anti-regression check is runnable and produces an L00 report.
- Seven subagent JSON outputs exist and validate.
- L00 `stage_result.json` records `PASS`, commit metadata after push, subagent verdicts, command log, artifacts, and remaining risks.
- No existing P00-P14 harness requirement, real Valkey requirement, or P14 opt-in boundary is weakened.
