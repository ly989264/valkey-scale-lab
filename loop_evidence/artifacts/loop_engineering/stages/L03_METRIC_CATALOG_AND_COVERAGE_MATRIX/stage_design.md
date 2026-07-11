# L03_METRIC_CATALOG_AND_COVERAGE_MATRIX Stage Design

## Stage Scope

L03 creates an artifact-first metric catalog and coverage matrix from committed machine-readable evidence. The stage must normalize metrics across heterogeneous JSON/JSONL artifacts without rewriting historical phase artifacts, without reading rendered reports as metric truth, and without executing P14 or any real/fault wrapper gates.

## Required Harness

1. `schemas/artifact/metric_catalog.schema.json`
2. `schemas/artifact/coverage_matrix.schema.json`
3. `scripts/build_metric_coverage_matrix.py`
4. `tests/metrics/test_metric_catalog.py`
5. `tests/coverage/test_coverage_matrix.py`
6. `tests/ci/test_metric_coverage_gate.py`
7. static CI entries in `.github/workflows/github-coverage-gates.yml`

## Builder Behavior

The builder must:

- read only committed machine-readable JSON/JSONL artifacts and existing loop reports;
- write `artifacts/loop_engineering/reports/metric_catalog.json`;
- write `artifacts/loop_engineering/reports/coverage_matrix.json`;
- validate both outputs against their schemas;
- use deterministic curated extractors for known metric-bearing artifact types;
- include metric identity, unit, source artifact, source SHA256, source pointer, phase, run, scenario, node-count scope, evidence layer, real/dry-run flags, source artifact type, and missing semantics for every metric entry;
- preserve `MISSING`, `SKIPPED_WITH_REASON`, and `NO_BASELINE_YET` values with non-empty reasons instead of converting them to zero or PASS;
- classify generated CSV, SVG, HTML, and Markdown reports as `report_view`/view coverage only, never as source measurement artifacts;
- classify 1000-node planner/preflight data only as `1000-dry-run` with `real_valkey_coverage=false` and `dry_run_only=true`;
- return nonzero only when blocking findings exist.

## Coverage Layers

The coverage matrix must always include exactly these layers:

- `fake`
- `small-real`
- `30`
- `50`
- `100`
- `1000-dry-run`

Required surfaces:

- `cluster_build`
- `management`
- `workload`
- `observability`
- `fault`
- `failover`
- `stability`
- `cleanup`
- `scale`
- `report_visualization`

Layer rules:

- `small-real` is backed by committed P03-P11 real Valkey evidence with Valkey `9.1.x` and observed six-node scenarios.
- `30`, `50`, and `100` are backed by committed P12/P13 real Valkey evidence and scale rung artifacts.
- `1000-dry-run` is backed only by dry-run planner/resource artifacts when present; when no P14 artifact exists, this layer is represented as `SKIPPED_WITH_REASON` or equivalent dry-run-only planning coverage.
- No `1000-dry-run` entry contributes to real coverage totals.

## Required Metric Families

The initial L03 catalog must cover at least:

- cluster build: real evidence status, observed nodes, cluster state, data-path proof;
- management: operation duration and skipped management operations;
- workload: requested/achieved QPS, latency percentiles, operation counts, skipped fault windows;
- observability: cluster, Valkey, Docker, and log metric samples from JSONL;
- fault: sandbox safety checks and skipped observed impact;
- failover: promotion/failover latency and missing split-brain duration;
- stability: soak duration, restart deltas, memory growth, workload latency, baseline/no-baseline values;
- cleanup: cleanup status/duration where available;
- scale: node count, cluster known nodes, memory, command counts, role counts, placement distribution, timing;
- report/visualization: report-indexed views as views over analysis artifacts.

## Finding Semantics

Blocking findings:

- required layer missing entirely;
- required real layer classified without real Valkey evidence;
- 1000 dry-run classified as real coverage;
- source artifact missing;
- source artifact hash mismatch where declared lineage exists;
- rendered report view used as source measurement;
- required metric identity fields missing from a catalog entry;
- missing/skipped metric converted to numeric zero, PASS, or measured coverage.

Nonblocking findings:

- optional historical metadata missing when the catalog entry explicitly records `MISSING` or `SKIPPED_WITH_REASON`;
- absent P14 dry-run artifacts when the `1000-dry-run` layer records the absence with reason and real coverage remains false.

## P14 Boundary

L03 must not run P14. No L03 command may invoke `VSLAB_ALLOW_1000_DRYRUN`, `scripts/valkey_e2e_gate.py`, `scripts/fault_safety_gate.py`, or `scripts/fault_failover_gate.py`. Existing P02 dry-run planner artifacts may be represented only as dry-run planning coverage.

## Acceptance Criteria

- Previous harness remains PASS.
- The two schemas, builder, tests, CI guard, and generated JSON artifacts exist.
- `metric_catalog.json` and `coverage_matrix.json` validate against their schemas.
- Every catalog metric has name, unit, source artifact, source SHA256, scenario, node-count scope, evidence layer, and missing semantics.
- The matrix contains all required layers and surfaces.
- Real layer entries point to real Valkey evidence with `real_valkey=true`, status `PASS`, Valkey version prefix `9.1.`, and matching observed node counts.
- `1000-dry-run` entries have `real_valkey_coverage=false` and `dry_run_only=true`.
- Dedicated tests prove missing/skipped semantics, report-view boundaries, and dry-run-not-real behavior.
