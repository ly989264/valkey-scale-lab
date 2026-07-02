# AGENTS.md — Valkey Scale Lab Goal Loop Harness

This repository is built by Codex in a strict phase/stage loop. This file is the controlling instruction source. Before editing code, Codex must read `CODEX_START_HERE.md` and the goal-loop documents under `docs/codex/goal-loop/`.

## Mission

Build `valkey-scale-lab`: a local-first, Docker-sandboxed test and analysis harness for Valkey 9.1.x cluster behavior at increasing scale. The system must support Mac and Linux, single-host and multi-host operation, virtual AZ placement, real Valkey e2e gates, sandboxed fault injection, quantitative metric collection, analysis, and report generation.

Machine-readable artifacts are the product. Charts, HTML, and Markdown reports are views over versioned artifacts only.

## Current goal-loop mission

Extend the existing bootstrap so the Codex App Goal-mode loop completes all missing cluster-management and fault/failover coverage:

1. Management operation matrix: remove node, reshard, rebalance, and rolling restart must be real operations with timing, convergence, workload, and error telemetry.
2. Fault matrix: primary stop is not enough. Add 30/50/100/200-node failover latency curves, replica stop, node-host stop, AZ stop, network delay, packet loss, partition, flap, minority/majority partition, split-brain-window measurement, and fault-period workload QPS/latency/error impact.
3. Quantification: every new capability must produce schema-validated metrics and event artifacts. Missing values must be encoded as `MISSING` or `SKIPPED_WITH_REASON` with a reason; values must never be invented.
4. Strong harness: no stage can be marked complete, committed, or pushed until required gates, artifacts, and review pass.

## Non-negotiable safety rules

1. Never default to 1000 Valkey nodes.
2. Normal development defaults remain capped at 100 nodes. The new 200-node failover curve stage is a user-required bounded exception; it must run only after explicit resource preflight passes, and it is not a precedent for any larger default.
3. Never change physical host network configuration.
4. Never modify global firewall, routing, PF, nftables, iptables, host interfaces, or OS network services.
5. Never use `sudo` for network, route, firewall, or interface changes as a default path.
6. Fault injection must be scoped to owned Docker/container namespaces, owned containers, or an explicit sandbox proxy layer.
7. Never kill physical host network interfaces or unrelated host processes.
8. Every started process/container must have deterministic cleanup logic, state files, and ownership labels.
9. Ports, directories, PID files, container names, and run IDs must be deterministic and collision-checked.
10. Fake tests may support early development, but fake-only gates must never be presented as real Valkey evidence.
11. No phase/stage may pass without required artifacts, schema validation, gate logs, and an audit/review decision.
12. Missing metrics must be encoded as `MISSING` or `SKIPPED_WITH_REASON`; never invent values.
13. Codex must not stop after skeleton work. Continue through all automatic stages until the next stage is blocked by a real gate failure.

## Harness integrity rules

The files below are harness controls. Do not weaken, delete, bypass, or edit lock/state files to hide changes:

```text
codex/phase_manifest.json
codex/gate_lock.json
scripts/*.py
schemas/**/*.json
templates/**/*
docs/codex/**/*
.github/workflows/codex-gates.yml
```

If a harness file is truly defective, stop the current stage, write `artifacts/harness_exception/<STAGE_ID>.md`, and make the smallest fix that strengthens or preserves the original requirement. The stage review must cite the defect, patch, and before/after behavior.

## Required document reload at every stage start

At the start of every stage, the main agent must reread and summarize these files in `artifacts/goal_loop/<STAGE_ID>/CONTEXT_RELOAD.md`:

```text
AGENTS.md
CODEX_START_HERE.md
CODEX_GOAL_LOOP_START.md
docs/codex/02_PHASES.md
docs/codex/04_AUDITOR.md
docs/codex/goal-loop/00_INDEX.md
docs/codex/goal-loop/01_GOAL_CONTRACT.md
docs/codex/goal-loop/02_STAGE_MANIFEST.md
docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md
docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md
docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md
docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md
docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md
docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md
docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md
docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md
docs/codex/goal-loop/stages/<CURRENT_STAGE>.md
```

If any required document is absent, the current stage is blocked. Do not continue based on memory.

## Required multi-agent stage loop

For every automatic stage after the goal-loop documents are placed:

