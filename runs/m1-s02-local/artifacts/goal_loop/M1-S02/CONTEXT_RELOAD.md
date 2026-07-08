# M1-S02 Context Reload

stage_id: M1-S02
stage_status: IN_PROGRESS
git_sha_before: 574271eaf8254d1f7e9180dfbd8c7b1ca9facd32
git_sha_after: MISSING_WITH_REASON: stage is still in progress
commit_sha: MISSING_WITH_REASON: stage is still in progress
pushed_branch: codex/valkey-scale-lab-loop

## Documents Reloaded

- `AGENTS.md`: preserved safety rules, no fake real PASS, no host network mutation, structured missing/skipped values.
- `CODEX_START_HERE.md`: preserve CLI contract and strong stage gates.
- `codex_goal_loop_m1/AGENTS_MILESTONE1.md`: every stage must use design/worker/review subagents and coverage matrix.
- `codex_goal_loop_m1/docs/00_INDEX.md` through `15_STAGE_EXIT_CHECKLIST.md`: M1 stages require schema/writer/reader/analyzer/renderer/fixture/gate propagation and run artifact separation.
- `codex_goal_loop_m1/stages/M1_S02_CLUSTER_SETUP_TELEMETRY.md`: add setup telemetry fields, per-node/per-nodehost metrics, analysis TopN, report inputs, cleanup timing, and a setup telemetry gate.
- Previous handoff `runs/m1-s01-local/artifacts/goal_loop/M1-S01/{CONTEXT_RELOAD.md,COMPLETION.md,REVIEW.md}`: M1-S02 must build on `RunContext`, `run_metadata`, and `run_manifest`; real Valkey smoke was blocked by sandbox port bind denial and must not be faked.

## Stage Scope

M1-S02 upgrades local cluster setup evidence from “started” to “where time went”: phase duration metrics, per-node readiness, per-nodehost process metrics, slowest node/replica TopN, cleanup timing, and report-ready inputs.

## Initial Risk Notes

- Existing `SetupTimeline` is P13-oriented; M1-S02 must generalize without breaking P13/P13O gates.
- Real Docker/Valkey local gate may remain blocked by port-bind sandboxing; blocked evidence must remain explicit.
- New fields must not live only in one scale rung or one script.
