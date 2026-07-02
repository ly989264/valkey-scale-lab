# Audit — P20_FAILOVER_LATENCY_CURVE_30_50_100

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-07-02T18:58:49Z

Gate Result: artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/gate_result.json
Observed Gate Result SHA256: 06c86ab895b8f3a2810bb7d2506f4067941c17499ebfbaff4f5b4421376a7ccd

## Scope inspected

- `AGENTS.md`
- `codex/phase_manifest.json`
- `docs/codex/02_PHASES.md`
- `docs/codex/04_AUDITOR.md`
- `docs/codex/goal-loop/stages/P20_FAILOVER_LATENCY_CURVE_30_50_100.md`
- `artifacts/goal_loop/P20_FAILOVER_LATENCY_CURVE_30_50_100/CONTEXT_RELOAD.md`
- `artifacts/goal_loop/P20_FAILOVER_LATENCY_CURVE_30_50_100/DESIGN_BRIEF.md`
- `artifacts/goal_loop/P20_FAILOVER_LATENCY_CURVE_30_50_100/WORKER_SUMMARY.md`
- `artifacts/goal_loop/P20_FAILOVER_LATENCY_CURVE_30_50_100/COMPLETION.md`
- phase source changes and tests
- gate result and logs
- required artifacts
- schema validation output
- cleanup evidence
- real Valkey evidence

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| harness_precheck | PASS | PASS | `artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/stdout/harness_precheck.log` |
| safety_static_scan | PASS | PASS | `artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/stdout/safety_static_scan.log` |
| scripts_compile | PASS | PASS | `artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/stdout/scripts_compile.log` |
| unit_integration_tests | PASS | PASS | `artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/stdout/unit_integration_tests.log` |
| goal_loop_stage_assertion | PASS | PASS | `artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/stdout/goal_loop_stage_assertion.log` |
| real_failover_gate | PASS | PASS | `artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/stdout/real_failover_gate.log` |
| quant_artifact_assertion | PASS | PASS | `artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/stdout/quant_artifact_assertion.log` |
| failover_curve_assertion | PASS | PASS | `artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/stdout/failover_curve_assertion.log` |
| workload_impact_assertion | PASS | PASS | `artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/stdout/workload_impact_assertion.log` |
| cleanup_report_check | PASS | PASS | `artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/stdout/cleanup_report_check.log` |

The ten observed commands exactly match the manifest commands. All recorded stdout/stderr files exist and match the SHA256 values in `gate_result.json`.

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/phase_summary.json` | `schemas/artifact/phase_summary.schema.json` | valid | SHA256 `081f9bffa18e5824236bf890aabaf0e103215fa5c70e3d4489d20ccd831726c2` |
| `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/valkey_e2e_evidence.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | valid | SHA256 `3cda9dcd65fafb1b9b04e375b9629385c13b77fd7fc8f8bde673f697aea7a6d4` |
| `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/cleanup_report.json` | `schemas/artifact/cleanup_report.schema.json` | valid | SHA256 `0d0a6a4eebb37e0f0b50f6a1a4a2c1679e82cdfafa127f46403dc813e4ebaa00` |
| `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/events.jsonl` | `schemas/artifact/goal_loop_event.schema.json` | valid | SHA256 `cea852c4d81c44f8abe8d29d4c8d783ac9727c855e6e87212253285c38b5f8e8` |
| `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/metrics_timeseries.jsonl` | `schemas/artifact/goal_loop_metric_sample.schema.json` | valid | SHA256 `c0143a9909174c592c82a70cc6b48c214cb0352413ae193d1b59a2704d9b67dd` |
| `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/workload_windows.json` | `schemas/artifact/workload_windows.schema.json` | valid | SHA256 `3a95e34263798c89aa7b542b61dccecd4af8f9ca5342e62e4ed2cc29496eb080` |
| `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/quant_summary.json` | `schemas/artifact/quant_summary.schema.json` | valid | SHA256 `5be21b53ff9846a2ddce4ebb95a6d737e0a923ccdd0b07615e07a341d05e4f1a` |
| `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/failover_latency_samples.jsonl` | `schemas/artifact/failover_latency_sample.schema.json` | valid | SHA256 `0f5533b1ca9c25c546712adf08adfc6ad765f59987454856c5d7c9c473c96063` |
| `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/failover_latency_curve.json` | `schemas/artifact/failover_latency_curve.schema.json` | valid | SHA256 `7e6d459beb96587f54bf92f3802a169cf694605f8499efa73098c612b947f1a7` |
| `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/fault_matrix_report.json` | `schemas/artifact/fault_matrix_report.schema.json` | valid | SHA256 `b6d1f89b3de252cb15dc2a0c2c9a7c3b718618450f299640523053822eb315cc` |
| `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/workload_impact_report.json` | `schemas/artifact/workload_impact_report.schema.json` | valid | SHA256 `b8d5c6360ad1d44d79678d5c2cd01f3e32baf249443bd9ca5242e148a90d1cf8` |

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: verified
- Default node cap <= 100: verified

## Real Valkey findings

Required for this phase: YES
Evidence file: `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/valkey_e2e_evidence.json`
Valkey version observed: `9.1.0`
Independent live probe: PASS

Per-sample evidence files prove exact rungs 30, 50, and 100 with three samples each. Each sample has live probe PASS, data-path PASS, Valkey `9.1.0`, exact `cluster_known_nodes`, live cluster-node observations, and cleanup PASS.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| Large local Docker failover runs depend on host resources. | medium | no | Resource preflights passed for P20; P21 has separate 200-node preflight requirements. |

## Final rationale

The stale contradictory `BLOCKED.md` is absent. All manifest gates ran and passed with matching command text and log hashes. Required artifacts exist, validate against schema, and pass P20 semantic assertions. The failover curve has exact 30/50/100 rungs with three real Valkey `9.1.0` samples per rung, derived curve values, workload impact references, safety-scoped primary-stop faults, and cleanup evidence with no owned leftovers.
