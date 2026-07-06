# CONTEXT_RELOAD - P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG

## Runtime Context

- Reloaded at: 2026-07-06T15:25:11Z
- Branch: `codex/valkey-scale-lab-loop`
- Harness next: `python3 scripts/codex_gate.py next` returned `COMPLETE_AUTOMATIC_PHASES`; P42 is user-requested and not yet present in the manifest at reload time.
- Git status included pre-existing untracked P14/P41 artifact directories plus new P42 stage-doc and harness-exception files.

## Required Docs Read

- `AGENTS.md`
- `CODEX_START_HERE.md`
- `CODEX_GOAL_LOOP_START.md`
- `docs/codex/02_PHASES.md`
- `docs/codex/04_AUDITOR.md`
- `docs/codex/goal-loop/00_INDEX.md`
- `docs/codex/goal-loop/01_GOAL_CONTRACT.md`
- `docs/codex/goal-loop/02_STAGE_MANIFEST.md`
- `docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md`
- `docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md`
- `docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md`
- `docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md`
- `docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md`
- `docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md`
- `docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md`
- `docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md`
- `docs/codex/goal-loop/stages/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG.md`

## Stage Contract Summary

P42 must add a global Valkey server profile config merged as built-in defaults, global config, scenario config, then CLI override. It must introduce `runtime.server_profile`, `runtime.valkey.io_threads`, `runtime.valkey.io_threads_auto`, per-node and total io-thread budgets, `runtime.valkey.log_format`, and global `cluster.node_memory_limit_mb=64`. Runtime config generation must write `io-threads <N>` only when effective threads exceed one, must record `effective_io_threads=1` otherwise, and must prevent high blind defaults. Resource preflight must calculate node memory, nodehost memory projection, host available memory, and `can_run`; insufficient memory must block or fail closed. Real and dry-run evidence must include generated configs, effective profile artifacts, run-state node fields, validation fields, and assertion-script coverage for smoke, 30, 50, 100, 200, and greater-than-200 projection-only paths.

## Safety Notes

Host networking remains forbidden. The stage may use Docker-owned runtime controls and generated Valkey configs only. Greater-than-200 remains dry-run projection unless a future explicit policy allows real execution. Missing values must use `MISSING` or `SKIPPED_WITH_REASON`.

## Blockers And Assumptions

The P42 stage document was absent, which would block the required reload rule. A harness exception was written and the stage document was added as a strengthening fix before implementation. The stage should add manifest and gate-lock coverage rather than bypassing the harness.
