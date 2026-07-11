# M1-S06 Context Reload

stage_id: M1-S06
stage_status: IN_PROGRESS
git_sha_before: 0705a95fe4de30237b6a27a9dbe89f15be281d8e
git_sha_after: MISSING_WITH_REASON: stage is still in progress
commit_sha: MISSING_WITH_REASON: stage is still in progress
pushed_branch: codex/valkey-scale-lab-loop

## Documents Reloaded

- `AGENTS.md`: preserve safety rules, local Docker/container fault injection only, no host network mutation, no fake real PASS, and structured missing/skipped values.
- `codex_goal_loop_m1/AGENTS_MILESTONE1.md`: every stage uses design, worker, and review roles; coverage must span execution shape, scale rung, functional path, data path, and outcome class; fields must propagate through schema, writer, fixture, reader, aggregator, renderer, gate, and docs.
- `codex_goal_loop_m1/docs/00_INDEX.md` through `15_STAGE_EXIT_CHECKLIST.md`: M1 stages require no partial implementation, run artifact/source separation, Chinese offline reports, review PASS before commit/push, and no long soak stage.
- `codex_goal_loop_m1/stages/M1_S06_FAULT_FAILOVER_TIMELINE.md`: fault validation must become full timeline evidence with planned/apply/effect/impact/failover/promotion/recovery/workload/clear/cleanup events, latency metrics, workload impact, failover samples, analysis aggregation, Chinese report visibility, fixtures, and gates.
- Previous stage files `runs/m1-s05-local/artifacts/goal_loop/M1-S05/{CONTEXT_RELOAD.md,COMPLETION.md,REVIEW.md,HANDOFF.md}`: M1-S05 benchmark workload is committed and pushed; M1-S06 must use benchmark workload windows for fault/failover workload-impact refs and continue to encode real-gate blocks with evidence.

## Stage Scope

M1-S06 upgrades fault/failover evidence from row-level PASS/FAIL into schema-validated timelines for every required fault type. The stage must add timeline artifacts, derived failover/unavailability/split-brain metrics, workload impact linkage, analysis aggregation, Chinese report outputs, fixtures, and gates.

## Initial Risk Notes

- Existing fault/failover paths are spread across runtime and gate scripts; design must avoid a single fixture-only timeline.
- Network delay/loss/partition must remain scoped to Docker/container namespaces or sandbox proxy layers; no host network mutation.
- Real local fault gates may remain blocked by sandbox port binding. Any blocked path must remain `BLOCKED_WITH_REASON`; no fake timeline PASS rows.
