# 11_ANALYSIS_VISUAL_REPORT_SPEC.md — Analysis and Visual Report Contract

## Purpose

The final report must be useful to a human and traceable to machine artifacts. It must be comprehensive, visually coherent, and free of rendering defects.

## Analysis inputs

P38 must consume only validated artifacts from P30-P37 and the coverage registry from P28. It must not scrape raw logs for final values unless those logs were converted into schema-validated artifacts first.

## Required analysis outputs

P38 must produce:

```text
cross_scale_analysis_summary.json
coverage_heatmap_table.csv
management_latency_table.csv
management_convergence_table.csv
failover_curve_table.csv
fault_impact_table.csv
workload_window_table.csv
resource_usage_table.csv
cleanup_table.csv
missing_data_table.csv
analysis_provenance.json
```

Every derived row must contain source artifact paths and coverage IDs.

## Required report sections

P39 must produce Markdown and HTML reports with at least:

```text
Executive summary
Strict coverage heatmap
Resource preflight and scale feasibility
Cluster lifecycle summary
Management operation matrix
Management latency and convergence charts
Fault/failover matrix
Failover latency curves for 50/100/200
Fault-period workload impact
Partition and split-brain findings
Telemetry completeness
Cleanup and leftover-resource summary
>200 dry-run support summary
Missing-data and blocked-row appendix
Source artifact provenance index
```

## Required charts

At minimum:

```text
coverage_heatmap
management_wall_ms_by_operation_and_scale
management_convergence_ms_by_operation_and_scale
failover_promotion_latency_curve_50_100_200
failover_cluster_recovery_latency_curve_50_100_200
workload_qps_ratio_by_fault_and_scale
workload_p99_delta_by_fault_and_scale
error_rate_delta_by_fault_and_scale
resource_usage_by_scale
cleanup_status_by_stage
```

Charts must be derived from CSV/JSON artifacts, not handwritten.

## Visual quality gate

P39 must implement or strengthen a gate equivalent to:

```text
python3 scripts/assert_report_quality.py --report-index artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json
```

The gate must fail on:

```text
missing HTML or Markdown report
missing chart asset
zero-byte chart asset
broken internal link
empty required table
mismatched table/chart row counts
NaN
Infinity
undefined
None used as a display value
Traceback
TODO
PLACEHOLDER
chart title missing
axis labels missing where applicable
missing source artifact citation for a section
```

`MISSING` is allowed only in the missing-data table or cells explicitly marked with a reason.

## Report aesthetics requirements

The report should use a consistent layout:

```text
clear title and run metadata
summary cards for core outcomes
heatmaps for coverage
small multiples or grouped charts for scale comparison
tables with fixed column order
human-readable status badges derived from data
appendices for detailed rows
```

A report that is technically generated but confusing, empty, or misleading is not complete.

## Regression requirements

P39 and P40 must add regression checks so future changes cannot silently break:

```text
schema compatibility
required report sections
required chart count
source provenance
missing-data rendering
coverage-row totals
```
