# H09 Context Reload

stage_id: H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING
source_commit_before: 1248c98c4eb68deeb446e06ef06586b92aadcbca

## Documents Reloaded

- `codex_goal_loop_m1_hardening_v2/START_HERE.md`: hardening stages require executable fail-closed gates, not Markdown-only completion notes.
- `codex_goal_loop_m1_hardening_v2/AGENTS_M1H_V2.md`: H09 must use real design, worker, and review subagents and may complete only after gates, artifacts, review PASS, commit, and push.
- `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md`: confirms H09 order and the required docs/contracts. The index lists `docs/contracts` and `docs/stages`, while this package stores them at top-level `contracts/` and `stages/`.
- `docs/02_NON_NEGOTIABLE_CONTRACT.md`: report generation cannot substitute for exact-scale evidence quality, and blocked source evidence must remain `BLOCKED_WITH_REASON`.
- `docs/03_EVIDENCE_TAXONOMY.md`: report claims can promote only with hardening-accepted real exact-scale evidence or explicitly valid reconstruction; fixture, legacy, dry-run, and smoke evidence cannot satisfy milestone claims.
- `docs/04_HARD_GATE_ARCHITECTURE.md`: H09 must use `scripts/m1h/assert_report_input_quality.py` and write gate JSON under the H09 gate artifact directory.
- `docs/09_NO_SHORTCUT_RULES.md`: no fixture fallback, legacy promotion, non-empty file check, or skipped-as-pass shortcut may support report input quality.
- `docs/10_ACCEPTANCE_MATRIX.md`: Chinese offline report claims are required for every accepted exact-scale run, but report output alone cannot promote milestone PASS.
- `docs/12_REPORT_QUALITY_CONTRACT.md`: the report is a view, not proof; the input gate must fail or block if source inputs are weak while report status claims PASS.
- `docs/13_BLOCKED_STATUS_POLICY.md`: blocked exact-scale source claims must remain explicit and cannot be converted to PASS because a report rendered.
- `docs/15_REVIEW_RUBRIC.md`: review must inspect gates, manifest, source-quality checks, fake/PARTIAL protections, and subagent artifacts.
- `docs/17_COMMANDS_AND_GATES.md`: common gates plus H09 `assert_report_input_quality.py` are required.
- `docs/18_STAGE_EXIT_CONTRACT.md`: `assert_stage_exit.py` must verify H09 gate results, review PASS, shortcut scan, and completion handoff.
- `stages/H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING.md`: H09 must distinguish render PASS from source-quality PASS and must block milestone when report inputs are weak.

## Contracts Reloaded

- `C11_REPORT_INPUT_QUALITY_CONTRACT.md`: exact-scale report PASS must cite accepted exact-scale M1 claims; no fixture-only source may back milestone report PASS; report index must include offline policy; report output must include setup, command audit, management, workload, fault, system metrics, cleanup, and missing metric sections; every chart/table needs source references; blocked source claims may still render but milestone status remains blocked.
- `C12_NO_SIMULATED_SUBAGENT_CONTRACT.md`: H09 agent and handoff artifacts must be produced by real subagents and avoid forbidden shortcut phrases.

## Previous Stage Reload

- H08 completion: system metrics exact-scale claims now fail closed and require real C10 resource bundles with strict lifecycle windows, exact node cardinality, high-value metric coverage, report/timeseries cross-checks, and Valkey 9.1.x evidence.
- H08 review: fresh real review returned `Decision: PASS` after earlier false-PASS issues in report semantic checks and exact node coverage were fixed.
- H08 gate artifact: `assert_system_metrics_real_windows.json` is PASS as a hardening gate, with zero passed system-metrics claims, four blocked claims, and rejected generic metrics rows.
- H08 next-stage input: H09 must not let report rendering turn blocked or weak source evidence into milestone PASS.

## Current Repository State

- Current branch is `codex/valkey-scale-lab-loop` at `1248c98c4eb68deeb446e06ef06586b92aadcbca`.
- `scripts/m1h/assert_report_input_quality.py` is currently only the generic capability wrapper.
- `scripts/m1h/manifest.py` currently marks report claims with weak checks: `report_index_present` and `accepted_inputs_only: False`.
- Current report claims are all `BLOCKED_WITH_REASON`: scale 30 has no report sources, and scales 50/100/200 cite P36 report indexes but remain `INVALID` because no H09 accepted-input semantics exist.
- Existing report renderers include offline policy and report input sections, but H09 must ensure source-quality semantics are tied to accepted M1H claim status rather than successful rendering alone.

## H09 Starting Risk

The unacceptable state is a report claim promoting because `report_index.json`, HTML, or Markdown exists, because the report rendered from fixture/legacy/blocked inputs, or because a report index says PASS while source claims remain blocked. H09 must make those paths impossible through manifest semantics, a dedicated gate, tests, real subagent artifacts, and `assert_stage_exit`.
