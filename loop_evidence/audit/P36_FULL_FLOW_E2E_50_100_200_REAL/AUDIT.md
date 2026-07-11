# Audit: P36_FULL_FLOW_E2E_50_100_200_REAL

Fresh Context: YES

Decision: PASS

Auditor: fresh-context review subagent

Created At: 2026-07-04T17:28:39Z

Gate result: `artifacts/gates/P36_FULL_FLOW_E2E_50_100_200_REAL/gate_result.json`

Gate result SHA256: `f52aaa19ef0abb35eb92081b9ff7ce65802e57d42a00387fa826229d0ebd88d1`

## Required Artifact Citations

- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/phase_summary.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_matrix.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_results.jsonl`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_50/valkey_e2e_evidence.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_100/valkey_e2e_evidence.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_200/valkey_e2e_evidence.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/events.jsonl`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/metrics_timeseries.jsonl`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/workload_windows.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/quant_summary.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/coverage_ledger.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/cleanup_report.json`

## Audit Summary

The current gate result is PASS and its SHA256 is `f52aaa19ef0abb35eb92081b9ff7ce65802e57d42a00387fa826229d0ebd88d1`.

P36 has exact real Valkey evidence for all required scales:

- 50 requested and 50 observed, Valkey `9.1.0`, data path PASS, cleanup PASS.
- 100 requested and 100 observed, Valkey `9.1.0`, data path PASS, cleanup PASS.
- 200 requested and 200 observed, Valkey `9.1.0`, data path PASS, cleanup PASS.

The fixed `full_flow_results.jsonl` rows include `artifact_type=full_flow_result`, satisfying the earlier failed schema requirement. Full-flow matrix and result artifacts link to scoped config validation, resource preflight, planning, run state, workload telemetry, representative management command logs, representative fault/failover command logs, analysis summaries, report indexes, exact-scale Valkey evidence, and cleanup reports.

Quantification and registry evidence are consistent: 36 P36 lifecycle PASS rows, 84 event rows, 858 metric rows, 39 workload windows, and node counts `[50, 100, 200]`. Future dry-run rows remain PENDING and owned by P37.

Safety checks are clean: no host firewall, route, interface, PF, nftables, iptables, or OS network-service mutation was found; no `sudo` network path was introduced; no real execution above 200 nodes was performed; the default development cap remains 100 except for the narrow P36 exact-200 bounded exception; and no 200-node downshift was found.

Cleanup is PASS in aggregate and per scale. Docker label spot check for `vslab.phase=P36_FULL_FLOW_E2E_50_100_200_REAL` returned no running containers.

## Risks

- Low: P36 uses representative management and fault/failover execution inside the product-level flow; exhaustive matrix ownership remains with P30-P35. This is acceptable for P36 and does not block completion.

## Commit Readiness

P36 is ready for postcheck, mark-complete, commit, and push by the main agent. This audit subagent did not mark complete, commit, or push.
