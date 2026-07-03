# REVIEW — P22_FAULT_REPLICA_HOST_AZ_STOP

## Scope reviewed

Fresh-context review of P22 implementation diffs, manifest gates, gate logs, hashes, required artifacts, real Valkey evidence, safety boundaries, cleanup, and P22-only stage scope.

## Documents and artifacts read

- `AGENTS.md`
- `CODEX_START_HERE.md`
- `CODEX_GOAL_LOOP_START.md`
- `docs/codex/04_AUDITOR.md`
- `docs/codex/goal-loop/00_INDEX.md` through `10_AUDIT_AND_COMMIT_POLICY.md`
- `docs/codex/goal-loop/stages/P22_FAULT_REPLICA_HOST_AZ_STOP.md`
- `artifacts/goal_loop/P22_FAULT_REPLICA_HOST_AZ_STOP/CONTEXT_RELOAD.md`
- `artifacts/goal_loop/P22_FAULT_REPLICA_HOST_AZ_STOP/DESIGN_BRIEF.md`
- `artifacts/goal_loop/P22_FAULT_REPLICA_HOST_AZ_STOP/WORKER_SUMMARY.md`
- `codex/phase_manifest.json`
- `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/gate_result.json`
- Required P22 artifacts under `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/`

## Diff review

Reviewed `git diff --name-only` and targeted diffs for:

- `scripts/fault_safety_gate.py`
- `scripts/assert_fault_matrix_coverage.py`
- `scripts/assert_quant_artifacts.py`
- `scripts/assert_workload_impact.py`
- `src/valkey_scale_lab/runtime/docker_runtime.py`
- `tests/integration/test_docker_runtime_contract.py`
- `tests/unit/test_goal_loop_assertions.py`
- `templates/configs/p22_6.yaml`
- `templates/configs/p22_10.yaml`
- `templates/configs/p22_30.yaml`
- `artifacts/harness_exception/P22_FAULT_REPLICA_HOST_AZ_STOP.md`
- `codex/gate_lock.json`

The implementation is scoped to P22 replica, logical node-host, and virtual AZ stop faults. P22 runtime admission is capped at 100 nodes and rejects 200-node P22 scenarios. I found no added P23/P24 network delay/loss/flap/partition implementation in the current diff beyond pre-existing shared fault-matrix identifiers.

## Gate review

Gate result: `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/gate_result.json`

Observed gate result SHA256: `c99e7cd8762e248f14fd5acc8866ac1447f5ac50454954b75967ae2cf8a766ce`

Manifest command comparison: all 10 gate names and commands matched `codex/phase_manifest.json`.

Log SHA256 verification: every stdout/stderr file referenced by `gate_result.json` exists and matches its recorded SHA256.

| Gate/check | Evidence | Result |
|---|---|---:|
| harness_precheck | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/harness_precheck.log` | PASS |
| safety_static_scan | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/safety_static_scan.log` | PASS |
| scripts_compile | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/scripts_compile.log` | PASS |
| unit_integration_tests | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/unit_integration_tests.log` | PASS |
| goal_loop_stage_assertion | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/goal_loop_stage_assertion.log` | PASS |
| real_fault_safety_gate | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/real_fault_safety_gate.log` | PASS |
| quant_artifact_assertion | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/quant_artifact_assertion.log` | PASS |
| fault_matrix_assertion | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/fault_matrix_assertion.log` | PASS |
| workload_impact_assertion | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/workload_impact_assertion.log` | PASS |
| cleanup_report_check | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/stdout/cleanup_report_check.log` | PASS |
| focused rerun: quant artifacts | `python3 scripts/assert_quant_artifacts.py --phase P22_FAULT_REPLICA_HOST_AZ_STOP` | PASS |
| focused rerun: fault matrix | `python3 scripts/assert_fault_matrix_coverage.py --phase P22_FAULT_REPLICA_HOST_AZ_STOP` | PASS |
| focused rerun: workload impact | `python3 scripts/assert_workload_impact.py --phase P22_FAULT_REPLICA_HOST_AZ_STOP` | PASS |
| focused rerun: cleanup | `python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/cleanup_report.json` | PASS |

## Artifact/schema review

All manifest-required artifacts exist and were validated by `quant_artifact_assertion`, `fault_matrix_assertion`, `workload_impact_assertion`, and `cleanup_report_check`.

- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/phase_summary.json`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/valkey_e2e_evidence.json`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/cleanup_report.json`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/events.jsonl`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/metrics_timeseries.jsonl`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/workload_windows.json`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/quant_summary.json`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/fault_matrix_report.json`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/fault_results.jsonl`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/fault_topology_snapshots.jsonl`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/workload_impact_report.json`

`fault_results.jsonl` contains 9 PASS rows: `replica_stop`, `node_host_stop`, and `az_stop` at 6, 10, and 30 nodes. `events.jsonl` has 153 rows, `metrics_timeseries.jsonl` has 198 rows, and `fault_topology_snapshots.jsonl` has 27 rows. Missing metrics are encoded as `MISSING` with reasons.

## Real Valkey evidence review

`artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/valkey_e2e_evidence.json` records `status: PASS`, `real_valkey: true`, `valkey_versions: ["9.1.0"]`, `probe_result: PASS`, `data_path_result: PASS`, `cluster_state_observed: ok`, and `nodes_observed: 30`.

Coverage verified:

- Required rows at 6 and 10 nodes: present for all three P22 fault types.
- 30+ evidence: `resource_preflight_30.json` has `can_run: true`, and real 30-node rows are present for all three P22 fault types.
- Replica stop target roles: all `replica_stop` rows target only replica nodes and record `promotion_expected: false`.
- Host stop grouping: all `node_host_stop` targets share the selected logical `host_id`.
- AZ stop grouping: all `az_stop` targets share the selected virtual `az_id`.

## Safety review

P22 stop faults are implemented through `python3 -m valkey_scale_lab.cli fault apply` and `fault clear` with fault type `node_stop`, `scope: owned_container_or_process`, and `forbid_host_network_mutation: true`. The generated P22 configs use logical host labels and virtual AZ labels over local Docker, not physical host or real AZ control.

The safety evidence records:

- `host_network_mutated: false`
- `global_firewall_mutated: false`
- `physical_host_mutated: false`
- `physical_az_mutated: false`
- `logical_topology_labels_only: true`

I found no default `sudo`, host firewall, host route, host interface, or global OS network mutation in the P22 diff.

## Quantitative coverage review

`workload_impact_report.json` contains 54 windows and 9 comparisons, covering baseline, pre_event, event, recovery, post_recovery, and all_run for every real P22 sample. Recovery timing, apply/clear timing, topology snapshots before/during/recovered, event rows, metric rows, QPS, latency, error, timeout, and redirection metrics are present.

## Cleanup review

`artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/cleanup_report.json` records `status: PASS`, empty `resources_remaining`, and PASS cleanup actions for 6-, 10-, and 30-node subruns. Focused cleanup assertion also passed.

## Blocking findings

| ID | Severity | Finding | Required fix |
|---|---|---|---|
| none | none | No blocking findings. | None. |

## Non-blocking notes

- `WORKER_SUMMARY.md` still describes an earlier sandbox-failed run, but the later gate result at `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/gate_result.json` is the reviewed source of truth and is PASS.
- The P22 workload is intentionally focused and low-sample; p999 and some p99 values are represented as `MISSING` with reasons where sample counts are insufficient.

## Decision

Decision: PASS