1. Main agent determines the current stage from `codex/phase_manifest.json` and `codex/status/phase_state.json`. If the manifest does not yet include the goal-loop stages, the first stage is `P15_GOAL_REBASE_HARNESS_EXTENSION`.
2. Main agent performs the required document reload and writes `CONTEXT_RELOAD.md`.
3. Main agent launches a design subagent using `docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md`. The design subagent is read-only and must produce `DESIGN_BRIEF.md`.
4. Main agent launches a worker subagent using `docs/codex/goal-loop/prompts/WORKER_SUBAGENT_PROMPT.md`. The worker implements only the current stage and must produce `WORKER_SUMMARY.md`.
5. Main agent runs the stage gates and artifact checks. If a gate fails, fix the current stage only and rerun the same stage loop from the worker step.
6. Main agent launches a review subagent using `docs/codex/goal-loop/prompts/REVIEW_SUBAGENT_PROMPT.md`. The review subagent is fresh-context and must produce `REVIEW.md` with `Decision: PASS` or `Decision: FAIL`.
7. A stage with `Decision: FAIL` is not complete. Fix findings, rerun gates, and rerun review.
8. After review passes, run `python3 scripts/codex_gate.py postcheck --phase <STAGE_ID>`.
9. Run `python3 scripts/codex_gate.py mark-complete --phase <STAGE_ID>` only after postcheck passes.
10. Commit and push the stage on the current branch before starting the next stage.

No stage may be marked complete, committed, or pushed before the current stage's required implementation, gates, artifacts, and review are complete.

## Real Valkey gates

From P03 onward, each capability must have at least one real Valkey e2e proof. A real proof must be produced by the pre-authored or newly strengthened wrapper scripts, not by project tests alone:

```text
scripts/valkey_e2e_gate.py
scripts/fault_safety_gate.py
scripts/fault_failover_gate.py
new scripts/assert_* goal-loop harness checks created in P15
```

A gate is not real if it only asserts mocks, fake Valkey, generated logs, or static files. The wrapper must independently probe live Valkey endpoints and produce evidence with Valkey 9.1.x version data.

## Project interface contract

Codex must implement a Python package importable as `valkey_scale_lab` and a CLI module callable as:

```bash
python3 -m valkey_scale_lab.cli <command> ...
```

The gate wrappers call these commands and any goal-loop extensions must preserve them:

```bash
python3 -m valkey_scale_lab.cli config validate ...
python3 -m valkey_scale_lab.cli plan ...
python3 -m valkey_scale_lab.cli gate scenario \
  --phase <PHASE_ID> \
  --scenario <SCENARIO_NAME> \
  --config <CONFIG_PATH> \
  --artifacts-dir <ARTIFACT_DIR> \
  --state-out <STATE_JSON>
python3 -m valkey_scale_lab.cli gate cleanup \
  --state <STATE_JSON> \
  --artifacts-dir <ARTIFACT_DIR> \
  --out <CLEANUP_JSON>
python3 -m valkey_scale_lab.cli fault apply \
  --state <STATE_JSON> \
  --target-logical-id <NODE_LOGICAL_ID> \
  --fault-json <FAULT_JSON> \
  --out <FAULT_APPLY_JSON>
python3 -m valkey_scale_lab.cli fault clear \
  --state <STATE_JSON> \
  --fault-id <FAULT_ID> \
  --out <FAULT_CLEAR_JSON>
python3 -m valkey_scale_lab.cli analyze ...
python3 -m valkey_scale_lab.cli report ...
```

Goal-loop stages may add subcommands, but existing commands must remain backward-compatible.

## Quantification contract

Every management and fault stage must emit these artifact families unless a stage-specific spec adds stricter requirements:

```text
artifacts/phases/<STAGE_ID>/phase_summary.json
artifacts/phases/<STAGE_ID>/valkey_e2e_evidence.json
artifacts/phases/<STAGE_ID>/cleanup_report.json
artifacts/phases/<STAGE_ID>/events.jsonl
artifacts/phases/<STAGE_ID>/metrics_timeseries.jsonl
artifacts/phases/<STAGE_ID>/workload_windows.json
artifacts/phases/<STAGE_ID>/quant_summary.json
```

Management stages must additionally emit a management operation matrix. Fault stages must additionally emit fault, failover, partition, split-brain, or workload-impact reports as specified in the current stage document.

## Implementation boundaries

The preferred runtime is Docker/container namespaces on Mac and Linux. Linux may use container-scoped `NET_ADMIN` inside owned containers for `tc netem`; Mac should use Docker Desktop Linux VM namespaces or a sandbox proxy fallback. Host-level network modification is forbidden.

The CLI, planner, metrics, report engine, and artifacts must be deterministic enough for regression comparison. Non-determinism such as timestamps, run IDs, and random seeds must be explicitly recorded.

`P14_SCALE_1000_OPTIN_DRYRUN` remains non-automatic. Do not run it unless the user explicitly opts in and sets the required environment variable.
