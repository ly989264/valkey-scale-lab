# CONTEXT_RELOAD - P22_FAULT_REPLICA_HOST_AZ_STOP

## Stage identity

- Stage ID: P22_FAULT_REPLICA_HOST_AZ_STOP
- Branch: codex/valkey-scale-lab-loop
- Date/time: 2026-07-03T00:24:43Z
- Current harness next output: P22_FAULT_REPLICA_HOST_AZ_STOP
- Git status summary: clean after pushed commit `a648f82 P21_FAILOVER_LATENCY_CURVE_200: add real 200-node failover curve`

## Documents reread

| Document | Read? | Notes |
|---|---:|---|
| AGENTS.md | yes | Strong stage loop, safety rules, bounded P21 exception only. |
| CODEX_START_HERE.md | yes | Continue automatic stages through P26; no fake PASS. |
| CODEX_GOAL_LOOP_START.md | yes | Goal-mode scope and operator approval boundaries. |
| docs/codex/02_PHASES.md | yes | Legacy phase intent and real gate expectations. |
| docs/codex/04_AUDITOR.md | yes | Fresh-context review/audit requirements. |
| docs/codex/goal-loop/00_INDEX.md | yes | Required read order and stage doc authority. |
| docs/codex/goal-loop/01_GOAL_CONTRACT.md | yes | P22 is part of fault matrix completion; blocked stages cannot be marked complete. |
| docs/codex/goal-loop/02_STAGE_MANIFEST.md | yes | P22 is automatic, real Valkey required, max 100 nodes. |
| docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md | yes | Design, worker, and review subagents are mandatory. |
| docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md | yes | Requires context, design, worker, review, completion artifacts. |
| docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md | yes | Assertions must fail closed and cleanup must be verified. |
| docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md | yes | Requires canonical events, metrics, workload windows, and missing-data reasons. |
| docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md | yes | P22 must not change management semantics. |
| docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md | yes | Defines replica_stop, node_host_stop, AZ stop, workload impact, and safety evidence. |
| docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md | yes | P22 remains capped at 100; 30+ evidence is conditional on resource preflight. |
| docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md | yes | Review PASS, postcheck, mark-complete, commit, and push are required in order. |
| docs/codex/goal-loop/stages/P22_FAULT_REPLICA_HOST_AZ_STOP.md | yes | Current stage contract. |
| artifacts/goal_loop/STAGE_JOURNAL.md | yes | P21 handoff says P22 must implement replica, node-host, and virtual AZ stop without widening caps. |

## Current stage contract summary

- Required implementation:
  - Implement and quantify `replica_stop`, `node_host_stop`, and `az_stop`.
  - Select targets from the cluster plan/topology, not physical host state.
  - Stop and restore targets only through project-owned runtime or fault APIs.
  - Record per-target topology/role impact, recovery timing, workload windows, events, metrics, and cleanup.
  - Include real 6/10-node evidence at minimum and at least one 30+ row if resource preflight passes; manifest limits P22 to 100 nodes.
- Required gates:
  - `python3 scripts/codex_gate.py precheck --phase P22_FAULT_REPLICA_HOST_AZ_STOP`
  - `python3 scripts/codex_gate.py run --phase P22_FAULT_REPLICA_HOST_AZ_STOP`
  - Stage-specific fault matrix, workload impact, quant, and cleanup assertions from the manifest.
  - Fresh-context review/audit, postcheck, mark-complete, commit, push.
- Required artifacts:
  - Common real-stage artifacts: `phase_summary.json`, `valkey_e2e_evidence.json`, `cleanup_report.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `quant_summary.json`.
  - P22 artifacts: `fault_matrix_report.json`, `fault_results.jsonl`, `fault_topology_snapshots.jsonl`, `workload_impact_report.json`.
- Explicit non-goals:
  - No host network, firewall, route, interface, or OS service mutation.
  - No physical host or real AZ stop; logical node-host and virtual AZ only.
  - No 200-node or 1000-node default widening.
  - No fake-only PASS evidence or static rows.

## Risks and assumptions

- Safety risks:
  - Node-host and AZ names could be mistaken for physical host/AZ controls; implementation must keep them as logical plan groupings over owned containers/processes.
  - Replica stop must not report promotion as success unless an unexpected promotion is recorded as impact.
- Resource risks:
  - P22 can require 30+ real evidence if resource preflight passes; otherwise it must record the reason rather than downscope silently.
  - Large fault rows must preserve deterministic cleanup after grouped stops.
- `待验证` items:
  - Existing `fault` API restore behavior for grouped process/container stops.
  - Whether current assertions already know P22 rows or need strengthening.
  - Whether an existing config can safely produce 30-node P22 evidence or a new bounded config is required.

## Handoff to design subagent

- Design prompt path: `docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md`
- Stage doc path: `docs/codex/goal-loop/stages/P22_FAULT_REPLICA_HOST_AZ_STOP.md`
- Notes:
  - Read P20/P21 failover controller patterns for artifact aggregation and cleanup handling.
  - Prefer reusing existing topology placement fields: `logical_id`, `role`, `host_id`, `nodehost_id`, and `az_id`.
  - Keep P22 scoped to replica, logical host, and virtual AZ stop faults only.
