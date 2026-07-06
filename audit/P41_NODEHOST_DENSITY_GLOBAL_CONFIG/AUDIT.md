# Audit - P41_NODEHOST_DENSITY_GLOBAL_CONFIG

Decision: PASS

Fresh Context: YES

Gate result: `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/gate_result.json`

Gate result SHA256: `ca9f758d4e35aaa443ad5d3843486323188e5cddc7c141554fcae64d33d59065`

## Required Artifacts Reviewed

- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/phase_summary.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/nodehost_density_plan.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/resource_preflight.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/run_state.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/cluster_plan.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/coverage_ledger.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/analysis_summary.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/report_index.json`

## Additional Evidence Reviewed

- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/smoke_10_valkey_e2e_evidence.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/valkey_e2e_evidence_30.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/valkey_e2e_evidence_50.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/valkey_e2e_evidence_100.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/valkey_e2e_evidence_200.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/cleanup_report.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/dry_run_gt_200_projection.json`

## Rationale

The full P41 gate passed after adding real Valkey wrapper gates for 10, 30, 50, 100, and 200 nodes. The coverage ledger now requires and references real Valkey evidence for all real rows. The 200-node evidence records 8 density-limited nodehosts with 25 logical nodes each, and the >200 artifact remains a dry-run projection without real runtime claims. Cleanup evidence is PASS.

## Risks

- Low: Full large-scale gates are resource-sensitive and may need Docker availability and free local ports on future runs. This is expected and fail-closed.
