# GOAL_MODE_START_PROMPT.md

You are running a Codex App goal-mode hardening loop for `ly989264/valkey-scale-lab`.

## Goal

Fix the false-PASS and weak-harness issues discovered after the earlier milestone1 loop. Do not redo milestone1 from scratch. Harden the repository so that milestone1 can only be PASS when exact-scale M1-format real evidence exists; otherwise it must be `BLOCKED_WITH_REASON`.

## Mandatory first read

Read:

- `codex_goal_loop_m1_hardening_v2/START_HERE.md`
- `codex_goal_loop_m1_hardening_v2/AGENTS_M1H_V2.md`
- every document in `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md`
- current repository files related to milestone1 acceptance and artifacts.

## Stage order

Run exactly this order:

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

## Multi-agent rule

For every stage, launch real design, worker, and review subagents. If real subagents cannot be launched, stop the stage as `BLOCKED_WITH_REASON`. Do not create simulated subagent artifacts.

## Hard gate rule

No stage can complete by text. Each stage must implement/run its required executable gates, write gate artifacts, and pass `scripts/m1h/assert_stage_exit.py --stage <stage_id>`.

## Correct final result

Acceptable final outcomes:

- hardening loop PASS + milestone1 PASS, only with exact-scale M1-format real evidence;
- hardening loop PASS + milestone1 BLOCKED_WITH_REASON, if exact-scale evidence cannot be produced here.

Unacceptable:

- milestone1 PASS using fixtures;
- milestone1 PASS using legacy-only evidence;
- milestone1 PASS with skipped core real metrics;
- milestone1 PASS with fake/PARTIAL fault timelines;
- milestone1 PASS with weak non-empty checks.
