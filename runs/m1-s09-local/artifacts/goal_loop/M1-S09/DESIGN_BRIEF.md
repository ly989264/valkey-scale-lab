# M1-S09 Design Brief

Role: simulated design subagent
Reason: explicit subagent capacity is unavailable, so this design is written as the required independent role artifact.

## Goal Understanding

M1-S09 is the milestone1 fail-closed acceptance gate. It must not implement new runtime features; it must inspect the artifacts and gates produced by M1-S01..M1-S08, check all milestone categories, ensure non-empty command/metrics/timeline/report artifacts, verify missing reasons, verify cross-scenario coverage, and output structured `PASS` / `FAIL` / `BLOCKED_WITH_REASON` statuses.

## Implementation Plan

- Add `scripts/assert_milestone1_acceptance.py`.
- Add `schemas/artifact/milestone1_acceptance_report.schema.json`.
- Gate inputs should be explicit directories for setup/management/workload/fault/system/report artifacts plus optional stage docs root.
- Gate checks:
  - command logs non-empty when present and required management evidence exists.
  - metrics JSONL non-empty for workload/system metrics.
  - fault timeline events non-empty for fault evidence.
  - Chinese offline report passes `assert_zh_offline_report_m1.py` contract shape from rendered artifacts.
  - missing metrics have reasons and are aggregated in analysis/report.
  - coverage spans small/30/50/100/200 fixtures or real/block artifacts.
  - blocked heavy rungs are represented as `BLOCKED_WITH_REASON`, not PASS.
- Output `milestone1_acceptance_report.json` with required top-level category statuses.

## Review Fail Conditions

Fail if any category silently passes without source artifacts, if empty JSONL is accepted, if missing/blocked values lack reasons, if exact heavy real blocked rows are reported as PASS, or if the Chinese report can depend on external URLs/LLM.
