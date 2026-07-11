# AUDIT - P35_FAULT_FAILOVER_MATRIX_200_REAL

Fresh Context: YES
Decision: PASS

Gate result path: artifacts/gates/P35_FAULT_FAILOVER_MATRIX_200_REAL/gate_result.json
Gate result SHA-256: c791a20aa98ffb62c3db48ec07055b32420519291e9364386b3a520be186548f

## Audit Summary

P35 satisfies the strict real 200-node fault/failover matrix contract. The final gate result is PASS. The reviewed artifacts show exact 200 requested and 200 observed real Valkey nodes, Valkey 9.1.0 evidence, data path PASS, all 12 required fault rows PASS, three primary-stop failover samples with coverage_id=200.fault.primary_stop_failover, node_host_stop and az_stop restored 100-node target groups, split-brain detectors executed, workload impact telemetry present, sandbox-scoped network faults, coverage registry PASS, no host network mutation evidence, and cleanup PASS with no owned containers remaining.

## Required Artifact Paths

- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/phase_summary.json
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/valkey_e2e_evidence.json
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/cleanup_report.json
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/events.jsonl
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/metrics_timeseries.jsonl
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/workload_windows.json
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/quant_summary.json
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/coverage_ledger.json
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/resource_preflight.json
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/cluster_plan.json
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/run_state.json
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/fault_matrix_report.json
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/fault_operation_results.jsonl
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/failover_samples.jsonl
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/failover_latency_curve.json
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/partition_report.json
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/split_brain_report.json
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/fault_workload_impact.json
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/fault_topology_snapshots.jsonl
- artifacts/phases/P35_FAULT_FAILOVER_MATRIX_200_REAL/fault_command_log.jsonl

## Risks

- The exact 200-node run is resource-intensive and remains acceptable only as a user-required bounded exception for explicit 200-node stages.
- The P35 preflight uses scale_200.yaml whose embedded marker still references P21, but the runtime/resource checks record explicit P35 phase and strict_fault_matrix_200 scenario identity and pass P35-specific exact-200 checks.

## Rationale

The audit decision is PASS because the final P35 gate and independent artifact checks satisfy every P35 pass criterion: exact 200 real Valkey 9.1.x evidence, data path PASS, all 12 strict fault rows PASS, three primary-stop failover samples, workload metrics, split-brain detector evidence, sandboxed network fault paths, coverage registry updates for 200.fault.*, cleanup PASS, anti-bypass PASS, and no owned containers left behind.
