# H02 Context Reload

stage_id: H02_ACCEPTANCE_GATE_FAIL_CLOSED
agent_invocation: main_agent
source_commit_before: 577b37d3aaadc5bc87f81090b02014133d318b1f

## Reloaded Documents

- `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md`: H02 follows H01 and must run before capability-specific hardening stages.
- `docs/02_NON_NEGOTIABLE_CONTRACT.md`: acceptance must be executable and fail closed, never prose-only.
- `docs/03_EVIDENCE_TAXONOMY.md`: only `REAL_EXACT_SCALE` or valid reconstructed M1-format real raw evidence may promote a required claim to PASS.
- `docs/04_HARD_GATE_ARCHITECTURE.md`: H02 must write C00 gate results under `runs/m1-hardening/H02_ACCEPTANCE_GATE_FAIL_CLOSED/artifacts/gates/`.
- `docs/09_NO_SHORTCUT_RULES.md`: fixture fallback, legacy promotion, skipped metric promotion, and non-empty checks are forbidden.
- `docs/10_ACCEPTANCE_MATRIX.md`: milestone PASS requires every exact-scale required claim to PASS; any missing claim keeps milestone status blocked.
- `stages/H02_ACCEPTANCE_GATE_FAIL_CLOSED.md`: rewrite milestone1 acceptance logic so fixture fallback and legacy-only evidence cannot produce milestone PASS, and emit the required claim ledger.

## Previous Stage Reload

- H01 generated `runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/artifacts/milestone1_acceptance_reset.json`.
- The old M1-S09 PASS is superseded as suspect historical evidence.
- Active hardening acceptance is `milestone1_status: BLOCKED_WITH_REASON`, with 29 required claims, 0 passed claims, and 29 blocked claims with reasons.
- H01 committed and pushed as `577b37d3aaadc5bc87f81090b02014133d318b1f`.

## Current Acceptance State

`scripts/assert_milestone1_acceptance.py` now reads the generated hardening evidence manifest and emits a claim-ledger acceptance report rather than the previous fixture fallback report. H02 must harden `scripts/m1h/assert_final_milestone1_hardened.py` and stage exit so the fail-closed acceptance contract is reusable and machine-enforced.
