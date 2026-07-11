# M1-S09 Context Reload

stage_id: M1-S09
stage_status: IN_PROGRESS
git_sha_before: b86d11b6ff5b764de96e49f0f15ee008270b2102
git_sha_after: MISSING_WITH_REASON: stage is starting
commit_sha: MISSING_WITH_REASON: stage is starting
pushed_branch: codex/valkey-scale-lab-loop

## Documents Reloaded

- `AGENTS.md`: strict harness, real Valkey proof, no fake PASS, no host network mutation, deterministic cleanup, and review/gates before commit/push.
- `codex_goal_loop_m1/AGENTS_MILESTONE1.md`: every stage needs design/worker/review artifacts, multi-dimensional coverage, and complete propagation across schema/writer/fixture/reader/analyzer/renderer/gate/docs.
- `codex_goal_loop_m1/docs/00_INDEX.md`: all milestone1 docs and current stage file are controlling.
- `codex_goal_loop_m1/docs/01_GOAL_CONTRACT.md`: milestone1 goal is local real Valkey through bounded 200 nodes, management/fault/workload/system metrics/analysis/offline Chinese report.
- `codex_goal_loop_m1/docs/02_STAGE_MANIFEST.md`: current final stage is M1-S09 after pushed M1-S08.
- `codex_goal_loop_m1/docs/03_GLOBAL_COVERAGE_MATRIX.md`: acceptance must cover execution shape, scale rung, functional path, data path, and result class.
- `codex_goal_loop_m1/docs/04_STRONG_HARNESS_LOOP_ENGINE.md`: final gate must fail closed and distinguish PASS from BLOCKED_WITH_REASON.
- `codex_goal_loop_m1/docs/05_MULTI_AGENT_STAGE_PROTOCOL.md`: design/worker/review artifacts required.
- `codex_goal_loop_m1/docs/06_CONTEXT_TRANSFER_PROTOCOL.md`: context reload, design brief, worker summary, review, completion, coverage, and handoff required.
- `codex_goal_loop_m1/docs/07_ARTIFACT_PLACEMENT_POLICY.md`: acceptance artifacts belong in `runs/<run_id>/artifacts`.
- `codex_goal_loop_m1/docs/08_SCHEMA_ARTIFACT_CONTRACT.md`: final result must be structured and reasoned missing/blocked values must not be null or invented.
- `codex_goal_loop_m1/docs/09_NO_PARTIAL_IMPLEMENTATION_RULES.md`: final gate must catch fields that stop in one path only.
- `codex_goal_loop_m1/docs/10_GIT_COMMIT_PUSH_PROTOCOL.md`: review PASS before commit; push before declaring milestone complete.
- `codex_goal_loop_m1/docs/11_MILESTONE1_ACCEPTANCE.md`: final gate checks cluster setup, management, fault/failover, workload, system metrics, analysis, Chinese report, cleanup, missing reasons, and cross-scenario coverage.
- `codex_goal_loop_m1/docs/12_REPORT_ZH_OFFLINE_CONTRACT.md`: Chinese report must be offline and local artifact-derived.
- `codex_goal_loop_m1/docs/13_RISK_REGISTER.md`: prevent fake real, empty metrics/timeline, external report dependencies, and unreasoned missing data.
- `codex_goal_loop_m1/docs/14_STAGE_ENTRY_CHECKLIST.md`: entry reload completed.
- `codex_goal_loop_m1/docs/15_STAGE_EXIT_CHECKLIST.md`: exit requires gate artifacts, review, commit, push.
- `codex_goal_loop_m1/stages/M1_S09_MILESTONE1_ACCEPTANCE_GATE.md`: add final acceptance gate producing `milestone1_status` plus category statuses and checking artifacts, coverage, command logs, metrics/timelines, Chinese offline report, missing reasons, and blocked heavy real rungs.
- Previous M1-S08 completion/review/handoff: report gate and canonical offline report layout are present and should be accepted as visual-report evidence.

## Stage Scope

M1-S09 must add a final structured milestone1 acceptance gate and run it over existing M1 artifacts. It must distinguish completed small/fixture/smoke/real-local evidence from exact 30/50/100/200 heavy rungs that are still `BLOCKED_WITH_REASON`; it must not mark blocked heavy real rungs as PASS.
