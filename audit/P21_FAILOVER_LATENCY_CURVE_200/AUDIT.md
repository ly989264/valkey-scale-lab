# Audit - P21_FAILOVER_LATENCY_CURVE_200

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-07-03T00:18:27Z

Gate Result: artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/gate_result.json
Observed Gate Result SHA256: 1166763b682bed67750d2b147259d3c7ed24bcdf32f082e64450bf481f4d4dca

## Scope inspected

- `AGENTS.md`
- `CODEX_START_HERE.md`
- `CODEX_GOAL_LOOP_START.md`
- `codex/phase_manifest.json`
- `docs/codex/02_PHASES.md`
- `docs/codex/04_AUDITOR.md`
- `docs/codex/goal-loop/00_INDEX.md` through `10_AUDIT_AND_COMMIT_POLICY.md`
- `docs/codex/goal-loop/stages/P21_FAILOVER_LATENCY_CURVE_200.md`
- phase source changes
- gate result and logs
- required artifacts
- schema validation output
- cleanup evidence
- real Valkey evidence

## Gate findings

All manifest command texts match `gate_result.json`. All stdout/stderr paths exist and their SHA256 values match the gate result.

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| harness_precheck | PASS | PASS | `artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/stdout/harness_precheck.log` |
| safety_static_scan | PASS | PASS | `artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/stdout/safety_static_scan.log` |
| scripts_compile | PASS | PASS | `artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/stdout/scripts_compile.log` |
| unit_integration_tests | PASS | PASS | `artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/stdout/unit_integration_tests.log` |
| goal_loop_stage_assertion | PASS | PASS | `artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/stdout/goal_loop_stage_assertion.log` |
| real_failover_gate | PASS | PASS | `artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/stdout/real_failover_gate.log` |
| quant_artifact_assertion | PASS | PASS | `artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/stdout/quant_artifact_assertion.log` |
| failover_curve_assertion | PASS | PASS | `artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/stdout/failover_curve_assertion.log` |
| workload_impact_assertion | PASS | PASS | `artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/stdout/workload_impact_assertion.log` |
| cleanup_report_check | PASS | PASS | `artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/stdout/cleanup_report_check.log` |

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/phase_summary.json` | `schemas/artifact/phase_summary.schema.json` | valid | schema validator PASS |
| `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/valkey_e2e_evidence.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | valid | schema validator PASS |
| `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/cleanup_report.json` | `schemas/artifact/cleanup_report.schema.json` | valid | schema validator PASS |
| `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/events.jsonl` | `schemas/artifact/goal_loop_event.schema.json` | valid | schema validator PASS |
| `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/metrics_timeseries.jsonl` | `schemas/artifact/goal_loop_metric_sample.schema.json` | valid | schema validator PASS |
| `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/workload_windows.json` | `schemas/artifact/workload_windows.schema.json` | valid | schema validator PASS |
| `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/quant_summary.json` | `schemas/artifact/quant_summary.schema.json` | valid | schema validator PASS |
| `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/resource_preflight_200.json` | `schemas/artifact/resource_preflight.schema.json` | valid | schema validator PASS |
| `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/failover_latency_samples_200.jsonl` | `schemas/artifact/failover_latency_sample.schema.json` | valid | schema validator PASS |
| `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/failover_latency_curve_200.json` | `schemas/artifact/failover_latency_curve.schema.json` | valid | schema validator PASS |
| `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/failover_latency_curve_combined_30_50_100_200.json` | `schemas/artifact/failover_latency_curve.schema.json` | valid | schema validator PASS |
| `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/workload_impact_report.json` | `schemas/artifact/workload_impact_report.schema.json` | valid | schema validator PASS |

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: verified
- Default node cap <= 100: verified

## Real Valkey findings

Required for this phase: YES
Evidence file: `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/valkey_e2e_evidence.json`
Valkey version observed: `9.1.0`
Independent live probe: PASS

The top-level evidence records 200 observed nodes, three sample refs, `real_valkey: true`, `cluster_state_observed: ok`, and `data_path_result: PASS`. Raw samples are exactly the three 200-node P21 sample IDs and include promotion, slot coverage, read/write recovery, workload impact refs, and cleanup PASS.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| Large local Docker failover runs depend on host resources. | medium | no | P21 preflight passed for this run and artifacts preserve host/resource details. |
| Cleanup needed retries for transient Docker process termination timeouts. | low | no | Retry provenance is recorded in nested cleanup reports; final resources remaining are empty. |

## Final rationale

All P21 manifest gates passed with exact command-text and log-hash integrity. Required artifacts exist and schema-validate. The evidence proves real Valkey 9.1.0 execution for exactly three 200-node failover sample rows, extends the combined curve to 30/50/100/200, records workload impact and quant telemetry, and verifies cleanup with no owned resources remaining. Safety constraints remain intact: no host network/firewall/routing/interface mutation, no sudo network path, P14 remains non-automatic, and the default max remains 100 outside the bounded P21 exception.
