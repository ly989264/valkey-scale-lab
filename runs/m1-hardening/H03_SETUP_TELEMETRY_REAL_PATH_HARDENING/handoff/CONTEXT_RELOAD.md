# H03 Context Reload

stage_id: H03_SETUP_TELEMETRY_REAL_PATH_HARDENING
agent_invocation: main_agent
source_commit_before: 65089a70901e8ccb7be4af89bf0bee92ad4e2016

## Reloaded Documents

- `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md`: H03 follows the fail-closed acceptance stages and begins capability-specific hardening.
- `docs/02_NON_NEGOTIABLE_CONTRACT.md`: setup telemetry cannot pass through prose or skipped core metrics.
- `docs/03_EVIDENCE_TAXONOMY.md`: legacy real setup evidence can be historical input only, not M1 PASS.
- `docs/04_HARD_GATE_ARCHITECTURE.md`: H03 must produce C00 gate artifacts.
- `docs/09_NO_SHORTCUT_RULES.md`: non-empty timing files and skipped metrics cannot prove exact-scale setup telemetry.
- `docs/10_ACCEPTANCE_MATRIX.md`: setup telemetry requires exact scales 30, 50, 100, and 200 for milestone PASS.
- `contracts/C06_SETUP_TELEMETRY_CONTRACT.md`: exact-scale setup PASS requires numeric core metrics and per-node sample fields; `SKIPPED_WITH_REASON` is forbidden for exact-scale PASS.
- `stages/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING.md`: ensure real setup telemetry claims require numeric core metrics, otherwise produce blocked claims.

## Previous Stage Reload

- H02 produced a reusable fail-closed milestone acceptance report.
- Active milestone state is `BLOCKED_WITH_REASON` with 29 blocked claims and 0 passed claims.
- H02 was committed and pushed as `65089a70901e8ccb7be4af89bf0bee92ad4e2016`.

## Current Setup Telemetry State

- The schema `schemas/artifact/setup_telemetry.schema.json` requires the setup telemetry artifact and core metric names.
- Runtime code in `src/valkey_scale_lab/runtime/setup_timeline.py` defines setup telemetry generation and currently allows structured missing/skipped metric values in the generic schema.
- Historical setup-related artifacts exist as `runtime_timing_breakdown*.json` and Valkey evidence under `artifacts/phases/`, but H03 must not promote them unless they satisfy numeric M1 setup telemetry and per-node sample requirements.

## H03 Direction

Strengthen `assert_setup_core_metrics.py` and manifest setup claim semantics so exact-scale setup claims remain blocked unless a real exact-scale setup telemetry artifact has all C06 numeric core metrics and required per-node sample fields.
