role: design
agent_invocation: real_subagent
stage_id: H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING
source_commit_before: 19bfc77e70df685111075c416cce8aeca5640f51
source_commit_after: MISSING

# DESIGN_BRIEF

## Recommendation

Implement H08 as a dedicated C10 system-metrics hardening gate, not as the current generic capability wrapper. The current repository should remain honestly blocked for `system_metrics.real_exact.{30,50,100,200}` unless it contains real exact-scale `system_metrics_report.json` plus `system_metrics_timeseries.jsonl` bundles with lifecycle windows, per-node identifiers, real Valkey 9.1.x evidence, and numeric high-value resource coverage.

## Current Gap

- `scripts/m1h/assert_system_metrics_real_windows.py` delegates to the generic capability gate, so it only evaluates manifest claim shape.
- `scripts/m1h/manifest.py` currently treats generic `metrics_timeseries.jsonl` rows as system metrics when rows exist. The 50/100/200 sources are workload, management, and fault-impact rows, not C10 resource samples.
- `system_metrics.real_exact.30` is fixture-backed and must remain non-promotable.
- The H08 stage exit wiring is absent from `scripts/m1h/assert_stage_exit.py`.
- Current system metric claims have `core_metrics_present: true` even when high-value CPU/RSS/network/Valkey INFO/cluster INFO coverage is not proven.

## Manifest Design

- Add H08 constants in `scripts/m1h/manifest.py`:
  - required claim scales: 30, 50, 100, 200;
  - required lifecycle windows: setup, workload, cleanup for all scales; management for scales with management exact-scale claims; fault_or_failover for scales with fault timeline exact-scale claims;
  - accepted source types: `system_process`, `system_network`, `container_stats`, `docker_stats`, `valkey_info`, and `cluster_info`;
  - high-value metric groups: CPU, RSS/memory, network IO, Valkey INFO, cluster INFO.
- Extend `CAPABILITY_FILES["system_metrics"]` to include `valkey_e2e_evidence.json` and prefer `system_metrics_report.json` plus `system_metrics_timeseries.jsonl` over generic metric files.
- Add `evaluate_system_metrics_claim(root, scale, paths, evidence)` and store the full result under `diagnostics.system_h08_acceptance`.
- Set `semantic_checks["hardening_stage_accepted"]` for system metrics only from `diagnostics.system_h08_acceptance.accepted is True`.
- Promote `system_metrics` to `REAL_EXACT_SCALE` only when H08 diagnostics accept the claim. Otherwise produce `BLOCKED_WITH_REASON` with reasons that name missing windows, missing files, missing node coverage, invalid row fields, or missing high-value numeric coverage.

## C10 Row Semantics

A C10 timeseries row that contributes to PASS must be a JSON object with:

- `schema_version: v1`;
- exact `node_count` or `scale` equal to the claim scale;
- top-level `node_id` or `logical_node_id`;
- canonical `lifecycle_window`;
- accepted system-oriented `source_type`;
- `metric_name`;
- numeric `metric_value` for observed samples, or `metric_value` encoded as `MISSING` or `SKIPPED_WITH_REASON` with a non-empty `missing_reason`;
- `timestamp_unix_ms` and numeric `monotonic_ms`;
- no fixture clock/source markers for real PASS.

Rows with `source_type` such as workload, management, fault, benchmark, or timeline may be cited as anchors, but they must not satisfy system-metric coverage. Workload QPS/latency/error rows and fault latency rows should be classified as non-system rows and counted in diagnostics as rejected sources.

## Report Semantics

Validate `system_metrics_report.json` against `schemas/artifact/system_metrics_report.schema.json`, then cross-check it against the timeseries:

- `status` must be PASS only for accepted exact-scale claims;
- `node_count` or `scale` must match the claim scale;
- `sample_count` must match parsed C10 rows closely enough to prevent report-only claims;
- `lifecycle_windows` and `coverage.rows_by_window` must cover required windows;
- `coverage.rows_by_node` or parsed unique node ids must cover the exact node count;
- `missing_metrics` entries must use structured `MISSING`, `SKIPPED_WITH_REASON`, or `UNSUPPORTED_WITH_REASON` with reasons;
- `source_refs` must resolve to the local bundle files and real Valkey evidence.

## Numeric Coverage Threshold

For PASS, require numeric coverage in every required high-value group:

