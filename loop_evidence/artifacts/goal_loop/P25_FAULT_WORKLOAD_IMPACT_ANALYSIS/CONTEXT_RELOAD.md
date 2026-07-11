# CONTEXT_RELOAD - P25_FAULT_WORKLOAD_IMPACT_ANALYSIS

## Stage identity

- Stage ID: P25_FAULT_WORKLOAD_IMPACT_ANALYSIS
- Branch: codex/valkey-scale-lab-loop
- Date/time: 2026-07-03 10:37:04 +0800
- Current harness next output: P25_FAULT_WORKLOAD_IMPACT_ANALYSIS
- Git status summary: clean after P24 commit/push

## Documents reread

| Document | Read? | Notes |
|---|---:|---|
| AGENTS.md | yes | Strict stage loop, real evidence, artifact-first reporting, and no host network mutation remain controlling. |
| CODEX_START_HERE.md | yes | Continue only the next incomplete automatic stage and use codex_gate sequence. |
| CODEX_GOAL_LOOP_START.md | yes | User requires fault-period workload QPS/latency/error impact across the matrix. |
| docs/codex/02_PHASES.md | yes | Analysis/reporting phases must consume real artifacts and avoid invented metrics. |
| docs/codex/04_AUDITOR.md | yes | Fresh-context review/audit must inspect gates, artifacts, schemas, and source diffs. |
| docs/codex/goal-loop/00_INDEX.md | yes | Required read order and Markdown handoff artifacts. |
| docs/codex/goal-loop/01_GOAL_CONTRACT.md | yes | Completion requires all automatic stages through P26, each with review PASS, mark-complete, commit, and push. |
| docs/codex/goal-loop/02_STAGE_MANIFEST.md | yes | P25 is automatic, real-Valkey required, max 100, and depends on P24. |
| docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md | yes | Must run design, worker, and review subagents; close each after use. |
| docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md | yes | This reload precedes design and must persist stage context. |
| docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md | yes | P25 must fail closed on missing malformed or fabricated workload impact data. |
| docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md | yes | Metrics must preserve window semantics and missing-data reasons. |
| docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md | yes | P25 must include management-stage workload impact where artifacts exist. |
| docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md | yes | P25 consolidates fault workload impact comparisons across earlier fault stages. |
| docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md | yes | Do not rerun large scale unless required; P25 should consume existing artifacts. |
| docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md | yes | No commit until gates, review PASS, postcheck, and mark-complete pass. |
| docs/codex/goal-loop/stages/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS.md | yes | Stage requires cross-stage JSON, CSV exports, missing-data summary, and quant summary. |
| artifacts/goal_loop/STAGE_JOURNAL.md | yes | P24 handoff says preserve per-sample workload/error taxonomy and consolidate P20-P24. |

## Current stage contract summary

- Required implementation: read existing artifacts from P17-P24 only, consolidate management and fault workload impact into comparable QPS, latency p50/p95/p99, error-rate, and recovery-duration tables, and export report-ready CSV files.
- Required source coverage: P17, P18, P19 management workload impact artifacts; P20 and P21 failover curve workload impact artifacts; P22, P23, and P24 fault workload impact artifacts. Missing source stages or rows must be represented as `MISSING` or `SKIPPED_WITH_REASON` with reasons rather than omitted.
- Required artifacts: `workload_impact_cross_stage.json`, `workload_impact_by_operation.csv`, `workload_impact_by_fault.csv`, `latency_delta_table.csv`, `error_delta_table.csv`, `recovery_duration_table.csv`, `missing_data_summary.json`, `quant_summary.json`, plus common real-stage artifacts required by the manifest.
- Required gates: manifest precheck, safety scan, compile, unit/integration tests, goal-loop assertion, P25 real Valkey smoke gate, quant artifact assertion, workload impact assertion, cleanup assertion, fresh-context review, postcheck, and mark-complete.
- Explicit non-goals: do not rerun P17-P24 scenarios to create new source data; do not hand-write report numbers; do not parse logs when JSON/JSONL artifacts are available; do not implement P26 final reports/regression baselines in P25.

## Risks and assumptions

- P25 is real-Valkey required by manifest even though its primary output is analysis; the stage must preserve or generate the common real-stage evidence/cleanup artifacts through the manifest smoke gate.
- Existing P17-P24 artifact shapes vary between management, failover, and fault stages; the design must identify canonical extraction paths and strict cross-reference checks.
- CSV rows must match JSON source counts exactly; derived numbers must cite source artifact paths and sample/window IDs.
- Missing data must be explicit and reasoned, especially for source rows whose workload windows are absent or whose metric fields are `MISSING`.

## Handoff to design subagent

- Design prompt path: docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md
- Stage doc path: docs/codex/goal-loop/stages/P25_FAULT_WORKLOAD_IMPACT_ANALYSIS.md
- Notes: Focus design on artifact-derived aggregation, schema/assertion strengthening, CSV-to-JSON count checks, source traceability, and preserving P24's corrected error taxonomy.
