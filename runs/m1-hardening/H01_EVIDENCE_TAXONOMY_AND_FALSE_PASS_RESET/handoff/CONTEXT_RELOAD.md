# H01 Context Reload

stage_id: H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET
agent_invocation: main_agent
source_commit_before: c6e5fcdb18b1d4960c613f84a53b8c90109cc019

## Reloaded Documents

- `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md`: confirms H01 follows H00 and precedes H02.
- `docs/02_NON_NEGOTIABLE_CONTRACT.md`: H01 must use executable gates and convert unavailable exact-scale proof to `BLOCKED_WITH_REASON`.
- `docs/03_EVIDENCE_TAXONOMY.md`: existing evidence must be classified; only `REAL_EXACT_SCALE` or valid reconstructed real raw evidence can support milestone PASS.
- `docs/04_HARD_GATE_ARCHITECTURE.md`: H01 must write C00-shaped gate result artifacts under its stage directory.
- `docs/09_NO_SHORTCUT_RULES.md`: fixtures, legacy-only evidence, non-empty checks, and fake/PARTIAL timelines cannot satisfy real exact-scale claims.
- `docs/10_ACCEPTANCE_MATRIX.md`: H01 must preserve the exact-scale claim matrix and keep missing claims blocked, not omitted.
- `stages/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET.md`: classify existing evidence, mark the current M1 PASS as suspect unless proven, and update acceptance outputs to `BLOCKED_WITH_REASON` when M1-format claims are missing.

## Previous Stage Reload

- H00 created `scripts/m1h/`, generated `runs/m1-hardening/evidence_manifest.json`, and produced real design/worker/review artifacts.
- H00 review decision was `PASS`.
- H00 was pushed on branch `codex/valkey-scale-lab-loop`; the latest stage commit at H01 entry is `c6e5fcdb18b1d4960c613f84a53b8c90109cc019`.
- H00 deferred the historical `runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json` false-PASS reset to H01/H02.

## Current Evidence State

- `runs/m1-hardening/evidence_manifest.json` has all 29 required exact-scale claim ids and currently promotes none of them to PASS.
- Some setup claims are classified as `LEGACY_EVIDENCE_ONLY`; many command, management, workload, fault, system, report, and cleanup claims are `INVALID`, `FIXTURE_ONLY`, or `BLOCKED_WITH_REASON` because M1-format semantic acceptance is missing.
- The old M1-S09 acceptance report still says `milestone1_status: PASS` and lists fixture sources; H01 must generate a replacement hardening acceptance reset artifact that records `BLOCKED_WITH_REASON` until exact-scale M1-format evidence exists.

## H01 Work Direction

Strengthen H00 deferrals into normal H01 behavior: old M1 PASS reports must be treated as suspect inputs, required claims must stay blocked with explicit reasons, and `assert_no_legacy_m1_pass.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET` must pass because no current hardening acceptance output claims milestone PASS from legacy or fixture evidence.
