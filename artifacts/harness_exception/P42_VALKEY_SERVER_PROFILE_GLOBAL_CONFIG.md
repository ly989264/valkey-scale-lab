# Harness Exception - P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG

## Defect

The user requested `P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG`, but the repository did not contain a stage document under `docs/codex/goal-loop/stages/`. `AGENTS.md` requires the current stage document to exist and be reread before implementation.

## Patch

Add `docs/codex/goal-loop/stages/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG.md` by transcribing the user-provided phase requirements into a fail-closed stage contract. This preserves the harness rule by making P42 explicit instead of relying on chat memory.

## Before

P42 could not satisfy the required document reload rule because the stage document was absent.

## After

P42 has an authoritative stage document requiring global server profile config, io-thread budget protection, memory preflight/enforcement evidence, scale-generic real and dry-run coverage, assertion scripts, tests, and review before completion.
