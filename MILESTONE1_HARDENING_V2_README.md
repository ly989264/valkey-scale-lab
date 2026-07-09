# Milestone1 hardening goal-loop v2 for valkey-scale-lab

This package is a Markdown-only Codex App goal-mode package. It does **not** contain placement scripts. Copy or unzip it at the repository root of `ly989264/valkey-scale-lab` and start Codex App goal mode with:

```text
codex_goal_loop_m1_hardening_v2/prompts/GOAL_MODE_START_PROMPT.md
```

## Purpose

This package does not ask Codex to redo milestone1 from scratch. It asks Codex to harden the existing milestone1 implementation and fix the false-PASS failure modes already observed:

- milestone1 reported PASS while real M1-format evidence was incomplete;
- acceptance gates used fixture fallback and non-empty checks;
- legacy real evidence was accepted as proof of new M1 capabilities;
- setup telemetry core real-run phases were `SKIPPED_WITH_REASON`;
- real 200-node management command log remained empty;
- workload benchmark passed with one metric row;
- fault timeline relied on fake/PARTIAL artifacts;
- Chinese report generation passed even when source evidence quality was insufficient.

## Main design difference from the previous package

The previous package relied too much on natural-language discipline. This v2 package requires Codex to implement **machine-checkable contracts** before a stage can pass. A stage is not complete because a review document says it is complete. A stage is complete only when its stage-specific hard gates exit 0, produce gate result artifacts, and are reviewed by an independent review agent.

## Correct final outcomes

The hardening loop may end in one of two acceptable states:

```text
hardening_loop_status: PASS
milestone1_status: PASS
```

Only if exact-scale M1-format real evidence is complete.

Or:

```text
hardening_loop_status: PASS
milestone1_status: BLOCKED_WITH_REASON
```

If the current environment cannot rerun or reconstruct exact 30/50/100/200 real evidence. This is not failure; it is the correct fail-closed result. A false `milestone1_status: PASS` is failure.

## Required stage sequence

```text
H00_BOOTSTRAP_HARD_GATES
H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET
H02_ACCEPTANCE_GATE_FAIL_CLOSED
H03_SETUP_TELEMETRY_REAL_PATH_HARDENING
H04_COMMAND_AUDIT_REAL_PATH_HARDENING
H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
H06_WORKLOAD_BENCHMARK_HARDENING
H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING
H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING
H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING
H10_FINAL_HARDENING_ACCEPTANCE
```

Every stage uses design -> worker -> review multi-agent flow. Simulated subagent documents are forbidden. If Codex cannot start a real subagent, the current stage must stop as `BLOCKED_WITH_REASON`.
