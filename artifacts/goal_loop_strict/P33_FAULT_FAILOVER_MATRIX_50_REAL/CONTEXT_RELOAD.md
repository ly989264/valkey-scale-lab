# CONTEXT_RELOAD — P33_FAULT_FAILOVER_MATRIX_50_REAL

## Stage

- Stage ID: `P33_FAULT_FAILOVER_MATRIX_50_REAL`
- Stage title: Real 50-Node Fault/Failover Matrix
- Branch: `codex/valkey-scale-lab-loop`
- Current commit: `df13c7e`
- Date/time: `2026-07-04 07:35:23 +0800`

## Harness status

```text
python3 scripts/codex_gate.py next
P33_FAULT_FAILOVER_MATRIX_50_REAL
```

## Git status

```text
git status --short
```

No output; the worktree was clean at stage start.

## Documents Reread

- [x] `AGENTS.md`
- [x] `CODEX_START_HERE.md`
- [x] `CODEX_GOAL_LOOP_START.md`
- [x] `CODEX_STRICT_MATRIX_LOOP_START.md`
- [x] `docs/codex/goal-loop/00_INDEX.md`
- [x] `docs/codex/goal-loop/01_GOAL_CONTRACT.md`
- [x] `docs/codex/goal-loop/02_STAGE_MANIFEST.md`
- [x] `docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md`
- [x] `docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md`
- [x] `docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md`
- [x] `docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md`
- [x] `docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md`
- [x] `docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md`
- [x] `docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md`
- [x] `docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md`
- [x] `docs/codex/goal-loop-strict/00_INDEX.md`
- [x] `docs/codex/goal-loop-strict/01_STRICT_GOAL_CONTRACT.md`
- [x] `docs/codex/goal-loop-strict/02_STRICT_STAGE_MANIFEST.md`
- [x] `docs/codex/goal-loop-strict/03_MAIN_SUBAGENT_LOOP_PROTOCOL.md`
- [x] `docs/codex/goal-loop-strict/04_CONTEXT_LEDGER_PROTOCOL.md`
- [x] `docs/codex/goal-loop-strict/05_FAIL_CLOSED_HARNESS_CONTRACT.md`
- [x] `docs/codex/goal-loop-strict/06_COVERAGE_REGISTRY_SPEC.md`
- [x] `docs/codex/goal-loop-strict/07_QUANTIFICATION_DATA_CONTRACT.md`
- [x] `docs/codex/goal-loop-strict/08_MANAGEMENT_OPERATION_MATRIX_SPEC.md`
- [x] `docs/codex/goal-loop-strict/09_FAULT_FAILOVER_MATRIX_SPEC.md`
- [x] `docs/codex/goal-loop-strict/10_SCALE_EXECUTION_POLICY.md`
- [x] `docs/codex/goal-loop-strict/11_ANALYSIS_VISUAL_REPORT_SPEC.md`
- [x] `docs/codex/goal-loop-strict/12_AUDIT_COMMIT_NO_BYPASS_POLICY.md`
- [x] `docs/codex/goal-loop-strict/stages/P33_FAULT_FAILOVER_MATRIX_50_REAL.md`
- [x] `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md`

## Current Stage Contract Summary

P33 must execute the complete strict fault/failover matrix on exactly 50 real Valkey 9.1.x nodes. It must not downshift or replace the run with generated/static artifacts. Resource preflight must show `can_run=true`, `valkey_e2e_evidence.json` must show `nodes_requested=50` and `nodes_observed=50`, and cleanup must pass with no owned resources left behind.

Required fault rows are:

```text
primary_stop_failover
replica_stop
node_host_stop
az_stop
network_delay
network_loss
network_flap
network_partition
minority_partition
majority_partition
split_brain_window_detection
fault_period_workload_impact
```

`primary_stop_failover` must include at least three independent real samples. Network faults must use `container_netns_tc` or `sandbox_proxy`; host firewall, route, interface, PF, nftables, iptables, or OS network mutation is forbidden. Split-brain detectors must actually run; `split_brain_window_ms=0` is valid only with detector evidence. Every row needs workload impact windows and explicit missing-data reasons where allowed by schema; required rows may not pass as skipped.

Required P33 artifacts include the common real-stage family plus fault-specific outputs:

```text
phase_summary.json
valkey_e2e_evidence.json
resource_preflight.json
cluster_plan.json
run_state.json
cleanup_report.json
events.jsonl
metrics_timeseries.jsonl
workload_windows.json
quant_summary.json
coverage_ledger.json
fault_matrix_report.json
fault_operation_results.jsonl
failover_samples.jsonl
failover_latency_curve.json
partition_report.json
split_brain_report.json
fault_workload_impact.json
fault_topology_snapshots.jsonl
fault_command_log.jsonl
```

Required assertions include exact-scale real evidence, strict fault matrix coverage, failover latency curve with at least three samples, split-brain report validation, quant completeness for `fault` at scale 50, coverage registry update for `50.fault.*`, no-bypass, and cleanup.

## Prior-Stage Handoff Summary

P27-P29 established strict harness, coverage registry, scenario plan, and telemetry collection. P30, P31, and P32 completed the management matrices at exact 50, 100, and 200 nodes. P32's gate result was `artifacts/gates/P32_MANAGEMENT_MATRIX_200_REAL/gate_result.json` with SHA `d8539e5b5bb13dc49c0cf6942edbc6e608cfd22a2b7c2ba52cd868b72f7ca2e8`; P32 was committed and pushed as `df13c7e`. The strict journal explicitly warns that P33 must begin fault/failover evidence and must not reuse management evidence as fault evidence.

## Known Blockers

No blocker is known at context reload time. If 50-node resource preflight fails, if required network fault implementation would require host-level network mutation, if any required row is skipped/missing, if failover samples are fewer than three, or if cleanup fails, P33 must write `BLOCKED.md` and must not mark complete.

## Assumptions and 待验证 Items

- 待验证: whether existing runtime support already implements all P33 fault rows at exact 50 nodes or needs stage-specific scenario routing.
- 待验证: whether network delay/loss/flap/partition rows can use existing owned container namespace/proxy mechanisms without host-level mutation in this environment.
- 待验证: whether strict assertion scripts already recognize P33 fault artifacts or need extension analogous to the P30-P32 management support.
- Assumption: the current branch remains `codex/valkey-scale-lab-loop`, and P33 changes will be committed and pushed as a single stage only after design, worker, gates, review, postcheck, mark-complete, subagent closure, completion update, and journal update.
