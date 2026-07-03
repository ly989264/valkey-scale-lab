# Audit — P22_FAULT_REPLICA_HOST_AZ_STOP

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-07-03T00:58:27.013958Z

Gate Result: artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/gate_result.json
Observed Gate Result SHA256: c99e7cd8762e248f14fd5acc8866ac1447f5ac50454954b75967ae2cf8a766ce

## Scope inspected

- `codex/phase_manifest.json`
- `docs/codex/02_PHASES.md`
- phase source changes
- gate result and logs
- required artifacts
- schema validation output
- cleanup evidence
- real Valkey evidence, if required

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| harness_precheck | PASS | PASS | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/harness_precheck.log` |
| safety_static_scan | PASS | PASS | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/safety_static_scan.log` |
| scripts_compile | PASS | PASS | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/scripts_compile.log` |
| unit_integration_tests | PASS | PASS | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/unit_integration_tests.log` |
| goal_loop_stage_assertion | PASS | PASS | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/goal_loop_stage_assertion.log` |
| real_fault_safety_gate | PASS | PASS | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/real_fault_safety_gate.log` |
| quant_artifact_assertion | PASS | PASS | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/quant_artifact_assertion.log` |
| fault_matrix_assertion | PASS | PASS | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/fault_matrix_assertion.log` |
| workload_impact_assertion | PASS | PASS | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/workload_impact_assertion.log` |
| cleanup_report_check | PASS | PASS | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/cleanup_report_check.log` |

All gate commands exactly match `codex/phase_manifest.json`. All referenced stdout/stderr log SHA256 values match `gate_result.json`.

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/phase_summary.json` | `schemas/artifact/phase_summary.schema.json` | valid | `assert_quant_artifacts.py` PASS |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/valkey_e2e_evidence.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | valid | `assert_quant_artifacts.py` PASS |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/cleanup_report.json` | `schemas/artifact/cleanup_report.schema.json` | valid | `assert_cleanup.py` PASS |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/events.jsonl` | `schemas/artifact/goal_loop_event.schema.json` | valid | `assert_quant_artifacts.py` PASS |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/metrics_timeseries.jsonl` | `schemas/artifact/goal_loop_metric_sample.schema.json` | valid | `assert_quant_artifacts.py` PASS |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/workload_windows.json` | `schemas/artifact/workload_windows.schema.json` | valid | `assert_quant_artifacts.py` PASS |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/quant_summary.json` | `schemas/artifact/quant_summary.schema.json` | valid | `assert_quant_artifacts.py` PASS |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/fault_matrix_report.json` | `schemas/artifact/fault_matrix_report.schema.json` | valid | `assert_fault_matrix_coverage.py` PASS |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/fault_results.jsonl` | `schemas/artifact/fault_result.schema.json` | valid | `assert_fault_matrix_coverage.py` PASS |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/fault_topology_snapshots.jsonl` | `schemas/artifact/topology_snapshot.schema.json` | valid | `assert_quant_artifacts.py` PASS |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/workload_impact_report.json` | `schemas/artifact/workload_impact_report.schema.json` | valid | `assert_workload_impact.py` PASS |

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: verified
- Default node cap <= 100: verified

P22 logical host and virtual AZ stops use topology labels over owned Valkey processes/containers. The reviewed P22 rows record `implementation_path: owned_runtime_control`, `host_network_mutated: false`, `physical_host_mutated: false`, and `physical_az_mutated: false`.

## Real Valkey findings

Required for this phase: YES
Evidence file: `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/valkey_e2e_evidence.json`
Valkey version observed: `9.1.0`
Independent live probe: PASS

The evidence reports real Valkey, `probe_result: PASS`, `data_path_result: PASS`, `cluster_state_observed: ok`, and `nodes_observed: 30`. `fault_results.jsonl` includes PASS rows for `replica_stop`, `node_host_stop`, and `az_stop` at 6, 10, and 30 nodes.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| Focused low-sample workload windows limit percentile depth | low | no | Missing high-percentile values are encoded as `MISSING` with reasons. |

## Final rationale

The P22 gate result is PASS, all manifest commands match, all referenced log hashes match, required artifacts exist and pass focused validation, real Valkey 9.1.0 evidence covers 6/10/30-node P22 fault rows, cleanup reports no remaining resources, and the implementation stays within owned runtime/container controls without host network or physical host/AZ mutation.
