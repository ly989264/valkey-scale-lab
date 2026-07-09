# H10 Context Reload

stage_id: H10_FINAL_HARDENING_ACCEPTANCE
source_commit_before: e9fc1d44b3d1e16b573e69d4bd74bc62fb0a1a8b

## Documents Reloaded

- `AGENTS.md`: repository safety rules remain active; machine-readable artifacts are the product, stage completion requires real gates, review, commit, and push, and fake/fixture-only evidence cannot be presented as real Valkey proof.
- `CODEX_START_HERE.md` and `CODEX_GOAL_LOOP_START.md`: preserve package and CLI contracts; use the staged loop with document reload, design, worker, gates, review, postcheck/marking when applicable, commit, and push.
- `codex_goal_loop_m1_hardening_v2/START_HERE.md`: do not satisfy the hardening loop with Markdown notes; executable fail-closed gates are required.
- `codex_goal_loop_m1_hardening_v2/AGENTS_M1H_V2.md`: every stage requires real design, worker, and review subagents; simulated subagent artifacts are forbidden; stage completion needs required gates, artifact JSON, review PASS, commit, and push.
- `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md`: reloaded the indexed core docs, contracts C00-C12, and the H10 stage file.
- Core docs `01` through `19`: H10 must prove the earlier false PASS is impossible, keep fixtures/legacy/skipped/fake/rendered-only evidence from milestone PASS, preserve honest `BLOCKED_WITH_REASON`, and produce final handoff artifacts.
- Contracts `C00` through `C12`: required claim IDs, evidence manifest shape, exact-scale semantics, static forbidden patterns, setup, command audit, workload, fault, system, report input quality, and real subagent requirements remain binding.
- `stages/H10_FINAL_HARDENING_ACCEPTANCE.md`: final acceptance must run `assert_final_milestone1_hardened.py`, common gates, stage exit, and real review; milestone1 PASS is allowed only if every exact-scale claim passes.
- Previous H09 handoff: report input-quality now fails closed; H10 should not rerun milestone1 from scratch or invent evidence, and current blocked claims are acceptable only with concrete reasons.

## Current Repository State

- Current branch: `codex/valkey-scale-lab-loop`.
- H09 commit pushed: `e9fc1d44 H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING`.
- `runs/m1-hardening/evidence_manifest.json` currently contains 29 required claims; exact-scale report claims are blocked by H09 source-quality checks and several upstream claims remain blocked.
- Existing final gate script `scripts/m1h/assert_final_milestone1_hardened.py` writes a C03-shaped acceptance report, but before H10 it defaults to `milestone1_acceptance_report.json` and H02-oriented artifact typing.
- Existing `scripts/m1h/assert_stage_exit.py` does not yet list H10 as a required stage or require the final hardened acceptance artifact.

## H10 Implementation Focus

- Add H10-specific final acceptance output at `runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/artifacts/milestone1_hardened_acceptance.json`.
- Ensure final hardening can PASS while milestone1 is honestly `BLOCKED_WITH_REASON`.
- Fail closed if milestone1 PASS has any blocked/failed required claim, fixture-only source, legacy-only source, skipped core real metric, fake/PARTIAL timeline, rendered-only report backing, or incomplete M1 semantics.
- Add tests proving H10 stage exit requires the final gate and final acceptance artifact.
- Run executable gates and preserve final handoff artifacts; no Markdown-only completion.
