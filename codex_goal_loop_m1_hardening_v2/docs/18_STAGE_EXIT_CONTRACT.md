# 18_STAGE_EXIT_CONTRACT.md

Stage exit contract is machine-checked by `scripts/m1h/assert_stage_exit.py`.

It must verify:

- all required gate result JSON files exist;
- all gate result JSON files conform to `m1h_gate_result` shape;
- all non-allowed blocked gates are not blocked;
- no gate result has `status: FAIL`;
- no subagent artifact contains forbidden simulated-subagent text;
- `COMPLETION.md` references gate artifact paths;
- evidence manifest was updated if the stage changes evidence claims;
- commit and push status are recorded in handoff.

No text-only stage completion is allowed.
