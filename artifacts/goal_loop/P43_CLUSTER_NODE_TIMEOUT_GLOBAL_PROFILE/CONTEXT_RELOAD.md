# CONTEXT_RELOAD - P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE

## Current Context

- Date/time: 2026-07-07 Asia/Shanghai.
- Branch: `codex/valkey-scale-lab-loop`.
- Current stage: `P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE`, explicitly requested by the user after completed P42.
- Harness status: `python3 scripts/codex_gate.py next` returned `COMPLETE_AUTOMATIC_PHASES`; P43 is therefore a user-directed non-automatic follow-on stage.
- Git status before implementation includes pre-existing untracked P14/P41 artifact directories plus new P43 stage-control files.

## Required Documents Reloaded

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
- `docs/codex/goal-loop/stages/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE.md`

## Stage Contract Summary

P43 must move `cluster-node-timeout` out of hidden phase-specific hardcodes and into global/profile/scenario/CLI configuration. The default effective timeout is `30000` ms. Generated `valkey.conf`, run state, config validation, real Valkey evidence, scale artifacts, and reports must record requested/effective timeout and source. A failover RTO timeout-matrix runner must support explicit `5000/10000/15000/30000/60000` selections without defaulting to all large runs or fabricating matrix data. Fake/schema, smoke real, 30/50/100/200 real, and greater-than-200 dry-run projection paths must all expose timeout evidence.

## Key Safety Constraints

- Do not weaken cleanup, coverage, no-bypass, or real-evidence gates.
- Do not silently downscale 30/50/100/200 real evidence.
- Do not present fake or static timeout matrix data as real.
- Do not mutate host network configuration.
- Do not default to 1000 nodes; greater-than-200 remains dry-run projection unless separately authorized.

## Blockers And Assumptions

- Initial blocker: P43 stage document was absent. A harness exception was written and the stage document was added so the reload could complete.
- Real 30/50/100/200 execution remains resource-gated. If resources fail, artifacts must record `BLOCKED` or `NOT_RUN_WITH_REASON`; no fake values may be used.
