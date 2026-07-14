# P36_FULL_FLOW_E2E_50_100_200_REAL — Full-Flow E2E at 50/100/200

## Purpose

Prove the whole system works as an end-to-end product at real 50, 100, and 200 nodes, not only as isolated management or fault stages.

## Required full-flow sequence per scale

For each scale `50`, `100`, and `200`, run or validate a real full-flow scenario that includes:

```text
config validate
resource preflight
plan
cluster create
baseline workload
telemetry collection
representative management operation sequence
representative fault/failover sequence
recovery verification
analysis generation
report rendering
cleanup verification
```

The full-flow scenario may reuse implementation modules from P30-P35, but it must produce its own P36 artifacts and exact-scale evidence.

## Required artifacts

```text
artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/phase_summary.json
artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_matrix.json
artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_results.jsonl
artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_50/valkey_e2e_evidence.json
artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_100/valkey_e2e_evidence.json
artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_200/valkey_e2e_evidence.json
artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/events.jsonl
artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/metrics_timeseries.jsonl
artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/workload_windows.json
artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/quant_summary.json
artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/coverage_ledger.json
artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/cleanup_report.json
```

## Required gates

```text
python3 scripts/assert_full_flow_e2e.py --phase P36_FULL_FLOW_E2E_50_100_200_REAL --scales 50,100,200
python3 scripts/assert_exact_scale_real_evidence.py --phase P36_FULL_FLOW_E2E_50_100_200_REAL --nodes 50 --artifact-scope full_flow_50
python3 scripts/assert_exact_scale_real_evidence.py --phase P36_FULL_FLOW_E2E_50_100_200_REAL --nodes 100 --artifact-scope full_flow_100
python3 scripts/assert_exact_scale_real_evidence.py --phase P36_FULL_FLOW_E2E_50_100_200_REAL --nodes 200 --artifact-scope full_flow_200
python3 scripts/assert_quant_completeness.py --phase P36_FULL_FLOW_E2E_50_100_200_REAL --category full_flow
python3 scripts/assert_coverage_registry.py --phase P36_FULL_FLOW_E2E_50_100_200_REAL --category lifecycle --scales 50,100,200
python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/cleanup_report.json
```

## Pass criteria

P36 passes only when:

```text
50/100/200 full-flow results exist
all three exact-scale evidence checks pass
management/fault modules are exercised through orchestration, not only imported
analysis and report generation run from artifacts
cleanup passes after each scale
coverage registry lifecycle rows are PASS for 50/100/200
```

## Blocking conditions

```text
any scale is omitted
200-node full flow downshifts
analysis/report uses fake data
cleanup fails
full-flow artifacts are not tied to source evidence
```
