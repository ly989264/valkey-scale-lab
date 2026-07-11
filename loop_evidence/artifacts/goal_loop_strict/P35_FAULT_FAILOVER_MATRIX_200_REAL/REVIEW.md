# REVIEW - P35_FAULT_FAILOVER_MATRIX_200_REAL

Fresh Context: YES
Decision: PASS

## Review Basis

I reread the strict review prompt, AGENTS.md, CODEX_STRICT_MATRIX_LOOP_START.md, the strict index and relevant strict contracts, the P35 stage document, CONTEXT_RELOAD.md, DESIGN_BRIEF.md, WORKER_SUMMARY.md, the gate result, the required phase artifacts, the harness exception note, and the audit decision schema.

Gate result path: artifacts/gates/P35_FAULT_FAILOVER_MATRIX_200_REAL/gate_result.json
Gate result SHA-256: c791a20aa98ffb62c3db48ec07055b32420519291e9364386b3a520be186548f

## Independent Checks

- Gate status is PASS, including harness precheck, safety scan, compile, unit/integration tests, strict stage contract, anti-bypass, real fault/failover e2e, exact scale evidence, strict fault matrix, failover latency curve, split-brain report, quant completeness, coverage registry, and cleanup assertion.
- Real evidence reports status PASS, real_valkey=true, nodes_requested=200, nodes_observed=200, probe_result=PASS, data_path_result=PASS, and Valkey version 9.1.0.
- Resource preflight reports can_run=true, dry_run=false, node_count=200, nodes_requested=200, P35 exact-200 bounded exception PASS, and P35 no-host-network-mutation PASS.
- Fault matrix evidence reports all 12 strict 200.fault.* rows PASS with real_execution_verified=true. Network rows use sandbox_proxy. node_host_stop and az_stop both record observed_impact target_group_count=100 and cluster_restored=true.
- failover_samples.jsonl contains three independent primary-stop samples, all status PASS, scale=200, node_count=200, and coverage_id=200.fault.primary_stop_failover.
- Split-brain report is PASS with split_brain_window_ms=0 backed by four ran detectors: primary slot overlap, partition-side view divergence, conflicting write probe, and old-primary write-after-promotion.
- Workload and telemetry artifacts are present: events.jsonl has 28 rows, metrics_timeseries.jsonl has 70 rows, workload_windows.json has 14 windows, fault_topology_snapshots.jsonl has 14 rows, and fault_command_log.jsonl has 213 rows.
- Coverage registry and coverage ledger show the 12 P35-owned 200.fault.* rows as PASS, execution_mode=real, with P35 source artifacts, validation artifacts, metric refs, cleanup ref, and review ref.
- Cleanup report is PASS with resources_remaining=[]. Live Docker inventory checks for the P35 phase label, final wrapper run label, and setup run label returned no containers.
- The harness exception documents additive changes to protected scripts and the gate lock only for strengthened P35 profile/quant checks; no phase state or gate result was edited to force PASS.

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

## Coverage IDs:

- 200.fault.primary_stop_failover
- 200.fault.replica_stop
- 200.fault.node_host_stop
- 200.fault.az_stop
- 200.fault.network_delay
- 200.fault.network_loss
- 200.fault.network_flap
- 200.fault.network_partition
- 200.fault.minority_partition
- 200.fault.majority_partition
- 200.fault.split_brain_window_detection
- 200.fault.fault_period_workload_impact

## Risks

- The exact 200-node run is intentionally resource-heavy and must remain bounded to P35/P36-style explicit stage contracts; reviewed runtime/resource diffs keep the P35 allowance exact to P35 and strict_fault_matrix_200.
- cleanup_report.json uses the setup run label while the final evidence run_id uses the wrapper run label. Both labels and the P35 phase label were checked with docker ps, and all returned no containers.

## Rationale

P35 satisfies the strict exact-200 fault/failover matrix contract. The final sustained-readiness gate passed with real Valkey 9.1.0 evidence at exactly 200 observed nodes, all required fault rows, three correctly attributed failover samples, measured workload and telemetry artifacts, detector-backed split-brain reporting, sandbox-scoped network faulting, coverage registry confirmation, no host network mutation evidence, and cleanup PASS with no owned containers remaining.
