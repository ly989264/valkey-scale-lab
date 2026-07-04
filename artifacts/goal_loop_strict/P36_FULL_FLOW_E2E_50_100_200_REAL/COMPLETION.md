# COMPLETION - P36_FULL_FLOW_E2E_50_100_200_REAL

## Stage result

- Stage ID: P36_FULL_FLOW_E2E_50_100_200_REAL
- Review path: artifacts/goal_loop_strict/P36_FULL_FLOW_E2E_50_100_200_REAL/REVIEW.md
- Review decision: Decision: PASS
- Audit path: audit/P36_FULL_FLOW_E2E_50_100_200_REAL/AUDIT.md
- Audit decision JSON: audit/P36_FULL_FLOW_E2E_50_100_200_REAL/audit_decision.json
- Gate result path: artifacts/gates/P36_FULL_FLOW_E2E_50_100_200_REAL/gate_result.json
- Gate result SHA256: f52aaa19ef0abb35eb92081b9ff7ce65802e57d42a00387fa826229d0ebd88d1

## Commands

```text
python3 scripts/codex_gate.py run --phase P36_FULL_FLOW_E2E_50_100_200_REAL
WROTE artifacts/gates/P36_FULL_FLOW_E2E_50_100_200_REAL/gate_result.json status=PASS

python3 scripts/codex_gate.py postcheck --phase P36_FULL_FLOW_E2E_50_100_200_REAL
PASS postcheck P36_FULL_FLOW_E2E_50_100_200_REAL

python3 scripts/codex_gate.py mark-complete --phase P36_FULL_FLOW_E2E_50_100_200_REAL
PASS postcheck P36_FULL_FLOW_E2E_50_100_200_REAL
MARKED_COMPLETE P36_FULL_FLOW_E2E_50_100_200_REAL
```

## Commit and push

- Commit hash: stage commit containing this file
- Commit subject: P36_FULL_FLOW_E2E_50_100_200_REAL: prove full-flow lifecycle
- Push result: stage commit pushed after mark-complete

## Coverage IDs completed

- 50.lifecycle.config_validate
- 50.lifecycle.resource_preflight
- 50.lifecycle.plan_cluster
- 50.lifecycle.create_cluster
- 50.lifecycle.meet_nodes
- 50.lifecycle.assign_slots
- 50.lifecycle.add_replica
- 50.lifecycle.baseline_workload
- 50.lifecycle.telemetry_collect
- 50.lifecycle.analysis_build
- 50.lifecycle.report_render
- 50.lifecycle.cleanup_verify
- 100.lifecycle.config_validate
- 100.lifecycle.resource_preflight
- 100.lifecycle.plan_cluster
- 100.lifecycle.create_cluster
- 100.lifecycle.meet_nodes
- 100.lifecycle.assign_slots
- 100.lifecycle.add_replica
- 100.lifecycle.baseline_workload
- 100.lifecycle.telemetry_collect
- 100.lifecycle.analysis_build
- 100.lifecycle.report_render
- 100.lifecycle.cleanup_verify
- 200.lifecycle.config_validate
- 200.lifecycle.resource_preflight
- 200.lifecycle.plan_cluster
- 200.lifecycle.create_cluster
- 200.lifecycle.meet_nodes
- 200.lifecycle.assign_slots
- 200.lifecycle.add_replica
- 200.lifecycle.baseline_workload
- 200.lifecycle.telemetry_collect
- 200.lifecycle.analysis_build
- 200.lifecycle.report_render
- 200.lifecycle.cleanup_verify

P36 produced exact-scale real Valkey 9.1.0 full-flow evidence for 50, 100, and 200 nodes. Each scoped run reported `nodes_requested == nodes_observed`, data path PASS, cluster state ok, Valkey version `9.1.0`, representative management and fault/failover execution through P36 orchestration, scoped analysis/report artifacts, and cleanup PASS.

P36 emitted 3 full-flow result rows, 84 events, 858 metric samples, 39 workload windows, aggregate quant summary PASS, aggregate cleanup PASS, and 36 lifecycle coverage rows as PASS. The previous schema review failure for `full_flow_results.jsonl` was fixed by adding `artifact_type=full_flow_result` to each row, then rerunning gates and fresh review.

## Next stage

- Next stage ID: P37_200_PLUS_DRY_RUN_SUPPORT
- Handoff: P37 must implement and prove >200 dry-run support for 201, 250, 300, 500, and 1000 nodes with no real runtime creation, no live >200 cluster formation, no workload above 200, dry-run-marked artifacts, and no-runtime-created proof.
