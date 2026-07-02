# CONTEXT_RELOAD - P20_FAILOVER_LATENCY_CURVE_30_50_100

## Stage identity

- Stage ID: P20_FAILOVER_LATENCY_CURVE_30_50_100
- Branch: codex/valkey-scale-lab-loop
- Date/time: 2026-07-02T17:54:09Z
- Current harness next output: P20_FAILOVER_LATENCY_CURVE_30_50_100
- Git status summary: clean
- Previous stage: P19_MANAGEMENT_ROLLING_RESTART committed and pushed as `e31650b`.

## Documents reread

| Document | Read? | Notes |
|---|---:|---|
| AGENTS.md | yes | Controlling goal-loop, safety, real-evidence, no-fake, resource-blocking, and multi-agent instructions. |
| CODEX_START_HERE.md | yes | Confirms current stage is determined by `codex_gate.py next` and the loop must continue through P26 unless blocked. |
| CODEX_GOAL_LOOP_START.md | yes | Confirms operator approvals and forbids host firewall/routing/interface mutation and 1000-node execution. |
| docs/codex/02_PHASES.md | yes | P20 requires real primary-stop failover curves for 30, 50, and 100 nodes. |
| docs/codex/04_AUDITOR.md | yes | Fresh-context audit must inspect gates, artifacts, schemas, and diffs. |
| docs/codex/goal-loop/00_INDEX.md | yes | Confirms required read order and stage artifact flow. |
| docs/codex/goal-loop/01_GOAL_CONTRACT.md | yes | P20 is part of the required fault/failover matrix and cannot be planning-only. |
| docs/codex/goal-loop/02_STAGE_MANIFEST.md | yes | P20 is automatic, real-Valkey, max 100 nodes, after P19. |
| docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md | yes | Requires design, worker, gate, review, postcheck, mark-complete, commit, push. |
| docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md | yes | Defines context reload, design brief, worker summary, review, completion, blocked, and journal handoffs. |
| docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md | yes | Failover curve assertion must require P20 rungs 30/50/100, sample counts, raw samples, timestamps, workload refs, and cleanup. |
| docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md | yes | Failover samples need fault/promotion/recovery/read/write timestamps and workload impact refs. |
| docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md | yes | P17-P19 management matrix complete; P20 must not drift back into management operations. |
| docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md | yes | P20 must produce at least three real primary-stop failover samples per rung for 30, 50, and 100 nodes. |
| docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md | yes | Resource preflight is mandatory; if any 30/50/100 rung lacks resources, P20 is blocked and must not pass with fake or downshifted values. |
| docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md | yes | Commit only after gate PASS, review PASS, postcheck, mark-complete, and intentional stage files. |
| docs/codex/goal-loop/stages/P20_FAILOVER_LATENCY_CURVE_30_50_100.md | yes | Authoritative P20 rows, artifacts, assertions, and review focus. |
| artifacts/goal_loop/STAGE_JOURNAL.md | yes | P19 handoff: P20 must produce real 30/50/100 primary-stop failover latency curves with resource preflight and at least three samples per rung. |

## Current stage contract summary

- Required implementation: produce real primary-stop failover latency curve samples for 30, 50, and 100 nodes, with at least three real samples per rung.
- Required behavior: resource preflight per rung; real cluster creation per rung; target primary selection; primary stop through project fault API or owned runtime controls; promotion detection from live cluster views; slot coverage recovery detection; first successful read/write recovery timestamps; workload QPS/latency/error windows; raw sample collection; curve derivation from raw samples; cleanup after every sample/rung.
- Required gates: precheck, safety static scan, script compile, unit/integration tests, goal-loop stage assertion, real `fault_failover_gate.py`, quant assertion, failover curve assertion, workload impact assertion, cleanup assertion, review/audit, postcheck, mark-complete.
- Required artifacts: `phase_summary.json`, `valkey_e2e_evidence.json`, `cleanup_report.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `quant_summary.json`, `failover_latency_samples.jsonl`, `failover_latency_curve.json`, `fault_matrix_report.json`, and `workload_impact_report.json`.
- Explicit non-goals: do not implement P21 200-node samples, P22 replica/host/AZ stops, P23 network delay/loss/flap, P24 partition/split-brain, P25 consolidation, or P26 reports; do not run 1000 nodes; do not mutate host networking.

## Risks and assumptions

- Safety risks: primary stop must target only owned containers/processes through project APIs or owned runtime controls; no host interface/firewall/routing changes are allowed.
- Resource risks: P20 requires real 30, 50, and 100 node clusters with at least three samples per rung; if Docker, memory, CPU, disk, port range, or runtime limits are insufficient, the stage is blocked rather than completed.
- `待验证` items: whether existing `fault_failover_gate.py` already supports multi-rung/multi-sample P20 artifacts; whether `scale_100.yaml` can be adapted to 30/50 rungs or sidecar sub-runs; whether existing failover schemas/assertions enforce all P20 sample fields; whether cleanup can safely run after each sample while preserving curve evidence; whether resource preflight data is already available or must be added.

## Handoff to design subagent

- Design prompt path: docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md
- Stage doc path: docs/codex/goal-loop/stages/P20_FAILOVER_LATENCY_CURVE_30_50_100.md
- Notes: Design must inspect `scripts/fault_failover_gate.py`, `scripts/assert_failover_latency_curve.py`, failover schemas, existing scale/runtime helpers, `src/valkey_scale_lab/runtime/docker_runtime.py`, `src/valkey_scale_lab/fault/`, and relevant tests. P20 must not be satisfied by fake samples, reusing one sample value, or downshifting 100 nodes.
