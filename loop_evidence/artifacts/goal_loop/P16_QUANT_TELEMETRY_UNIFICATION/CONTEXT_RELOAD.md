# CONTEXT_RELOAD — P16_QUANT_TELEMETRY_UNIFICATION

## Stage identity

- Stage ID: P16_QUANT_TELEMETRY_UNIFICATION
- Branch: codex/valkey-scale-lab-loop
- Date/time: 2026-07-02T15:59:33Z
- Current harness next output: `P16_QUANT_TELEMETRY_UNIFICATION`
- Git status summary: clean worktree, branch synced with `origin/codex/valkey-scale-lab-loop`
- Current stage reason: `codex/status/phase_state.json` includes `P15_GOAL_REBASE_HARNESS_EXTENSION`; `python3 scripts/codex_gate.py next` returns P16.

## Documents reread

| Document | Read? | Notes |
|---|---:|---|
| AGENTS.md | yes | Goal-loop mission, safety rules, required stage reload, subagent loop. |
| CODEX_START_HERE.md | yes | Execute next incomplete automatic stage; no manual pass results. |
| CODEX_GOAL_LOOP_START.md | yes | User-required management/fault/quantification coverage and allowed approvals. |
| docs/codex/02_PHASES.md | yes | P16 summary and existing P00-P15 context. |
| docs/codex/04_AUDITOR.md | yes | P15-P26 review plus legacy audit outputs required. |
| docs/codex/goal-loop/00_INDEX.md | yes | Required read order and stage doc requirement. |
| docs/codex/goal-loop/01_GOAL_CONTRACT.md | yes | P16 must leave runnable code, validated artifacts, real evidence, and review. |
| docs/codex/goal-loop/02_STAGE_MANIFEST.md | yes | P16 is real-Valkey, max 6 nodes, common real artifacts required. |
| docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md | yes | Design, worker, gate, review, postcheck, mark-complete, commit/push sequence. |
| docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md | yes | Required Markdown handoff artifacts and stage journal. |
| docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md | yes | Real gates must independently verify Valkey 9.1.x, endpoints, topology, data path, cleanup. |
| docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md | yes | Canonical event, metric, workload-window, missing-data, report derivation rules. |
| docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md | yes | P16 setup evidence can serve create/meet/add-replica baseline for management matrix. |
| docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md | yes | Future fault stages depend on P16 workload window and event/metric model. |
| docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md | yes | P16 stays at 6 nodes; no 30+ resource preflight requirement yet. |
| docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md | yes | Review, postcheck, mark-complete, commit, push required before P17. |
| docs/codex/goal-loop/stages/P16_QUANT_TELEMETRY_UNIFICATION.md | yes | Current stage objective and real 6-node telemetry smoke requirements. |
| artifacts/goal_loop/STAGE_JOURNAL.md | yes | P15 handoff: keep no-fake-evidence harness guarantees intact. |

## Current stage contract summary

- Required implementation: canonical metric sample writer, event writer, workload window aggregator, quant summary generator, missing-data helpers, JSON/JSONL schema validation path, telemetry integration for `gate scenario`, and a real 6-node telemetry smoke scenario.
- Required real scenario: start a 6-node Valkey cluster, run low-QPS workload, sample `INFO`, `CLUSTER INFO`, and `CLUSTER NODES`, emit workload window metrics, independently verify Valkey endpoints, and clean up.
- Required artifacts: `phase_summary.json`, `valkey_e2e_evidence.json`, `cleanup_report.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, and `quant_summary.json` under `artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/`.
- Required assertions: JSONL line-by-line validation, at least one Valkey INFO sample per live node, at least one workload window with non-zero sample count, missing values encoded with reasons, cleanup no owned leftovers.
- Explicit non-goals: do not implement remove/reshard/rebalance/rolling restart, failover curves, network faults, partitions, split-brain, 200-node execution, or 1000-node execution in P16.

## Risks and assumptions

- Safety risks: P16 must use existing owned Docker/container runtime paths only; no host network/firewall/routing changes.
- Resource risks: P16 requires real Docker/Valkey at 6 nodes. If Docker or real Valkey gates cannot run, write `BLOCKED.md` with evidence and do not mark complete.
- `待验证` items: existing `valkey_e2e_gate.py` telemetry scenario coverage, current runtime output shape for metrics/workload windows, whether P15 schemas are strict enough for P16 artifacts, and whether current workload engine can produce all required windows without future management/fault logic.

## Handoff to design subagent

- Design prompt path: `docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md`
- Stage doc path: `docs/codex/goal-loop/stages/P16_QUANT_TELEMETRY_UNIFICATION.md`
- Notes: design must inspect current metrics, workload, runtime, artifact, CLI, and e2e gate implementation and propose the minimum shared telemetry interfaces needed for later stages.
