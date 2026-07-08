# M1-S05 Context Reload

stage_id: M1-S05
stage_status: IN_PROGRESS
git_sha_before: e4427dc7a180651b778a965409152dc7abbc54ac
git_sha_after: MISSING_WITH_REASON: stage is still in progress
commit_sha: MISSING_WITH_REASON: stage is still in progress
pushed_branch: codex/valkey-scale-lab-loop

## Documents Reloaded

- `AGENTS.md`: preserve local-first Valkey harness safety; do not fake real evidence; no host network mutation; missing metrics must be structured.
- `codex_goal_loop_m1/AGENTS_MILESTONE1.md`: each stage must use design, worker, and review roles; coverage must span execution shape, scale rung, functional path, data path, and outcome class; fields must propagate through schema, writer, fixture, reader, aggregator, renderer, gate, and docs.
- `codex_goal_loop_m1/docs/00_INDEX.md` through `15_STAGE_EXIT_CHECKLIST.md`: M1 stages require no partial implementation, run artifact/source separation, Chinese offline reports, review PASS before commit/push, and no long soak stage.
- `codex_goal_loop_m1/stages/M1_S05_WORKLOAD_BENCHMARK.md`: keep smoke workload and add benchmark workload profiles; implement full-slot key generation; collect benchmark windows and latency/error/QPS fields; attach workload impact to management/fault/failover; update schema, fixtures, analysis, Chinese report, and gates.
- Previous stage files `runs/m1-s04-local/artifacts/goal_loop/M1-S04/{CONTEXT_RELOAD.md,COMPLETION.md,REVIEW.md,HANDOFF.md}`: M1-S04 management matrix is committed and pushed; workload benchmark additions must preserve management workload impact refs and must not claim fake real PASS while local port binding remains blocked.

## Stage Scope

M1-S05 upgrades workload from smoke-only data-path checks into benchmark profiles suitable for performance analysis. The stage must introduce profile/config semantics, full-slot key generation, canonical benchmark windows, QPS/latency/error metrics, workload impact aggregation, and Chinese report views.

## Initial Risk Notes

- Existing workload code may use fixed hash tags; M1-S05 must prove uniform benchmark keys cover multiple hash slots.
- Metrics must be written at runtime and not only in fixtures.
- Management/fault/failover paths already reference workload impact artifacts, so new benchmark rows must remain referenceable from those paths.
- Real local gates may remain blocked by sandbox port binding. If so, encode `BLOCKED_WITH_REASON` with evidence rather than a fake PASS.
