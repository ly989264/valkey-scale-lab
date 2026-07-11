# CONTEXT_RELOAD - P21_FAILOVER_LATENCY_CURVE_200

## Stage identity

- Stage ID: P21_FAILOVER_LATENCY_CURVE_200
- Branch: codex/valkey-scale-lab-loop
- Current harness next output: P21_FAILOVER_LATENCY_CURVE_200
- Previous stage: P20_FAILOVER_LATENCY_CURVE_30_50_100 committed and pushed as `12cbb38`.
- Git status summary at reload: clean.

## Documents reread

- AGENTS.md: yes; controlling strict phase loop, safety rules, no fake evidence, and resource-blocking rules.
- CODEX_START_HERE.md: yes; confirms the next incomplete automatic stage must be implemented and the loop continues through P26 unless blocked.
- CODEX_GOAL_LOOP_START.md: yes; confirms user-required 200-node failover data and operator approval boundaries.
- docs/codex/goal-loop/00_INDEX.md: yes; confirms required document flow.
- docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md: yes; confirms design, worker, gate, review, postcheck, mark-complete, commit, push sequence.
- docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md: yes; confirms P21 is a bounded 200-node exception with strict preflight.
- docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md: yes; confirms blocked-stage handling and commit requirements.
- docs/codex/goal-loop/stages/P21_FAILOVER_LATENCY_CURVE_200.md: yes; confirms exact P21 objective and artifacts.
- codex/phase_manifest.json: yes; P21 gates and required artifacts inspected.

## Stage contract summary

- Run real Valkey primary-stop failover latency samples at exactly 200 nodes.
- Produce at least three real samples for the 200-node rung.
- Run strict `resource_preflight_200.json` before execution.
- Use a low but non-zero workload profile if needed for resource safety.
- Measure promotion, slot coverage, read recovery, write recovery, workload impact, and cleanup.
- Produce `failover_latency_samples_200.jsonl`, `failover_latency_curve_200.json`, and combined `failover_latency_curve_combined_30_50_100_200.json`.
- Do not substitute 100-node evidence, dry-run output, or fake Valkey.
- If Docker or resources cannot support 200 nodes, write `artifacts/goal_loop/P21_FAILOVER_LATENCY_CURVE_200/BLOCKED.md`, leave P21 incomplete, and stop.

## Required artifacts

- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/phase_summary.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/valkey_e2e_evidence.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/cleanup_report.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/events.jsonl`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/metrics_timeseries.jsonl`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/workload_windows.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/quant_summary.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/resource_preflight_200.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/failover_latency_samples_200.jsonl`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/failover_latency_curve_200.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/failover_latency_curve_combined_30_50_100_200.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/workload_impact_report.json`

## Risks and assumptions

- P21 may be resource-blocked on a local Mac/Linux Docker host; that is an allowed blocking outcome, not a failure to hide.
- The current P20 controller may provide reusable aggregation patterns, but P21 must enforce exact 200-node samples and combined curve semantics.
- P14 must remain non-automatic and no 1000-node path may be activated.
- Host firewall, routing, interface, PF, nftables, iptables, and sudo network changes remain forbidden.
