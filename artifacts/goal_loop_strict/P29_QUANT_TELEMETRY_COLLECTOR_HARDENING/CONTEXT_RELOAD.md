# CONTEXT_RELOAD - P29_QUANT_TELEMETRY_COLLECTOR_HARDENING

## Stage

- Stage ID: P29_QUANT_TELEMETRY_COLLECTOR_HARDENING
- Stage title: Quant telemetry collector hardening
- Branch: codex/valkey-scale-lab-loop
- Current commit: dbfed9116d64fa8c10a106c677b961d67f123c83
- Date/time: 2026-07-03

## Harness status

```text
python3 scripts/codex_gate.py next
P29_QUANT_TELEMETRY_COLLECTOR_HARDENING
```

P29 is current because P28 was postchecked, marked complete, committed, and pushed. The worktree was clean before this context reload was written.

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
- [x] docs/codex/goal-loop-strict/stages/P29_QUANT_TELEMETRY_COLLECTOR_HARDENING.md
- [x] artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md

## Current stage contract summary

P29 must harden the telemetry model before large real stages. It must implement or strengthen event and metric JSONL writers, workload window aggregation, topology snapshots, Valkey INFO / CLUSTER INFO / CLUSTER NODES sampling, Docker/process stats sampling where available, missing-data encoding, provenance writing, and schema validation helpers.

P29 must run a bounded small real Valkey proof for collector smoke and must not claim 50/100/200 matrix coverage. Required artifacts include `phase_summary.json`, `valkey_e2e_evidence.json`, `cleanup_report.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `quant_summary.json`, `coverage_ledger.json`, and `telemetry_completeness_report.json`.

Pass requires real Valkey proof, JSONL line-by-line validation, explicit reasons for every `MISSING` metric, rejection of null/NaN/undefined, complete workload window metrics, provenance links from raw samples to summaries, and cleanup PASS.

## Prior-stage handoff summary

P28 generated `artifacts/coverage/strict_coverage_registry.json`, `strict_required_matrix.csv`, and `strict_scenario_plan.json`. All real 50/100/200 rows remain `PENDING`. The P28 scenario plan requires every real scenario to include `events.jsonl`, `metrics_timeseries.jsonl`, and `workload_windows.json` with a telemetry policy; P29 should harden the collectors and validators that later stages rely on.

## Known blockers

- None confirmed yet. P29 is real-Valkey-required and may block if Docker/runtime resources are unavailable or if the real Valkey smoke gate cannot run safely.

## Assumptions and 待验证 items

- 待验证: whether the existing `scripts/valkey_e2e_gate.py` already emits enough collector artifacts for P29 or needs a P29-specific telemetry wrapper.
- 待验证: whether current `assert_quant_completeness.py` enforces strict P29 telemetry completeness or needs strengthening.
- 待验证: whether existing workload window schemas cover all strict P29 window metrics without allowing null or silent omissions.
