# CONTEXT_RELOAD - P26_FINAL_REPORT_REGRESSION

## Stage identity

- Stage ID: P26_FINAL_REPORT_REGRESSION
- Branch: codex/valkey-scale-lab-loop
- Date/time: 2026-07-03 11:11:16 +0800
- Current harness next output: P26_FINAL_REPORT_REGRESSION
- Git status summary: clean after P25 commit `321c673` was pushed; branch synchronized with `origin/codex/valkey-scale-lab-loop`

## Documents reread

| Document | Read? | Notes |
|---|---:|---|
| AGENTS.md | yes | Strict stage loop remains controlling; P26 still requires real evidence, review PASS, postcheck, mark-complete, commit, and push. |
| CODEX_START_HERE.md | yes | Continue only the next incomplete automatic stage returned by the harness. |
| CODEX_GOAL_LOOP_START.md | yes | Final output must close the management, fault/failover, and quantitative evidence loop under the strong harness. |
| docs/codex/02_PHASES.md | yes | P26 must generate final reports, curves, tables, exports, and regression checks from versioned artifacts. |
| docs/codex/04_AUDITOR.md | yes | Fresh-context review/audit must inspect gate results, required artifacts, schemas, source diffs, and P26 handoff artifacts. |
| docs/codex/goal-loop/00_INDEX.md | yes | Required read order and template-backed Markdown handoffs remain mandatory. |
| docs/codex/goal-loop/01_GOAL_CONTRACT.md | yes | Goal completion requires all automatic stages through P26 to pass gates, review, mark-complete, commit, and push. |
| docs/codex/goal-loop/02_STAGE_MANIFEST.md | yes | P26 is automatic, real-Valkey required, max 100, and the final automatic stage. |
| docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md | yes | Must use design, worker, and review subagents; worker must not commit. |
| docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md | yes | This reload must precede the design subagent and survive context compaction. |
| docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md | yes | Final checks must fail closed on missing rows, malformed artifacts, fake evidence, or fabricated metrics. |
| docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md | yes | Reports/CSVs/Markdown must derive from JSON/JSONL artifacts and render missing data explicitly. |
| docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md | yes | Final management report must cover required create/meet/add/remove/reshard/rebalance/restart rows. |
| docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md | yes | Final fault report must cover failover, replica/host/AZ, network, partition, split-brain, and workload-impact rows. |
| docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md | yes | P14 remains non-automatic and 1000-node execution stays opt-in; P21's 200-node data remains bounded evidence only. |
| docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md | yes | No P26 commit until gates, review PASS, postcheck, and mark-complete pass. |
| docs/codex/goal-loop/stages/P26_FINAL_REPORT_REGRESSION.md | yes | Requires report index, Markdown reports, CSV exports, quant summary, and regression hardening. |
| artifacts/goal_loop/STAGE_JOURNAL.md | yes | P25 handoff says generate final reports and baselines from P17-P25 artifacts without parsing logs or inventing missing values. |

## Current stage contract summary

- Required implementation: build final machine-readable and human-readable reports from prior artifacts, including management matrix, failover latency curve, fault matrix, workload impact, final goal-loop report, report index, CSV exports, regression fixtures or golden summaries, and local loop documentation.
- Required source coverage: management rows from P16-P19; failover curve rows from P20-P21; fault matrix rows from P22-P24; workload impact rows from P25; real current-stage smoke evidence and cleanup through the manifest gate.
- Required gates: manifest precheck, safety scan, compile, unit/integration tests, goal-loop assertion, real Valkey e2e smoke, final report/regression assertion, quant artifact assertion, cleanup assertion, fresh-context review, postcheck, and mark-complete.
- Required artifacts: `report_index.json`, `reports/management_ops_matrix.md`, `reports/failover_latency_curve.md`, `reports/fault_matrix.md`, `reports/workload_impact.md`, `reports/final_goal_loop_report.md`, `exports/management_ops_matrix.csv`, `exports/failover_latency_curve.csv`, `exports/fault_matrix.csv`, `exports/workload_impact.csv`, `quant_summary.json`, plus common real-stage artifacts.
- Explicit non-goals: do not rerun P17-P25 source scenarios to manufacture report data; do not parse logs for report numbers when JSON/JSONL artifacts exist; do not implement P14 or run 1000 nodes; do not mutate host networking/firewall/routing; do not combine P26 with any future stage because P26 is the final automatic stage.

## Risks and assumptions

- Safety risks: P26 should be mostly artifact/report generation; the only runtime side effect should be the bounded real-Valkey smoke gate and deterministic cleanup.
- Resource risks: P26 should not require 30/50/100/200-node reruns; it should consume already committed stage artifacts.
- `待验证` items: exact P26 manifest gate names and required-artifact schema paths; whether existing report package can be extended or a new final-report builder is cleaner; whether final assertions already exist or must be added/strengthened; whether `report_index.json` schema exists and is strict enough for P26.

## Handoff to design subagent

- Design prompt path: docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md
- Stage doc path: docs/codex/goal-loop/stages/P26_FINAL_REPORT_REGRESSION.md
- Notes: Focus design on artifact-only derivation, full row coverage regression checks, final report index schema, CSV/Markdown provenance, P14 opt-in preservation, and final automatic-loop completion evidence.
