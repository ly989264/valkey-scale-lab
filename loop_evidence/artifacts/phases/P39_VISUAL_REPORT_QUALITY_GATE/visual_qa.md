# P39 Visual QA

Static visual QA status: PASS

- Markdown and HTML reports were generated from P38 machine-readable artifacts only.
- All required section headings are present in `final_report.md` and represented in `report_index.json`.
- All 10 required SVG chart assets are present, non-empty, and referenced from the report index.
- Charts that cannot be sourced exactly from P38 values render `MISSING` with reasons rather than substituted values.
- Above-200 rows are labeled dry-run-only in the report body and resource chart.
- `report_quality_report.json` records the automated section, asset, token, source, and coverage-total checks.

## Checked chart IDs

| Chart ID | Path |
| --- | --- |
| coverage_heatmap | artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/coverage_heatmap.svg |
| management_wall_ms_by_operation_and_scale | artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/management_wall_ms_by_operation_and_scale.svg |
| management_convergence_ms_by_operation_and_scale | artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/management_convergence_ms_by_operation_and_scale.svg |
| failover_promotion_latency_curve_50_100_200 | artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/failover_promotion_latency_curve_50_100_200.svg |
| failover_cluster_recovery_latency_curve_50_100_200 | artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/failover_cluster_recovery_latency_curve_50_100_200.svg |
| workload_qps_ratio_by_fault_and_scale | artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/workload_qps_ratio_by_fault_and_scale.svg |
| workload_p99_delta_by_fault_and_scale | artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/workload_p99_delta_by_fault_and_scale.svg |
| error_rate_delta_by_fault_and_scale | artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/error_rate_delta_by_fault_and_scale.svg |
| resource_usage_by_scale | artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/resource_usage_by_scale.svg |
| cleanup_status_by_stage | artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/cleanup_status_by_stage.svg |

## Checked section IDs

| Section ID | Title |
| --- | --- |
| executive_summary | Executive summary |
| strict_coverage_heatmap | Strict coverage heatmap |
| resource_preflight_and_scale_feasibility | Resource preflight and scale feasibility |
| cluster_lifecycle_summary | Cluster lifecycle summary |
| management_operation_matrix | Management operation matrix |
| management_latency_and_convergence_charts | Management latency and convergence charts |
| fault_failover_matrix | Fault/failover matrix |
| failover_latency_curves_for_50_100_200 | Failover latency curves for 50/100/200 |
| fault_period_workload_impact | Fault-period workload impact |
| partition_and_split_brain_findings | Partition and split-brain findings |
| telemetry_completeness | Telemetry completeness |
| cleanup_and_leftover_resource_summary | Cleanup and leftover-resource summary |
| above_200_dry_run_support_summary | >200 dry-run support summary |
| missing_data_and_blocked_row_appendix | Missing-data and blocked-row appendix |
| source_artifact_provenance_index | Source artifact provenance index |
