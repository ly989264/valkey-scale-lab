# M1-S07 Context Reload

stage_id: M1-S07
stage_status: IN_PROGRESS
git_sha_before: 2b2d2ba5e13495383f4228a91cc46191338b8916
git_sha_after: MISSING_WITH_REASON: stage is starting
commit_sha: MISSING_WITH_REASON: stage is starting
pushed_branch: codex/valkey-scale-lab-loop

## Documents Reloaded

- `AGENTS.md`: preserve local-first Valkey harness, no host network mutation, no fake real PASS, deterministic cleanup, structured missing/skipped values, and strong gates before commit/push.
- `codex_goal_loop_m1/AGENTS_MILESTONE1.md`: every stage must run main/design/worker/review, maintain coverage across execution shape, scale, functional path, data path, and outcome class, and propagate new fields through schema -> writer -> fixture -> reader -> aggregator -> renderer -> gate -> docs.
- `codex_goal_loop_m1/docs/00_INDEX.md`: read all milestone1 core docs and current stage file.
- `codex_goal_loop_m1/docs/01_GOAL_CONTRACT.md`: milestone1 requires local real Valkey through 200 nodes, metrics collection, analysis, and offline Chinese report generation without LLM dependency.
- `codex_goal_loop_m1/docs/02_STAGE_MANIFEST.md`: current stage is `M1-S07`, after pushed `M1-S06`; no long soak stage exists.
- `codex_goal_loop_m1/docs/03_GLOBAL_COVERAGE_MATRIX.md`: coverage matrix must span fake/unit/integration/smoke/real/dry-run/blocked/cleanup/failure and small/30/50/100/200/200+ planning.
- `codex_goal_loop_m1/docs/04_STRONG_HARNESS_LOOP_ENGINE.md`: run compileall and unit/integration gates, add a stage-specific system metrics assertion, and record blocked real paths with reason.
- `codex_goal_loop_m1/docs/05_MULTI_AGENT_STAGE_PROTOCOL.md`: use design subagent, worker subagent, gates, review subagent, then commit/push.
- `codex_goal_loop_m1/docs/06_CONTEXT_TRANSFER_PROTOCOL.md`: write structured context, design, worker, review, completion, coverage, and handoff artifacts.
- `codex_goal_loop_m1/docs/07_ARTIFACT_PLACEMENT_POLICY.md`: new run artifacts belong under `runs/<run_id>/artifacts`, with legacy paths only as compatibility.
- `codex_goal_loop_m1/docs/08_SCHEMA_ARTIFACT_CONTRACT.md`: system metrics must become schema-validated non-empty samples and flow through analysis/report/gate.
- `codex_goal_loop_m1/docs/09_NO_PARTIAL_IMPLEMENTATION_RULES.md`: no metric may be fake-only, report-only, scale-only, or script-only.
- `codex_goal_loop_m1/docs/10_GIT_COMMIT_PUSH_PROTOCOL.md`: review PASS before commit, push before moving to M1-S08.
- `codex_goal_loop_m1/docs/11_MILESTONE1_ACCEPTANCE.md`: system metrics are a final acceptance category and must be real/fixture/blocked-cleanly covered.
- `codex_goal_loop_m1/docs/12_REPORT_ZH_OFFLINE_CONTRACT.md`: Chinese report must show system resource trends and abnormal node lists from local artifacts.
- `codex_goal_loop_m1/docs/13_RISK_REGISTER.md`: prevent fake real, empty metrics JSONL, report-only fields, and context loss.
- `codex_goal_loop_m1/docs/14_STAGE_ENTRY_CHECKLIST.md`: entry checklist completed through context reload and coverage draft.
- `codex_goal_loop_m1/docs/15_STAGE_EXIT_CHECKLIST.md`: exit requires schema/writer/reader/analyzer/renderer/fixture/gate/review/commit/push.
- `codex_goal_loop_m1/stages/M1_S07_SYSTEM_METRICS.md`: add process, network, and Valkey-side system metrics; collect during setup, management ops, workload, fault, cleanup; aggregate per-node/per-stage/per-window; render Chinese resource trends and abnormal node TopN.
- Previous M1-S06 handoff/review/completion/context: fault timeline stage is committed and pushed, real 30-node Valkey failover evidence passed, 50/100/200 remain structured blocked; M1-S07 should link fault-period system metrics to `fault_id`, `sample_id`, and `timeline_ref` when applicable.

## Stage Scope

M1-S07 must build a system metrics layer with schema-validated samples, non-empty metrics JSONL, fake fixtures, smoke/real/blocked paths, analysis aggregation, and offline Chinese report sections. The implementation must not only add report text; it must add artifact writers and gates.

## Initial Risk Notes

- System metrics may be platform-dependent. Unsupported fields such as TCP retransmits or cluster bus connections must be structured `SKIPPED_WITH_REASON` or `MISSING` with reason, not null.
- Full pytest has legacy CI/provenance failures unrelated to M1-S06; M1-S07 gates must still include focused unit/integration and stage-specific checks.
- Real 50/100/200 system metrics may require resource budget. Any blocked larger real runs must be explicit and must not reuse 30-node evidence as PASS.
