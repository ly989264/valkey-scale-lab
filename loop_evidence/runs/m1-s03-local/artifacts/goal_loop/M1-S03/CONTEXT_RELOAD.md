# M1-S03 Context Reload

stage_id: M1-S03
stage_status: IN_PROGRESS
git_sha_before: 8aab10f51e6a0d605f2cb44a1767c884d65be38b
git_sha_after: MISSING_WITH_REASON: stage is still in progress
commit_sha: MISSING_WITH_REASON: stage is still in progress
pushed_branch: codex/valkey-scale-lab-loop

## Documents Reloaded

- `AGENTS.md`: preserve safety rules, no fake real PASS, no host network mutation, structured missing/skipped values, real wrapper evidence for real claims.
- `codex_goal_loop_m1/AGENTS_MILESTONE1.md`: every stage must use design/worker/review subagents and full coverage matrix propagation.
- `codex_goal_loop_m1/docs/00_INDEX.md` through `15_STAGE_EXIT_CHECKLIST.md`: M1 stages require schema/writer/reader/analyzer/renderer/fixture/gate propagation, run artifact separation, Chinese offline report output, review PASS before commit/push, and no long soak stage.
- `codex_goal_loop_m1/stages/M1_S03_COMMAND_AUDIT_LOG.md`: add a universal nonempty command audit log covering cluster, management, fault, cleanup, and probe commands with required timing/status/retry/timeout/error fields.
- Previous handoff `runs/m1-s02-local/artifacts/goal_loop/M1-S02/{CONTEXT_RELOAD.md,COMPLETION.md,REVIEW.md}`: M1-S03 must reuse run-scoped artifacts, preserve setup telemetry paths, and propagate command audit fields through schema, writer, fixtures, reader, aggregator, Chinese report renderer, gates, coverage matrix, and blocked/timeout paths.

## Stage Scope

M1-S03 introduces command-level auditability. Every PASS management/fault/cleanup/probe operation must be traceable to command rows, and command logs must not be empty or accepted by gates when required fields are missing.

## Initial Risk Notes

- Existing runtime helpers call Docker and `valkey-cli` in many locations; design must find a shared recorder path rather than patching isolated command sites.
- Real local Docker/Valkey gate may remain blocked by sandbox port-bind denial; blocked evidence must not fabricate command rows.
- Command stdout/stderr handling must use paths or hashes and avoid storing huge raw output directly in summary artifacts.
- The docs index lists stage files under `codex_goal_loop_m1/docs/stages`, but the repository stores them under `codex_goal_loop_m1/stages`; M1-S03 loaded the actual existing stage file and records this path mismatch.
