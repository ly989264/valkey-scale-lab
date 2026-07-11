# FIX_LOG — P15_GOAL_REBASE_HARNESS_EXTENSION

## Main-agent fix after worker handoff

- Issue: `WORKER_SUMMARY.md` identified that the future P21 200-node stage still used `templates/configs/scale_100.yaml` as the manifest command config while requiring `--min-nodes 200`.
- Risk: the command would fail closed, but it could confuse future P21 implementation by pointing the 200-node stage at a 100-node template.
- Fix: changed the P21 real failover gate command to reference `templates/configs/scale_200.yaml`, added `assert_goal_loop_stage.py` validation that P21 real gates cannot reference `scale_100.yaml` and must include `--min-nodes 200`, and added unit coverage in `tests/unit/test_goal_loop_assertions.py`.
- Re-run evidence: P15 `precheck`, `precheck --all`, `safety_scan`, compileall with repo-local pycache, focused goal-loop tests, full `tests/unit tests/integration`, `assert_goal_loop_stage.py`, and `codex_gate.py run --phase P15_GOAL_REBASE_HARNESS_EXTENSION` all passed after the fix.
- Non-goal preserved: no P21 runtime behavior or fake 200-node evidence was implemented in P15; `scale_200.yaml` remains a future-stage required config target.
