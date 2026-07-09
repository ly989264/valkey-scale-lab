# H05 Context Reload

Stage: H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING

Reloaded sources:

- AGENTS.md and the active goal require the exact H00-H10 stage order, real design/worker/review subagents, executable gates, and `assert_stage_exit.py --stage <stage_id>` before completion.
- `codex_goal_loop_m1_hardening_v2/START_HERE.md`, `AGENTS_M1H_V2.md`, and docs listed by `docs/00_INDEX.md` require fail-closed milestone1 acceptance. Exact-scale real M1-format evidence may pass; fixtures, legacy-only evidence, dry-runs, weak non-empty checks, and incomplete semantics must block with reasons.
- `docs/10_ACCEPTANCE_MATRIX.md` requires management matrix exact-scale PASS at 50, 100, and 200 nodes using M1-format matrix/results/diffs/workload impact/command refs.
- `stages/H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING.md` adds `python3 scripts/m1h/assert_management_exact_scale.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING`.
- H04 established stricter C07 command audit semantics. H05 management command references must not be allowed to pass from empty or invalid command evidence.

Current repository state entering H05:

- H04 is committed and pushed as `8f6b557f`.
- Current management matrix claims for 50/100/200 are `BLOCKED_WITH_REASON`.
- Existing real phase dirs contain `management_ops_matrix.json`, `management_operation_results.jsonl`, `management_command_log.jsonl`, `management_workload_impact.json`, and `valkey_e2e_evidence.json`, but current H04-era manifest did not yet include Valkey evidence for management matrix claims and does not enforce a full H05 management contract.

H05 implementation target:

- Strengthen management matrix manifest evaluation to require exact-scale real Valkey 9.1.x evidence and M1-format management artifacts.
- Require matrix status PASS, exact node counts, required operation coverage, per-operation PASS semantics, non-empty operation results, topology snapshot refs, workload impact/windows, and command references that resolve to command log rows.
- Do not promote current artifacts unless they satisfy the strengthened H05 semantics; blocked claims must include explicit reasons.
- Replace `assert_management_exact_scale.py` with a H05-specific gate that passes honest blocked claims but fails unsafe management PASS.
