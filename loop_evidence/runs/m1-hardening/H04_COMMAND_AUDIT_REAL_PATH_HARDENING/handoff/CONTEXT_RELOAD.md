# H04 Context Reload

Stage: H04_COMMAND_AUDIT_REAL_PATH_HARDENING

Reloaded sources:

- AGENTS.md and user goal instructions require the exact H00-H10 hardening order, real design/worker/review subagents for each stage, executable gates, and `assert_stage_exit.py --stage <stage_id>` before completion.
- `codex_goal_loop_m1_hardening_v2/START_HERE.md`, `AGENTS_M1H_V2.md`, and docs listed by `docs/00_INDEX.md` define fail-closed milestone1 hardening: exact-scale real M1-format evidence may pass; fixtures, dry-runs, legacy-only evidence, weak non-empty checks, and simulated subagents may not.
- `contracts/C04_EXACT_SCALE_REQUIREMENTS.md` requires command audit exact-scale claims for 50, 100, and 200 nodes.
- `contracts/C07_COMMAND_AUDIT_CONTRACT.md` requires non-empty schema-valid command logs, no placeholder commands, required command kinds (`cluster_meet`, `cluster_addslots`, `cluster_replicate`, `cluster_probe`, `cleanup`) where applicable, operation traceability to command ids, stdout/stderr refs or hashes, and retry/failure/timeout summaries.
- `docs/17_COMMANDS_AND_GATES.md` requires compile, pytest, no-fixture, no-legacy, no-simulated, and stage-exit gates.
- `docs/18_STAGE_EXIT_CONTRACT.md` requires gate result JSON, real subagent artifacts, review PASS, and no text-only completion.
- `stages/H04_COMMAND_AUDIT_REAL_PATH_HARDENING.md` adds `python3 scripts/m1h/assert_command_audit_real.py --stage H04_COMMAND_AUDIT_REAL_PATH_HARDENING`.

Current repository state entering H04:

- H00-H03 have been committed and pushed on `codex/valkey-scale-lab-loop`.
- H03 hardened setup telemetry claims so setup exact-scale PASS now requires C06 M1-format telemetry, real exact-scale Valkey 9.1.x proof, numeric core metrics, and complete per-node samples.
- Current command audit manifest logic remains weak: it only checks for command-log presence and any command rows, and it does not yet enforce C07 schema, required kinds, placeholder rejection, output refs/hashes, traceability, retry/failure/timeout summary, or hardening acceptance.
- Existing management command logs under P30/P31/P32 and full-flow command logs under P36 include historical rows, but old rows may lack the full C07 schema fields. They must therefore block with reasons rather than become exact-scale PASS unless all C07 requirements are met.

H04 implementation target:

- Strengthen manifest command audit evaluation to fail closed for 50/100/200 unless exact-scale real Valkey 9.1.x evidence and C07-complete command audit artifacts exist.
- Replace the generic `assert_command_audit_real.py` wrapper with a H04-specific gate that passes an honest blocked result, fails unsafe command PASS, and writes detailed gate diagnostics.
- Add tests proving valid C07 exact-scale command audit can pass and that empty, placeholder, fixture, missing-kind, or incomplete legacy logs block.
