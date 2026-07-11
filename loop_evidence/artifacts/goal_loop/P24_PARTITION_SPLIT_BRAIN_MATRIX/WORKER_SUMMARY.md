# WORKER_SUMMARY — P24_PARTITION_SPLIT_BRAIN_MATRIX

## Scope implemented

Implemented the P24 partition and split-brain matrix only. Added a first-class P24 real gate path in `scripts/fault_safety_gate.py` covering exactly:

- `network_partition_minority`
- `network_partition_majority`
- `split_brain_window_detection`

The P24 controller runs bounded real Valkey clusters at 6 and 10 nodes, applies partitions by disconnecting owned Docker nodehost containers from the owned stage Docker network, probes majority and minority sides, runs split-brain detectors, clears the partition, verifies recovery, and emits the required P24 artifacts.

## Changed files

| Path | Summary |
|---|---|
| `scripts/fault_safety_gate.py` | Added P24 controller, partition planner, owned Docker network apply/clear command logging, side probes, split-brain detectors, workload windows, reports, and quant artifacts. |
| `src/valkey_scale_lab/runtime/docker_runtime.py` | Added bounded P24 scenario admission and P24-specific process nodehost grouping so one minority nodehost can be partitioned while majority nodehosts remain connected. |
| `templates/configs/p24_6.yaml` | Added deterministic 6-node P24 real gate config. |
| `templates/configs/p24_10.yaml` | Added deterministic 10-node P24 real gate config on a non-conflicting port range. |
| `schemas/artifact/fault_result.schema.json` | Added `owned_docker_network_control` as an allowed fault implementation path. |
| `scripts/assert_fault_matrix_coverage.py` | Strengthened P24 checks for exact rows, 6/10 real evidence, explicit groups, traffic policy, side probes, side-view comparison, command logs, and no host/global network mutation. |
| `scripts/assert_split_brain_report.py` | Strengthened detector, timing, missing-detector reason, side-view comparison, and positive-window checks. |
| `scripts/assert_workload_impact.py` | Added P24 workload sample/window/comparison checks with side labels. |
| `scripts/assert_quant_artifacts.py` | Added P24 cross-artifact checks for events, metrics, fault rows, topology snapshots, command logs, partition report, split-brain report, evidence, cleanup, and quant counts. |
| `tests/unit/test_goal_loop_assertions.py` | Added P24 assertion fixtures and rejection tests for missing rows, missing detector reasons, missing side probes/groups, and host-network mutation evidence. |
| `tests/integration/test_docker_runtime_contract.py` | Added P24 bounded runtime admission tests and 200/1000 rejection checks. |
| `codex/gate_lock.json` | Updated hashes for intentionally strengthened locked harness/schema files. |

## Commands run

