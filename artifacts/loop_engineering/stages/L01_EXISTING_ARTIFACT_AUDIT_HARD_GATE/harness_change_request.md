# Harness Change Request: Phase-Aware Loop Validation

## Defect

During L01 previous-harness baseline, `python3 scripts/loop_engineering_validate.py --root artifacts/loop_engineering` failed because the active L01 stage had not yet produced `previous_harness_result.json` or `current_harness_plan.json`.

That failure conflicts with `codex/loop_engineering/01_STAGE_LOOP_PROTOCOL.md`: `current_harness_plan.json` is written in Phase C after previous harness passes, while root validation is now part of the previous harness baseline through the L00 workflow addition.

## Impact

The validator correctly validates completed stages, but it is too strict for the currently active in-progress stage. Without a fix, every stage after L00 blocks before it can reach the design phase.

## Patch Plan

Make `scripts/loop_engineering_validate.py` phase-aware:

- Always require and validate `stage_state.json` and `commands.jsonl`.
- Require `previous_harness_result.json` only after the stage leaves `PREVIOUS_HARNESS`.
- Require `current_harness_plan.json` only after the stage reaches `DESIGN` or later.
- Preserve strict PASS validation for completed `stage_result.json`.
- Add loop-engineering tests covering an in-progress PREVIOUS_HARNESS stage without design artifacts.

## Why This Is Not A Bypass

This change does not weaken completed-stage validation. It preserves the stage ordering contract by allowing the active stage to be validated before artifacts that are not yet supposed to exist. Completed PASS stages still require previous harness, current harness, seven subagents, stage result, command log, and artifact references.
