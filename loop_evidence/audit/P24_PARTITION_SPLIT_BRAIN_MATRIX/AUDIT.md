# Audit — P24_PARTITION_SPLIT_BRAIN_MATRIX

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-07-03T02:50:00Z

Gate Result: artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/gate_result.json
Observed Gate Result SHA256: 7fd78fd050569defed629680a526fb927c3246dfe0539128f69c7109b20ca430

## Scope inspected

- `codex/phase_manifest.json`
- `docs/codex/02_PHASES.md`
- phase source changes
- gate result and logs
- required artifacts
- schema validation output
- cleanup evidence
- real Valkey evidence, if required
- P24 goal-loop handoff artifacts and stage document
- `artifacts/goal_loop/P24_PARTITION_SPLIT_BRAIN_MATRIX/REVIEW.md`
- `artifacts/goal_loop/P24_PARTITION_SPLIT_BRAIN_MATRIX/FIX_LOG.md`

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| harness_precheck | PASS | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/harness_precheck.log` |
| safety_static_scan | PASS | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/safety_static_scan.log` |
| scripts_compile | PASS | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/scripts_compile.log` |
| unit_integration_tests | PASS | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/unit_integration_tests.log` |
| goal_loop_stage_assertion | PASS | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/goal_loop_stage_assertion.log` |
| real_fault_safety_gate | PASS | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/real_fault_safety_gate.log` |
| quant_artifact_assertion | PASS | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/quant_artifact_assertion.log` |
| fault_matrix_assertion | PASS | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/fault_matrix_assertion.log` |
| split_brain_assertion | PASS | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/split_brain_assertion.log` |
| workload_impact_assertion | PASS | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/workload_impact_assertion.log` |
| cleanup_report_check | PASS | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/cleanup_report_check.log` |

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/phase_summary.json` | `schemas/artifact/phase_summary.schema.json` | valid | gate and quant assertion |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/valkey_e2e_evidence.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | valid | real Valkey evidence |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/cleanup_report.json` | `schemas/artifact/cleanup_report.schema.json` | valid | cleanup assertion |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/events.jsonl` | `schemas/artifact/goal_loop_event.schema.json` | valid | JSONL schema validation |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/metrics_timeseries.jsonl` | `schemas/artifact/goal_loop_metric_sample.schema.json` | valid | JSONL schema validation |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/workload_windows.json` | `schemas/artifact/workload_windows.schema.json` | valid | workload assertion |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/quant_summary.json` | `schemas/artifact/quant_summary.schema.json` | valid | quant assertion |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/partition_report.json` | `schemas/artifact/partition_report.schema.json` | valid | P24 semantic assertion |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/split_brain_report.json` | `schemas/artifact/split_brain_report.schema.json` | valid | split-brain assertion |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/fault_results.jsonl` | `schemas/artifact/fault_result.schema.json` | valid | fault matrix assertion |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/fault_topology_snapshots.jsonl` | P24 quant cross-check | valid | quant assertion |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/workload_impact_report.json` | `schemas/artifact/workload_impact_report.schema.json` | valid | workload assertion |

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: verified
- Default node cap <= 100: verified

P24 uses `owned_docker_network_control` through Docker network disconnect/connect on owned, run-labeled nodehost containers and owned stage networks only.

## Real Valkey findings

Required for this phase: YES
Evidence file: `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/valkey_e2e_evidence.json`
Valkey version observed: 9.1.0
Independent live probe: PASS

The evidence reports `real_valkey=true`, `nodes_observed=10`, `cluster_state_observed=ok`, and `data_path_result=PASS`. P24 fault artifacts contain six PASS rows for `network_partition_minority`, `network_partition_majority`, and `split_brain_window_detection` at 6 and 10 nodes.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| P24 uses owned Docker network disconnect/reconnect of nodehost containers rather than container `tc`. | medium | no | Accepted because the scope is owned Docker resources only and command logs prove no host/global mutation. |
| `old_primary_accepts_write_after_promotion` is not run in P24. | low | no | It is encoded as `MISSING` with reason because P24 does not inject a primary-stop promotion condition. |

## Final rationale

P24 satisfies the stage contract with schema-valid artifacts, matching PASS gates, real Valkey 9.1.0 evidence, six required partition/split-brain rows at 6 and 10 nodes, explicit partition groups, detector-backed split-brain reporting, corrected workload error taxonomy and all-run latency aggregation, safe owned Docker network controls, and cleanup evidence showing no remaining owned resources.
