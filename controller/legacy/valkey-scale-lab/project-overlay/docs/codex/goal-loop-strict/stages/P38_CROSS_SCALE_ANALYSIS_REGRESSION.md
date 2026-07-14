# P38_CROSS_SCALE_ANALYSIS_REGRESSION — Cross-Scale Quantitative Analysis and Regression

## Purpose

Aggregate validated P30-P37 artifacts into report-ready tables and regression baselines. This stage performs analysis, not new large-cluster execution.

## Required inputs

P38 must read only validated artifacts from:

```text
P30_MANAGEMENT_MATRIX_50_REAL
P31_MANAGEMENT_MATRIX_100_REAL
P32_MANAGEMENT_MATRIX_200_REAL
P33_FAULT_FAILOVER_MATRIX_50_REAL
P34_FAULT_FAILOVER_MATRIX_100_REAL
P35_FAULT_FAILOVER_MATRIX_200_REAL
P36_FULL_FLOW_E2E_50_100_200_REAL
P37_200_PLUS_DRY_RUN_SUPPORT
artifacts/coverage/strict_coverage_registry.json
```

## Required outputs

```text
artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/phase_summary.json
artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/cross_scale_analysis_summary.json
artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/coverage_heatmap_table.csv
artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/management_latency_table.csv
artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/management_convergence_table.csv
artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/failover_curve_table.csv
artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/fault_impact_table.csv
artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/workload_window_table.csv
artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/resource_usage_table.csv
artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/cleanup_table.csv
artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/missing_data_table.csv
artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/analysis_provenance.json
artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/regression_baseline.json
artifacts/phases/P38_CROSS_SCALE_ANALYSIS_REGRESSION/quant_summary.json
```

## Required gates

```text
python3 scripts/assert_analysis_provenance.py --phase P38_CROSS_SCALE_ANALYSIS_REGRESSION
python3 scripts/assert_quant_completeness.py --phase P38_CROSS_SCALE_ANALYSIS_REGRESSION --category analysis
python3 scripts/assert_coverage_registry.py --phase P38_CROSS_SCALE_ANALYSIS_REGRESSION --require-final-real-scales
python3 scripts/assert_no_bypass.py --phase P38_CROSS_SCALE_ANALYSIS_REGRESSION
```

## Pass criteria

P38 passes only when:

```text
all required source stages have PASS evidence
all real 50/100/200 rows are represented in analysis tables
all >200 rows are represented as dry-run-only
no analysis value lacks source provenance
missing-data table lists every MISSING value with reason
derived percentiles and deltas declare method
regression baseline is generated from current artifacts
```

## Blocking conditions

```text
analysis omits a required scale or row
analysis reads unvalidated logs as final data
source provenance missing
NaN/null/undefined appears in analysis outputs
fake or dry-run data is mixed into real 50/100/200 metrics
```
