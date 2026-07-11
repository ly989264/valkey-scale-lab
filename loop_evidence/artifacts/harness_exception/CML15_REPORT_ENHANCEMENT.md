# CML15 Report Enhancement Harness Exception

## Defect

The previous CML15 report harness accepted report artifacts that only proved file existence and checksum integrity. The generated `index.html` and `lifecycle_timeline.svg` could pass while containing only a status sentence, so the gate did not prove quantitative analysis or data-driven visualization of operation duration, workload latency, workload availability, slot coverage, or role counts.

## Patch

- `tools/cml15_lifecycle_runner.py` now rebuilds CML15 reports from existing `lifecycle_evidence_30.json`, `operation_command_trace.jsonl`, `metrics_window.jsonl`, and `workload_window.jsonl` artifacts.
- `analysis_summary.json` now includes measured operation durations, workload latency deltas, error rate, sample coverage, slot coverage, and role count summaries.
- `reports/lifecycle_summary.csv`, `reports/report.md`, `reports/index.html`, and `reports/lifecycle_timeline.svg` are generated from the same machine-readable evidence instead of fixed status text.
- `tools/capability_matrix_gate.py` now requires CML15 reports to declare and contain the data series `operation_duration`, `workload_latency_ms`, `workload_availability_percent`, and `cluster_slot_role_counts`.
- `tests/capability_loop/test_capability_matrix_gate.py` adds a regression test for the enhanced CML15 report markers and data-series metadata.

## Before

The CML15 gate passed when `report_index.json` contained csv, markdown, html, and chart entries, even if the HTML and SVG were placeholder views.

## After

The CML15 gate fails unless each report view is tied to quantitative data series and the CSV/HTML/SVG files contain the expected data-driven report markers and sections.
