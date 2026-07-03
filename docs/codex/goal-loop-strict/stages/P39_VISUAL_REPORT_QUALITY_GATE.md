# P39_VISUAL_REPORT_QUALITY_GATE — Visual Report Quality Gate

## Purpose

Generate the final human-facing report and verify it is comprehensive, visually correct, and free of broken or misleading display states.

## Required inputs

P39 consumes P38 analysis artifacts and P30-P37 provenance artifacts. It must not invent new quantitative values.

## Required outputs

```text
artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/phase_summary.json
artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json
artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_quality_report.json
artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/final_report.md
artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/final_report.html
artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/assets/*
artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/visual_qa.md
artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/quant_summary.json
```

## Required report sections

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

## Required gates

```text
python3 scripts/assert_report_quality.py --phase P39_VISUAL_REPORT_QUALITY_GATE --report-index artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json
python3 scripts/assert_analysis_provenance.py --phase P39_VISUAL_REPORT_QUALITY_GATE --report-index artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json
python3 scripts/assert_no_bypass.py --phase P39_VISUAL_REPORT_QUALITY_GATE
```

## Pass criteria

P39 passes only when:

```text
Markdown and HTML reports exist
all required sections exist
all required charts exist and are non-empty
all assets referenced by report_index exist
no NaN/Infinity/undefined/Traceback/TODO/PLACEHOLDER appears
all charts and tables have source artifact references
coverage row totals match P38 analysis
MISSING appears only with reason
report quality gate passes
review visually inspects report structure and cites report_quality_report.json
```

## Blocking conditions

```text
required section missing
chart or image broken
report displays NaN/null/undefined
empty table presented as successful data
source provenance missing
visual QA not performed
```
