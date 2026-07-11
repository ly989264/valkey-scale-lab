# M1-S08 Context Reload

stage_id: M1-S08
stage_status: IN_PROGRESS
git_sha_before: c2e36a411717e375e1d9c52c80ac042d1c614b81
git_sha_after: MISSING_WITH_REASON: stage is starting
commit_sha: MISSING_WITH_REASON: stage is starting
pushed_branch: codex/valkey-scale-lab-loop

## Documents Reloaded

- `AGENTS.md`: preserve strict harness, real Valkey evidence, no fake PASS, no host network mutation, machine-readable artifacts first, and no stage completion before gates/review/commit/push.
- `codex_goal_loop_m1/AGENTS_MILESTONE1.md`: every stage must use design/worker/review roles, maintain multi-dimensional coverage, and propagate new behavior through schema -> writer -> fixture -> reader -> aggregator -> renderer -> gate -> docs.
- `codex_goal_loop_m1/docs/00_INDEX.md`: M1 core docs and current stage file are controlling for milestone1.
- `codex_goal_loop_m1/docs/01_GOAL_CONTRACT.md`: milestone1 requires local real Valkey through 200 nodes, analysis, metrics, and Chinese offline automated reporting without LLM dependency.
- `codex_goal_loop_m1/docs/02_STAGE_MANIFEST.md`: current stage is `M1-S08`, following pushed `M1-S07`, before final acceptance `M1-S09`.
- `codex_goal_loop_m1/docs/03_GLOBAL_COVERAGE_MATRIX.md`: coverage must include execution shape, scale rung, functional path, data path, and outcome class.
- `codex_goal_loop_m1/docs/04_STRONG_HARNESS_LOOP_ENGINE.md`: run compile/unit/integration/smoke/stage gates and record real blocked paths with reasons.
- `codex_goal_loop_m1/docs/05_MULTI_AGENT_STAGE_PROTOCOL.md`: design, worker, review artifacts are required; explicit subagents are preferred, simulated roles are acceptable when unavailable.
- `codex_goal_loop_m1/docs/06_CONTEXT_TRANSFER_PROTOCOL.md`: write context reload, design brief, worker summary, review, completion, coverage matrix, and handoff.
- `codex_goal_loop_m1/docs/07_ARTIFACT_PLACEMENT_POLICY.md`: run artifacts live under `runs/<run_id>/artifacts`; report outputs should remain separated from source.
- `codex_goal_loop_m1/docs/08_SCHEMA_ARTIFACT_CONTRACT.md`: report index and generated artifacts must be schema/contract validated; missing data stays explicit.
- `codex_goal_loop_m1/docs/09_NO_PARTIAL_IMPLEMENTATION_RULES.md`: no report-only or single-fixture patch; all report fields must read artifacts.
- `codex_goal_loop_m1/docs/10_GIT_COMMIT_PUSH_PROTOCOL.md`: review PASS before commit and push before moving to M1-S09.
- `codex_goal_loop_m1/docs/11_MILESTONE1_ACCEPTANCE.md`: final acceptance depends on offline Chinese report coverage.
- `codex_goal_loop_m1/docs/12_REPORT_ZH_OFFLINE_CONTRACT.md`: report must output `reports/index.html`, `reports/report.md`, `reports/exports/*.csv`, `reports/assets/*.svg`, `reports/report_index.json`; all titles/tables/explanations/conclusions in Chinese; no LLM, CDN, external API, or online charts.
- `codex_goal_loop_m1/docs/13_RISK_REGISTER.md`: prevent fake real, external URL dependencies, empty charts, and report fields not backed by artifacts.
- `codex_goal_loop_m1/docs/14_STAGE_ENTRY_CHECKLIST.md`: entry context reload complete.
- `codex_goal_loop_m1/docs/15_STAGE_EXIT_CHECKLIST.md`: exit requires schema/writer/reader/analyzer/renderer/fixture/gate/review/commit/push/handoff.
- `codex_goal_loop_m1/stages/M1_S08_ZH_OFFLINE_VISUAL_REPORT.md`: implement Chinese automatic visual report, local SVG/HTML static assets, artifact-only inputs, same renderer for 30/50/100/200, missing metrics aggregation, bottleneck summary.
- Previous `M1-S07` context/completion/review/handoff: system metrics artifacts and Chinese system resource sections are available and should be consumed by M1-S08 rather than re-derived.

## Stage Scope

M1-S08 should upgrade report output shape and quality: `reports/index.html`, `reports/report.md`, `reports/exports/*.csv`, `reports/assets/*.svg`, and `reports/report_index.json`; enforce offline/no external URL/no LLM dependency; add a report quality gate; ensure the report answers main bottlenecks from artifact-backed analysis.

## Initial Risks

- Current renderer writes flat report files directly in a report directory, not the required `exports/` and `assets/` layout.
- Some headings are already Chinese but the document title and several labels remain English; M1-S08 must tighten Chinese coverage without hiding machine-readable field names.
- Report index must reference the new layout and verify non-empty local assets.
