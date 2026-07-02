# Next Stage Context: CML01_UNIFIED_OBSERVATION_AND_ARTIFACT_MODEL

CML00 PASS. Previous P00-P13 harness passes after refreshing stale gate artifacts/audits with official runners. CML01 must add schemas and validation for capability matrix rows, operation/fault events, metrics windows, workload windows, analysis summary, and report source checksums. It must reject empty metrics, zero-filled missing values, report charts without source checksums, and old artifact reuse. CML01 requires at least a minimal real Valkey data-path sample that produces complete window artifacts.
