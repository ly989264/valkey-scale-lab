# L02_EVIDENCE_PROVENANCE_DAG Stage Design

## Stage Scope

L02 adds a static artifact provenance DAG for committed evidence. It must prove that analysis, report, scale, stability, timing, and visualization-like outputs trace to machine-readable source artifacts with recomputed SHA256 values and available metadata. The graph is an audit artifact; it must not run P14, real Valkey gates, fault gates, or mutate historical phase/gate/audit artifacts.

## Required Harness

1. `schemas/artifact/provenance_graph.schema.json`
2. `scripts/build_provenance_graph.py`
3. `tests/provenance/test_provenance_graph.py`
4. `tests/ci/test_provenance_graph_gate.py`
5. Static CI entries in `.github/workflows/github-coverage-gates.yml`

## Graph Behavior

The builder must:

- read committed artifacts under the repository root;
- write `artifacts/loop_engineering/reports/provenance_graph.json`;
- compute SHA256 from disk for every existing node;
- model source-of-truth JSON/JSONL artifacts separately from rendered report views;
- mark HTML, Markdown, SVG, and report-indexed CSV files as `source_of_truth=false`;
- validate P09 report outputs against `report_index.json` hashes;
- validate P09 analysis `source_artifacts` hashes against actual committed source files;
- infer deterministic edges for legacy artifacts that lack explicit `source_artifacts`, such as P11 stability and P12/P13 scale reports;
- include P13 despite its historical gate command drift;
- keep P14 out of automatic real evidence coverage; if dry-run/planner artifacts are represented, they must be typed as dry-run and not real coverage;
- emit findings for missing source artifacts, hash mismatches, missing metadata, report views used as sources, cycles, or missing edge endpoints;
- exit nonzero only when blocking findings exist.

## Required Coverage

- P09 report views must trace to `report_index.json`, `analysis_summary.json`, and the P08 source artifacts listed by `analysis_summary.json`.
- P11 `stability_report.json` must trace to `stability_metrics.jsonl`, `stability_baseline_comparison.json`, `valkey_e2e_evidence.json`, `cleanup_report.json`, and `phase_summary.json`.
- P12 `scale_ladder_report.json` must trace to 10/30 resource preflight, real evidence, scale rung, cleanup, and phase summary artifacts.
- P13 `scale_ladder_report.json` must trace to 50/100 resource preflight, real evidence, scale rung, cleanup, P13 timing breakdowns, and phase summary artifacts.
- P13 timing nodes must trace to available setup timeline, runtime timing breakdown, real evidence, and cleanup artifacts where present.

## Finding Semantics

Blocking findings:

- missing required source artifact;
- source or report view SHA mismatch;
- graph cycle;
- edge endpoint missing;
- rendered report view used as a source-of-truth upstream;
- P14 or 1000-node dry-run represented as real Valkey coverage;
- required graph coverage missing for P09/P11/P12/P13.

Nonblocking findings may record missing optional metadata when the historical source artifact exists and the graph explicitly marks the missing field as `MISSING`.

## P14 Boundary

L02 must not run P14. No L02 command may invoke `VSLAB_ALLOW_1000_DRYRUN`, `scripts/valkey_e2e_gate.py`, `scripts/fault_safety_gate.py`, or `scripts/fault_failover_gate.py`. Dry-run planner artifacts are never real evidence.

## Acceptance Criteria

- Previous harness remains PASS.
- The provenance schema, builder, tests, CI guard, and graph artifact exist.
- The generated graph validates against `schemas/artifact/provenance_graph.schema.json`.
- The graph status is PASS for the current repository with zero blocking findings.
- P09/P11/P12/P13 coverage exists with verified hashes and source/view distinctions.
- Fixture tests prove missing sources, hash drift, cycles, and report-view misuse are blocking.
- Existing historical artifacts are not edited to add provenance retroactively.