- CPU: at least one numeric CPU utilization metric, such as aggregate CPU percent or user/system CPU percent;
- RSS/memory: numeric process RSS or Valkey memory metrics;
- network IO: numeric RX/TX bytes or Valkey total network bytes;
- Valkey INFO: numeric client, command, memory, or persistence counters;
- cluster INFO: cluster state/known node/slot metrics encoded numerically or with a documented machine-readable state mapping.

Missing or skipped entries may document unsupported metrics, but a claim must fail or block if any high-value group has no numeric samples across required windows. For scales 50/100/200, management and fault/failover windows must also meet this group threshold. For scale 30, any omitted management or fault/failover window must be recorded as not applicable by the evaluator, while setup, workload, and cleanup remain mandatory.

## Dedicated Gate Design

Replace `assert_system_metrics_real_windows.py` with a H08-specific gate modeled after H07:

- read `runs/m1-hardening/evidence_manifest.json`;
- inspect `system_metrics` claims for 30/50/100/200;
- PASS the hardening gate when every claim is either safely accepted or explicitly blocked with H08 diagnostics;
- fail any system-metrics claim that reports PASS without `diagnostics.system_h08_acceptance.accepted`;
- fail any PASS backed by fixtures, legacy-only evidence, report-only evidence, generic workload/fault rows, source paths without `system_metrics_timeseries.jsonl`, or missing Valkey 9.1.x proof;
- write `extra.system_metrics_claim_status`, `passed_claims`, `blocked_claims`, rejected row counts, required windows, and high-value metric groups.

The expected current gate artifact should be `status: PASS` for the H08 gate itself, with `system_metrics_claim_status: BLOCKED_WITH_REASON`, zero passed system-metrics claims, and four blocked claim summaries.

## Stage Exit Wiring

- Add `H08_REQUIRED_GATE_RESULTS` in `scripts/m1h/assert_stage_exit.py`.
- Register `H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` in `STAGE_REQUIRED_GATE_RESULTS`.
- Update tests so H08 stage exit blocks until `assert_system_metrics_real_windows.json` exists and is PASS.

## Tests

Add focused tests in `tests/m1h/test_gate_framework.py`:

- valid exact-scale system metrics bundle promotes to `REAL_EXACT_SCALE`;
- fixture-only system metrics remains blocked and non-promotable;
- generic workload-only `metrics_timeseries.jsonl` remains blocked even when rows are numerous;
- fault/workload latency rows do not count toward C10 high-value resource coverage;
- report-only bundle fails because no matching C10 timeseries exists;
- missing lifecycle window blocks the claim;
- rows missing node id, lifecycle window, timestamp, monotonic time, or exact node count fail;
- high-value group fully `MISSING` or `SKIPPED_WITH_REASON` blocks PASS;
- unique node coverage below exact scale blocks PASS;
- Valkey evidence missing, non-real, wrong scale, or non-9.1.x blocks PASS;
- crafted manifest PASS without H08 diagnostics fails the dedicated gate;
- blocked claims must include H08 diagnostic reasons;
- H08 stage exit requires the system metrics gate artifact.

## Gate Commands

Run the common gates plus H08-specific validation:

```text
PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h08 python3 -m compileall -q scripts src tests
python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h
python3 scripts/m1h/build_evidence_manifest.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING --out runs/m1-hardening/evidence_manifest.json
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING
python3 scripts/m1h/assert_system_metrics_real_windows.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING
python3 scripts/m1h/assert_stage_exit.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING
```

## Acceptance Criteria

- System-metrics PASS requires real exact-scale H08 diagnostics, not manifest fields alone.
- Fixture-only rows, generic metrics files, workload/fault rows, legacy evidence, and report-only artifacts cannot promote a claim.
- Missing high-value CPU/RSS/network/Valkey INFO/cluster INFO coverage blocks the exact-scale claim with reasons.
- Current 30/50/100/200 claims remain blocked until real C10 bundles exist.
- H09 report-input quality can rely on H08 semantics to reject weak system-metrics sources.

## Review Risks

- Do not let generic `metrics_timeseries.jsonl` rows satisfy C10 without system-oriented source types and lifecycle fields.
- Do not let schema validity replace semantic coverage checks.
- Do not hide skipped high-value resource metrics behind a report PASS.
- Do not allow a manually crafted manifest PASS without H08 acceptance diagnostics.
