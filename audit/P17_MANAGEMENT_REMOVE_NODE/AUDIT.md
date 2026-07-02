# Audit - P17_MANAGEMENT_REMOVE_NODE

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-07-02T16:51:30Z

Gate Result: artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/gate_result.json
Observed Gate Result SHA256: e827d805256897c922efdd6cd96ff3823cd9d6c8cc3413a3250ca2a291fc0c7e

## Scope inspected

- `codex/phase_manifest.json`
- `docs/codex/goal-loop/stages/P17_MANAGEMENT_REMOVE_NODE.md`
- `artifacts/goal_loop/P17_MANAGEMENT_REMOVE_NODE/REVIEW.md`
- P17 source and assertion changes
- gate result and logs
- required artifacts
- schema validation output
- cleanup evidence
- real Valkey evidence

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| harness_precheck | PASS | PASS | `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/stdout/harness_precheck.log` |
| safety_static_scan | PASS | PASS | `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/stdout/safety_static_scan.log` |
| scripts_compile | PASS | PASS | `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/stdout/scripts_compile.log` |
| unit_integration_tests | PASS | PASS | `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/stdout/unit_integration_tests.log` |
| goal_loop_stage_assertion | PASS | PASS | `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/stdout/goal_loop_stage_assertion.log` |
| real_valkey_e2e | PASS | PASS | `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/stdout/real_valkey_e2e.log` |
| quant_artifact_assertion | PASS | PASS | `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/stdout/quant_artifact_assertion.log` |
| management_ops_assertion | PASS | PASS | `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/stdout/management_ops_assertion.log` |
| workload_impact_assertion | PASS | PASS | `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/stdout/workload_impact_assertion.log` |
| cleanup_report_check | PASS | PASS | `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/stdout/cleanup_report_check.log` |

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/phase_summary.json` | declared | valid | required artifact present and postcheck-gated |
| `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/valkey_e2e_evidence.json` | declared | valid | required artifact present and postcheck-gated |
| `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/cleanup_report.json` | declared | valid | required artifact present and postcheck-gated |
| `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/events.jsonl` | declared | valid | required artifact present and postcheck-gated |
| `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/metrics_timeseries.jsonl` | declared | valid | required artifact present and postcheck-gated |
| `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/workload_windows.json` | declared | valid | required artifact present and postcheck-gated |
| `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/quant_summary.json` | declared | valid | required artifact present and postcheck-gated |
| `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_ops_matrix.json` | declared | valid | required artifact present and postcheck-gated |
| `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_operation_results.jsonl` | declared | valid | required artifact present and postcheck-gated |
| `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_workload_impact.json` | declared | valid | required artifact present and postcheck-gated |
| `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_topology_snapshots.jsonl` | declared | valid | required artifact present and postcheck-gated |
| `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_command_log.jsonl` | declared | valid | required artifact present and postcheck-gated |

Required artifact paths:

- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/phase_summary.json`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/valkey_e2e_evidence.json`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/cleanup_report.json`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/events.jsonl`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/metrics_timeseries.jsonl`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/workload_windows.json`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/quant_summary.json`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_ops_matrix.json`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_operation_results.jsonl`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_workload_impact.json`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_topology_snapshots.jsonl`
- `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_command_log.jsonl`


## Management Matrix Findings

All six required P17 rows passed with clean before/after cluster state and full slot coverage:

- `remove_replica-06`: before ok/16384 slots, after ok/16384 slots, observed_nodes_after=5, real_execution_verified=True
- `remove_replica-10`: before ok/16384 slots, after ok/16384 slots, observed_nodes_after=9, real_execution_verified=True
- `remove_primary_drained-06`: before ok/16384 slots, after ok/16384 slots, observed_nodes_after=5, real_execution_verified=True
- `remove_primary_drained-10`: before ok/16384 slots, after ok/16384 slots, observed_nodes_after=9, real_execution_verified=True
- `remove_failed_node-06`: before ok/16384 slots, after ok/16384 slots, observed_nodes_after=5, real_execution_verified=True
- `remove_failed_node-10`: before ok/16384 slots, after ok/16384 slots, observed_nodes_after=9, real_execution_verified=True

`artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_ops_matrix.json` lists all six required rows. `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/management_operation_results.jsonl` provides the row-level evidence.

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: verified by `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/cleanup_report.json`, status `PASS`, resources_remaining=[]
- Default node cap <= 100: verified; P17 max node count is 10
- Harness exception: `artifacts/harness_exception/P17_MANAGEMENT_REMOVE_NODE.md` strengthens the P17 assertion to require exact 6-node and 10-node rows plus clean before/after evidence.

## Real Valkey findings

Required for this phase: YES
Evidence file: `artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/valkey_e2e_evidence.json`
Valkey version observed: `9.1.0`
Independent live probe: `PASS`
Data path result: `PASS`

## Quantitative findings

`artifacts/phases/P17_MANAGEMENT_REMOVE_NODE/quant_summary.json` reports status `PASS` and counts `{"command_log_count": 56, "event_count": 86, "main_gate_node_count": 6, "metric_count": 720, "operation_count": 6, "six_node_operation_count": 3, "ten_node_operation_count": 3, "topology_snapshot_count": 24, "workload_window_count": 36}`.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| The outer wrapper remains a 6-node probe while 10-node proof is produced by P17 runtime sidecar rows. | low | no | The strengthened management assertion and artifacts enforce all 10-node rows, and review verified this evidence. |

## Final rationale

P17 satisfies the stage objective. The gate result is PASS, the fresh-context review is PASS, all required artifacts are present and cited, all six required remove-node rows are real PASS rows for 6 and 10 nodes, primary removal uses takeover before old-primary removal, workload/topology/command artifacts were generated, and cleanup reports no remaining owned resources.
