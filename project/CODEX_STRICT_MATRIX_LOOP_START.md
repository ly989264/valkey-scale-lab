# CODEX_STRICT_MATRIX_LOOP_START.md — Strict Goal-Mode Loop Entry

Use this file to launch the strict Codex App Goal-mode loop for `valkey-scale-lab`.

This package is intentionally stricter than the existing P15-P26 goal loop. The existing loop can be treated as prior implementation evidence, but it is not sufficient for the clarified target: full management, fault, telemetry, analysis, and visualization coverage at real 50/100/200-node clusters, plus dry-run-only support above 200 nodes.

## Operator goal

Implement a strict, multi-stage, multi-agent loop that proves the following with fail-closed harness checks:

```text
real 50 nodes:  full lifecycle + management matrix + fault/failover matrix + metrics + analysis + report
real 100 nodes: full lifecycle + management matrix + fault/failover matrix + metrics + analysis + report
real 200 nodes: full lifecycle + management matrix + fault/failover matrix + metrics + analysis + report
>200 nodes:     dry-run planning/support only; no real containers or real cluster execution
```

`PASS` is allowed only when the required operation or fault was actually executed and independently verified. A generated artifact is not proof. A worker summary is not proof. A visual report that contains broken charts, `NaN`, `undefined`, missing images, empty tables, or misleading zeroes is not complete.

## How to place these files

Copy the contents of this zip into the repository root while preserving paths. The zip contains Markdown files only; do not use a shell script to generate or place the Markdown files.

Expected new root-level file:

```text
CODEX_STRICT_MATRIX_LOOP_START.md
```

Expected new document tree:

```text
docs/codex/goal-loop-strict/
```

## First action in Codex App Goal mode

Paste the full prompt from:

```text
docs/codex/goal-loop-strict/prompts/GOAL_MODE_STRICT_START_PROMPT.md
```

Then let the main agent execute the stage loop.

## Bootstrap rule

At the time this strict package is applied, the existing repository may report `COMPLETE_AUTOMATIC_PHASES` because P00-P26 have already completed. That is not a reason to stop.

The main agent must:

1. read `AGENTS.md`, `CODEX_START_HERE.md`, `CODEX_GOAL_LOOP_START.md`, this file, and all files listed in `docs/codex/goal-loop-strict/00_INDEX.md`;
2. inspect `codex/phase_manifest.json`, `codex/status/phase_state.json`, and `scripts/codex_gate.py`;
3. if P27-P40 are absent from the manifest, implement `P27_STRICT_MATRIX_REBASE_HARNESS` first;
4. after P27 extends the manifest and harness, continue with `python3 scripts/codex_gate.py next`;
5. never treat P15-P26 completion as satisfying the stricter P27-P40 contract.

## Required stage sequence

```text
P27_STRICT_MATRIX_REBASE_HARNESS
P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER
P29_QUANT_TELEMETRY_COLLECTOR_HARDENING
P30_MANAGEMENT_MATRIX_50_REAL
P31_MANAGEMENT_MATRIX_100_REAL
P32_MANAGEMENT_MATRIX_200_REAL
P33_FAULT_FAILOVER_MATRIX_50_REAL
P34_FAULT_FAILOVER_MATRIX_100_REAL
P35_FAULT_FAILOVER_MATRIX_200_REAL
P36_FULL_FLOW_E2E_50_100_200_REAL
P37_200_PLUS_DRY_RUN_SUPPORT
P38_CROSS_SCALE_ANALYSIS_REGRESSION
P39_VISUAL_REPORT_QUALITY_GATE
P40_STRICT_FINAL_AUDIT_CLOSEOUT
```

## Required command pattern after P27 is in the manifest

For every stage:

```bash
python3 scripts/codex_gate.py precheck --phase <STAGE_ID>
python3 scripts/codex_gate.py run --phase <STAGE_ID>
# run any additional stage-specific assertions listed in the stage document
python3 scripts/codex_gate.py postcheck --phase <STAGE_ID>
python3 scripts/codex_gate.py mark-complete --phase <STAGE_ID>
git status --short
git add <intentional stage files>
git commit -m "<STAGE_ID>: <concise summary>"
git push
```

Do not run `mark-complete`, commit, or push until design, worker, review, gates, artifacts, and cleanup all satisfy the current stage contract.

## Approval rules for the human operator

Approve project-scoped operations only:

```text
allowed: read/edit repository files
allowed: run Python tests and harness scripts
allowed: run Docker commands for owned containers/networks/volumes only
allowed: collect logs from owned containers
allowed: commit and push one completed stage at a time
```

Do not approve:

```text
forbidden: sudo for network, firewall, routing, or interface changes
forbidden: host firewall or route mutation
forbidden: killing unrelated host processes
forbidden: modifying global OS services
forbidden: real execution above 200 nodes
forbidden: downshifting a required 200-node real stage to 100 nodes
forbidden: manually editing phase state or gate results to force PASS
```

## Completion condition

The loop is complete only when P27-P40 are present in the manifest, `automatic_stop_after` points to `P40_STRICT_FINAL_AUDIT_CLOSEOUT`, all P27-P40 automatic stages pass their gates and reviews, every required artifact validates, every required 50/100/200 matrix cell is covered by real evidence, every >200 cell is dry-run-only with zero runtime proof, and P40 has been committed and pushed.
