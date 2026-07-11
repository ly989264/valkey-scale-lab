# M1-S04 Context Reload

stage_id: M1-S04
stage_status: IN_PROGRESS
git_sha_before: bf111fe6b916ee21d92df1a44c310c54f8bf3fd1
git_sha_after: MISSING_WITH_REASON: stage is still in progress
commit_sha: MISSING_WITH_REASON: stage is still in progress
pushed_branch: codex/valkey-scale-lab-loop

## Documents Reloaded

- `AGENTS.md`: preserve safety rules, real Valkey claims require real wrapper evidence, no fake PASS, no host network mutation, structured missing/skipped values.
- `codex_goal_loop_m1/AGENTS_MILESTONE1.md`: every stage uses design/worker/review subagents; coverage is multidimensional and must include schema/writer/reader/analyzer/renderer/fixture/gate propagation.
- `codex_goal_loop_m1/docs/00_INDEX.md` through `15_STAGE_EXIT_CHECKLIST.md`: M1 stages require run artifact separation, Chinese offline reports, no partial implementation, review PASS before commit/push, and no long soak stage.
- `codex_goal_loop_m1/stages/M1_S04_MANAGEMENT_MATRIX_ENHANCEMENT.md`: management matrix must become an explainable operation process with topology snapshots/diffs, command-log aggregation, workload impact refs, cleanup refs, reshard/rebalance details, rolling restart timings, analysis aggregation, report sections, fixtures, and gates.
- Previous handoff `runs/m1-s03-local/artifacts/goal_loop/M1-S03/{CONTEXT_RELOAD.md,COMPLETION.md,REVIEW.md}`: M1-S04 must build management operation rows on top of the command audit path; every PASS management operation needs command refs traceable to `command_log.jsonl`.

## Stage Scope

M1-S04 upgrades management operation evidence from a simple result matrix to schema-validated operation artifacts with before/after topology snapshots, topology/slot/role diffs, command/retry/error counts, convergence timing, workload impact refs, cleanup refs, and Chinese report visibility.

## Initial Risk Notes

- Management operations already exist in later strict P30/P31/P32 code paths; design must avoid a one-off M1-S04-only matrix and should converge on common artifact semantics reusable by 30/50/100/200 scales.
- Real local Valkey gates may remain blocked by sandbox port binding. Any blocked path must remain `BLOCKED_WITH_REASON`; no fake management PASS rows.
- Reshard/rebalance and rolling restart fields are operation-specific and must be represented even when values are `MISSING` or `SKIPPED_WITH_REASON` with reasons.
