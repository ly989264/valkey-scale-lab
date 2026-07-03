# CONTEXT_RELOAD - P27_STRICT_MATRIX_REBASE_HARNESS

## Stage

- Stage ID: P27_STRICT_MATRIX_REBASE_HARNESS
- Stage title: Strict matrix harness rebase
- Branch: codex/valkey-scale-lab-loop
- Current commit: ea2493b58a79f9b9b5c7770ce136c270fa31bec2
- Date/time: 2026-07-03

## Harness status

```text
python3 scripts/codex_gate.py next
COMPLETE_AUTOMATIC_PHASES
```

Interpretation: this is the expected older-loop completion state. Per `CODEX_STRICT_MATRIX_LOOP_START.md`, this does not satisfy the strict loop because P27-P40 are not yet present in `codex/phase_manifest.json`; P27 is therefore the current stage.

## Git status

```text
git status --short
<clean before this CONTEXT_RELOAD.md was written>
```

## Documents reread

- [x] AGENTS.md
- [x] CODEX_START_HERE.md
- [x] CODEX_GOAL_LOOP_START.md
- [x] CODEX_STRICT_MATRIX_LOOP_START.md
- [x] docs/codex/goal-loop/00_INDEX.md
- [x] docs/codex/goal-loop/01_GOAL_CONTRACT.md
- [x] docs/codex/goal-loop/02_STAGE_MANIFEST.md
- [x] docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md
- [x] docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md
- [x] docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md
- [x] docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md
- [x] docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md
- [x] docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md
- [x] docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md
- [x] docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md
- [x] docs/codex/goal-loop-strict/00_INDEX.md
- [x] docs/codex/goal-loop-strict/01_STRICT_GOAL_CONTRACT.md
- [x] docs/codex/goal-loop-strict/02_STRICT_STAGE_MANIFEST.md
- [x] docs/codex/goal-loop-strict/03_MAIN_SUBAGENT_LOOP_PROTOCOL.md
- [x] docs/codex/goal-loop-strict/04_CONTEXT_LEDGER_PROTOCOL.md
- [x] docs/codex/goal-loop-strict/05_FAIL_CLOSED_HARNESS_CONTRACT.md
- [x] docs/codex/goal-loop-strict/06_COVERAGE_REGISTRY_SPEC.md
- [x] docs/codex/goal-loop-strict/07_QUANTIFICATION_DATA_CONTRACT.md
- [x] docs/codex/goal-loop-strict/08_MANAGEMENT_OPERATION_MATRIX_SPEC.md
- [x] docs/codex/goal-loop-strict/09_FAULT_FAILOVER_MATRIX_SPEC.md
- [x] docs/codex/goal-loop-strict/10_SCALE_EXECUTION_POLICY.md
- [x] docs/codex/goal-loop-strict/11_ANALYSIS_VISUAL_REPORT_SPEC.md
- [x] docs/codex/goal-loop-strict/12_AUDIT_COMMIT_NO_BYPASS_POLICY.md
- [x] docs/codex/goal-loop-strict/stages/P27_STRICT_MATRIX_REBASE_HARNESS.md
- [x] artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md if present: not present at stage start

## Current stage contract summary

P27 must append strict automatic stages P27-P40 to the manifest, set `automatic_stop_after` to `P40_STRICT_FINAL_AUDIT_CLOSEOUT`, keep P14 non-automatic, keep the project default cap at 100 nodes, and explicitly model P32/P35/P36 as bounded exact 200-node exceptions. It must extend the harness so strict stage discovery, strict Markdown handoffs, strict review/audit requirements, coverage registry checks, exact-scale real evidence assertions, dry-run no-runtime checks, visual report checks, and anti-bypass checks fail closed.

P27 is a harness/scaffolding stage only. It must not claim real 50/100/200 runtime coverage, fake real Valkey evidence, run >200 real clusters, downshift future 200-node stages, mutate host networking, or manually edit phase state/gate results to force completion.

Required P27 artifacts include `phase_summary.json`, `quant_summary.json`, `harness_extension_report.json`, `strict_manifest_report.json`, this context reload, a design brief, a worker summary, and review/audit artifacts. P27 gates must include safety scan, compile, tests, strict stage contract, anti-bypass, coverage registry bootstrap, and codex gate run/postcheck.

## Prior-stage handoff summary

Older automatic stages P00-P26 are marked complete in `codex/status/phase_state.json`; `python3 scripts/codex_gate.py next` currently reports `COMPLETE_AUTOMATIC_PHASES`. No strict stage journal exists yet. The strict bootstrap overrides the older completion status and requires P27 first.

## Known blockers

- None yet. P27 is expected to modify locked harness files; any lock update must be documented as strengthening the harness and must preserve lock enforcement.
- The local branch is already ahead of origin by one commit before P27 work; do not rewrite or squash that existing commit.

## Assumptions and 待验证 items

- 待验证: whether all P28-P40 stage docs are already present and complete.
- 待验证: whether existing schemas can validate the new strict phase artifacts or need P27-specific schema additions.
- 待验证: whether existing `codex_gate.py` postcheck can be extended without weakening prior P15-P26 behavior.
- 待验证: exact command set required by the existing test suite after strict assertion scripts are added.