| Command | Result | Log/artifact path |
|---|---|---|
| `PYTHONPYCACHEPREFIX=/tmp/valkey_scale_lab_pycache python3 -m py_compile scripts/fault_safety_gate.py scripts/assert_fault_matrix_coverage.py scripts/assert_split_brain_report.py scripts/assert_workload_impact.py scripts/assert_quant_artifacts.py src/valkey_scale_lab/runtime/docker_runtime.py` | PASS | terminal output |
| `PYTHONPYCACHEPREFIX=/tmp/valkey_scale_lab_pycache python3 -m compileall -q scripts src` | PASS | terminal output and final gate result |
| `PYTHONPYCACHEPREFIX=/tmp/valkey_scale_lab_pycache python3 -m pytest -q tests/unit/test_goal_loop_assertions.py tests/integration/test_docker_runtime_contract.py` | PASS, 99 tests | terminal output |
| `PYTHONPYCACHEPREFIX=/tmp/valkey_scale_lab_pycache python3 -m pytest -q tests/integration/test_docker_runtime_contract.py tests/config/test_config_validation.py` | PASS, 66 tests | terminal output |
| `python3 scripts/safety_scan.py` | PASS | terminal output and final gate result |
| `python3 scripts/assert_goal_loop_stage.py --phase P24_PARTITION_SPLIT_BRAIN_MATRIX` | PASS | terminal output and final gate result |
| `python3 scripts/codex_gate.py precheck --phase P24_PARTITION_SPLIT_BRAIN_MATRIX` | PASS | terminal output and final gate result |
| `python3 scripts/codex_gate.py run --phase P24_PARTITION_SPLIT_BRAIN_MATRIX` | Initial sandbox run failed on localhost port permission; escalated final run PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/gate_result.json` |

## Gates and assertions

| Gate/assertion | Result | Evidence path |
|---|---:|---|
| Harness precheck | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/gate_result.json` |
| Safety static scan | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/safety_static_scan.log` |
| Compileall | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/scripts_compile.log` |
| Unit/integration tests | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/unit_integration_tests.log` |
| Goal-loop stage assertion | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/goal_loop_stage_assertion.log` |
| Real fault safety gate | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/real_fault_safety_gate.log` |
| Quant artifact assertion | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/quant_artifact_assertion.log` |
| Fault matrix assertion | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/fault_matrix_assertion.log` |
| Split-brain assertion | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/split_brain_assertion.log` |
| Workload impact assertion | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/workload_impact_assertion.log` |
| Cleanup report check | PASS | `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/stdout/cleanup_report_check.log` |

## Artifacts produced

| Artifact | Schema/check | Result |
|---|---|---:|
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/phase_summary.json` | `phase_summary.schema.json` via quant assertion | PASS |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/valkey_e2e_evidence.json` | Real Valkey evidence check | PASS |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/cleanup_report.json` | `assert_cleanup.py` | PASS |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/events.jsonl` | `goal_loop_event.schema.json` | PASS |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/metrics_timeseries.jsonl` | `goal_loop_metric_sample.schema.json` | PASS |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/workload_windows.json` | required artifact + workload assertion | PASS |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/quant_summary.json` | `quant_summary.schema.json` + P24 cross-checks | PASS |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/partition_report.json` | `partition_report.schema.json` + P24 semantic checks | PASS |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/split_brain_report.json` | `split_brain_report.schema.json` + detector checks | PASS |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/fault_results.jsonl` | `fault_result.schema.json` + row coverage | PASS |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/fault_topology_snapshots.jsonl` | P24 quant cross-check | PASS |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/workload_impact_report.json` | workload impact assertion | PASS |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/fault_matrix_report.json` | manifest required artifact | PASS |
| `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/network_partition_command_log.jsonl` | command log schema + safety checks | PASS |

## Quantitative evidence summary

- Real Valkey evidence: `status=PASS`, `nodes_observed=10`, `valkey_versions=["9.1.0"]`.
- Fault rows: 6 real rows, covering all three P24 rows at 6 and 10 nodes.
- Quant counts: 102 events, 138 metric samples, 18 topology snapshots, 12 command-log entries, 6 partition samples, and 6 split-brain samples.
- Split-brain detectors run per sample: `primary_slot_assignment_overlap`, `partition_side_cluster_view_divergence`, and `conflicting_write_probe`.
- `old_primary_accepts_write_after_promotion` is encoded as `MISSING` with reason because P24 does not inject a primary-stop promotion condition.
- Final aggregate `split_brain_window_ms` was measured from detector timing; no zero window was assumed.

## Cleanup summary

Cleanup passed. `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/cleanup_report.json` has `status=PASS` and `resources_remaining=[]`.

## Deviations from design

- The design considered a three-AZ config, but existing global validation requires exactly two virtual AZs for `virtual_az_mode: multi`. I preserved that validator and instead added P24-specific owned nodehost grouping inside the process runtime: one minority nodehost and two majority nodehosts.
- The implementation path is recorded as `owned_docker_network_control`, backed by Docker network disconnect/reconnect on owned, run-labeled nodehost containers. No host firewall, route, interface, global network service, or host-level network mutation is used.
- The first non-escalated P24 run failed at localhost port preflight due sandbox permission. The final run was escalated and passed. Earlier 10-node port `7700` showed a transient conflict, so `templates/configs/p24_10.yaml` now uses deterministic port range `7820/17820`.

## Remaining risks or `待验证`

- `old_primary_accepts_write_after_promotion` remains reasoned `MISSING`; P24 measures partition/split-brain indicators but does not force a promotion-specific old-primary detector condition.
- P24 partitions are implemented by owned Docker network membership changes, not `tc`/netem. The assertion layer explicitly allows only this scoped path for P24 and rejects host/global network mutation evidence.

## Review handoff notes

- Review should inspect `scripts/fault_safety_gate.py` P24 controller, `src/valkey_scale_lab/runtime/docker_runtime.py` P24 nodehost grouping, and the strengthened P24 assertion branches.
- Final successful gate result: `artifacts/gates/P24_PARTITION_SPLIT_BRAIN_MATRIX/gate_result.json`.
- Do not mark complete, commit, or push from worker scope.
