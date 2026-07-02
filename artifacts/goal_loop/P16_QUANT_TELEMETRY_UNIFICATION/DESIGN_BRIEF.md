# DESIGN_BRIEF — P16_QUANT_TELEMETRY_UNIFICATION

## Objective

Implement the shared quantitative telemetry foundation for later management and fault stages, proven by a real 6-node Valkey gate scenario named `goal_loop_quant_telemetry`. P16 must emit canonical `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `quant_summary.json`, `phase_summary.json`, `valkey_e2e_evidence.json`, and `cleanup_report.json` under `artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/`, with no future management or fault behavior implemented in this stage.

## Repository findings

- `codex/phase_manifest.json` already defines P16 as automatic, real-Valkey-required, max 6 nodes, with gates for precheck, safety scan, compile, unit/integration tests, `assert_goal_loop_stage.py`, `scripts/valkey_e2e_gate.py`, `assert_quant_artifacts.py`, and `assert_cleanup.py`.
- `src/valkey_scale_lab.cli` routes `gate scenario` to `runtime.docker_runtime.create_scenario()` and `gate cleanup` to `cleanup_scenario()`. The P16 scenario is not yet accepted by `create_scenario()` or `_scenario_node_count_allowed()`.
- `scripts/valkey_e2e_gate.py` owns the real wrapper flow: run `python3 -m valkey_scale_lab.cli gate scenario`, load state, independently probe live endpoints with `INFO`, `CLUSTER INFO`, `CLUSTER NODES`, run a SET/GET data-path proof, then run cleanup and write `valkey_e2e_evidence.json`.
- `src/valkey_scale_lab/runtime/docker_runtime.py` already starts owned Docker containers/networks with deterministic names, writes state, configures a 6-node cluster, and performs cleanup by project/phase/run labels.
- Current P06 observability emits older `metric_sample` JSONL and older `event` JSONL: nested metric payloads, fixed timestamp strings, lower-case severities, and no P16 fields such as `scenario_name`, `sample_id`, `timestamp_unix_ms`, `monotonic_ms`, `source_type`, `source_id`, `metric_name`, `operation_id`, or `fault_id`.
- `src/valkey_scale_lab/workload/__init__.py` and `src/valkey_scale_lab/metrics/__init__.py` are placeholders. P16 should create reusable primitives there or in a small new telemetry/artifacts module rather than further enlarging `docker_runtime.py`.
- Existing workload smoke (`write_workload_report`) runs real SET/GET operations and calculates latency percentiles, but only writes `workload_report.json` with old window names. P16 needs canonical windows: `baseline`, `pre_event`, `event`, `recovery`, `post_recovery`, and `all_run`, with window boundaries as event IDs.
- P15 schemas exist for `goal_loop_event`, `goal_loop_metric_sample`, `workload_windows`, and `quant_summary`, but they are permissive. `scripts/assert_quant_artifacts.py` validates schema and missing reasons, but does not yet assert P16-specific semantics: INFO sample per live node, workload window sample count, required six window names, event boundary references, and no silent missing fields.
- `schemas/artifact/phase_summary.schema.json`, `cleanup_report.schema.json`, and `valkey_e2e_evidence.schema.json` are sufficient for P16 if artifacts contain required fields.
- Docker availability, Valkey image pull/cache status, local port availability, and 6-node resource fit are `待验证`.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `src/valkey_scale_lab/metrics/__init__.py` | implement | Add canonical metric/event record helpers, missing-data helpers, JSONL writer, monotonic/wall-clock capture, and workload-window aggregation helpers. |
| `src/valkey_scale_lab/workload/__init__.py` | implement | Add reusable low-QPS workload runner returning per-operation latency/error samples and canonical window metrics. |
| `src/valkey_scale_lab/runtime/docker_runtime.py` | modify | Accept P16 scenario, run 6-node cluster setup, call telemetry/workload helpers after cluster configuration, write P16 `phase_summary.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, and `quant_summary.json`, and preserve existing scenario behavior. |
| `scripts/assert_quant_artifacts.py` | strengthen | Add P16 semantic assertions: JSONL line validation, one Valkey INFO metric per live node, canonical event fields, six workload windows with boundary event IDs, at least one non-zero workload sample window, `MISSING` values always have reasons, cleanup pass. |
| `scripts/valkey_e2e_gate.py` | possible narrow modify | After wrapper probes, optionally verify/cite P16 telemetry artifact paths in `valkey_e2e_evidence.json` or fail if P16 telemetry files are missing. Do not make the wrapper synthesize fake runtime telemetry. |
| `schemas/artifact/goal_loop_metric_sample.schema.json` | possible strengthen | If needed, tighten timestamp/monotonic numeric expectations and missing reason semantics while staying compatible with P16 outputs. |
| `schemas/artifact/goal_loop_event.schema.json` | possible strengthen | If needed, tighten severity/timestamp semantics and keep canonical required fields. |
| `schemas/artifact/workload_windows.schema.json` | possible strengthen | If needed, require per-window workload metrics from the quant spec instead of arbitrary metrics objects. |
| `schemas/artifact/quant_summary.schema.json` | possible strengthen | If needed, add fields for event/metric/window counts and real evidence linkage. |
| `tests/unit/test_goal_loop_assertions.py` | add tests | Cover fail-closed quant assertion behavior, missing reasons, INFO-per-node requirement, non-zero workload sample requirement, and bad window boundary references. |
| `tests/integration/test_docker_runtime_contract.py` | add tests | Cover P16 scenario allow-list/node-count policy and telemetry helper integration with mocked Docker commands where feasible. |
| `tests/unit/test_cli_contract.py` | possible add tests | Ensure CLI still exposes `gate scenario` contract and no incompatible parser change is introduced. |
| `codex/gate_lock.json` | update by main/worker only after harness changes | Required if `scripts/*.py` or schema files change; must be transparent and not weaken lock coverage. |
| `artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/*` | generate via gates | Real P16 stage artifacts produced by `scripts/valkey_e2e_gate.py` and runtime telemetry. |

## Implementation plan

1. Add canonical telemetry helpers with a small API: `TelemetryRun` or equivalent should create deterministic event IDs, capture `timestamp_unix_ms` and `monotonic_ms`, write JSONL line-by-line, encode `MISSING`/`SKIPPED_WITH_REASON` with reasons, and provide helper constructors for `valkey_info`, `cluster_info`, `cluster_nodes`, `docker_stats`, `workload`, and `harness` samples.
2. Add a reusable low-QPS workload function that runs real cluster SET/GET operations against an owned node using existing `run_node_cluster_cli()`/`run_node_cli()` paths, records per-operation latency and error taxonomy, and aggregates quant-spec fields: requested/achieved QPS, ok/error ops, error rate, p50/p90/p95/p99/p999 or `MISSING` with reason, timeout/connection/MOVED/ASK/CLUSTERDOWN/READONLY/TRYAGAIN/unknown counts, and sample count.
3. Add P16 to `create_scenario()` and `_scenario_node_count_allowed()` as `("P16_QUANT_TELEMETRY_UNIFICATION", "goal_loop_quant_telemetry")` with exactly 6 nodes. After `_configure_cluster(nodes)`, run the telemetry smoke: emit lifecycle events, sample `INFO`, `CLUSTER INFO`, `CLUSTER NODES`, and Docker stats for each node, run low-QPS workload, emit canonical workload windows, write quant and phase summaries, then write state as usual for wrapper probing and cleanup.
4. For canonical windows in this smoke stage, create all six windows. `all_run` and at least `baseline` should contain measured workload/sample data; windows with no management/fault trigger should use explicit `SKIPPED_WITH_REASON`/`MISSING` subfields with reasons where the metric is not applicable, not omitted or zero invented as a measurement.
5. Generate `quant_summary.json` from the produced artifacts only. Include artifact refs, counts of events/metrics/windows, node count, real-Valkey claim true, management/fault claims false, and a `missing_data` list for deliberately absent management/fault-only measurements.
6. Generate `phase_summary.json` for P16 with all required artifact paths, no fake claims, known missing metrics encoded with reasons, and resource/safety risks.
7. Strengthen `assert_quant_artifacts.py` for real stages and especially P16. It should fail closed on missing files, empty JSONL, invalid JSONL line, missing reasons, no live-node INFO samples, no workload sample window, non-canonical windows, or cleanup leftovers.
8. Keep future stages out of scope: no remove/reshard/rebalance/rolling restart, failover curve, network fault, partition, or split-brain implementation.

## Harness, schema, and gate plan

- Required P16 manifest gates are already present. Worker should not add recursive `codex_gate.py run/postcheck` gates.
- Run and preserve:
  - `python3 scripts/codex_gate.py precheck --phase P16_QUANT_TELEMETRY_UNIFICATION`
  - `python3 scripts/safety_scan.py`
  - `python3 -m compileall -q scripts src`
  - `python3 -m pytest -q tests/unit tests/integration`
  - `python3 scripts/assert_goal_loop_stage.py --phase P16_QUANT_TELEMETRY_UNIFICATION`
  - `python3 scripts/valkey_e2e_gate.py --phase P16_QUANT_TELEMETRY_UNIFICATION --config templates/configs/single_mac_6node.yaml --scenario goal_loop_quant_telemetry --out artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/valkey_e2e_evidence.json --min-nodes 6 --require-data-path`
  - `python3 scripts/assert_quant_artifacts.py --phase P16_QUANT_TELEMETRY_UNIFICATION`
  - `python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/cleanup_report.json`
- If schemas are strengthened, ensure `scripts/schema_validator.py` supports the used schema keywords; avoid unsupported JSON Schema features such as `if/then` unless the validator is extended and tested.
- Any change to `scripts/*.py`, `schemas/**/*.json`, docs, templates, or manifest requires a legitimate `codex/gate_lock.json` refresh after tests prove the change strengthens or preserves harness requirements.

## Test plan

- Unit tests for telemetry helpers: event IDs are stable/non-empty, monotonic values are numeric and nondecreasing within a run, JSONL lines include every required field, and `MISSING`/`SKIPPED_WITH_REASON` require non-empty reasons.
- Unit tests for workload aggregation: percentiles are computed from actual latency samples, empty latency sets produce `MISSING` with reason, error taxonomy counts timeout/connection/redirection/cluster errors, and `p999` is present or explicitly missing.
- Unit tests for `assert_quant_artifacts.py`: fails on missing P16 files, empty JSONL, invalid JSONL, missing `missing_reason`, no `valkey_info` per node, no non-zero workload window, missing canonical windows, and cleanup `FAIL`; passes on a minimal valid synthetic artifact set.
- Integration tests for P16 scenario allow-list and node-count policy in `docker_runtime`, ideally using monkeypatched Docker commands for fast non-real tests.
- Real gate validation through the manifest P16 run. If Docker or Valkey image access fails, record as blocked rather than generating fake artifacts.

## Required artifacts

- `artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/phase_summary.json`
- `artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/valkey_e2e_evidence.json`
- `artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/cleanup_report.json`
- `artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/events.jsonl`
- `artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/metrics_timeseries.jsonl`
- `artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/workload_windows.json`
- `artifacts/phases/P16_QUANT_TELEMETRY_UNIFICATION/quant_summary.json`
- Gate logs under `artifacts/gates/P16_QUANT_TELEMETRY_UNIFICATION/`
- Later main/review artifacts: `WORKER_SUMMARY.md`, `REVIEW.md`, audit markdown/json, and completion only after gates pass.

## Safety considerations

- Use only existing owned Docker/container/network controls with project labels. Do not modify host firewall, routing, PF, nftables, iptables, host interfaces, or unrelated processes.
- P16 must remain capped at 6 nodes and must not change defaults toward 1000 or use P14/P21 exception logic.
- Cleanup must continue to use deterministic phase/run labels and fail if owned resources remain.
- Telemetry must never replace real wrapper evidence: `valkey_e2e_evidence.json` must still be produced by `scripts/valkey_e2e_gate.py` with independent live endpoint probes and Valkey 9.1.x version data.
- Missing metrics must be encoded with `MISSING`, `SKIPPED_WITH_REASON`, or `UNSUPPORTED_WITH_REASON` plus reasons. Do not use `null`, empty string, omitted fields, or invented zeroes for missing measurements.

## Resource considerations

- P16 uses `templates/configs/single_mac_6node.yaml`, expected 6 local Docker containers, ports 7000-7005 and 17000-17005, and image `valkey/valkey:9.1.0`.
- Docker daemon availability, image availability/pull, port availability, CPU/memory headroom, and cleanup timing are `待验证`.
- No 30/50/100/200-node resource preflight is required for P16, but failures at 6 nodes are real blockers and must not be hidden by fake artifacts.

## `待验证`

- Whether Docker is running and can start/pull `valkey/valkey:9.1.0` in the current environment.
- Whether the current host has ports 7000-7005 and 17000-17005 free at gate time.
- Whether direct host probes in `scripts/valkey_e2e_gate.py` can observe all six nodes before cleanup for the P16 scenario.
- Whether current schema permissiveness should be tightened in schemas or entirely enforced in `assert_quant_artifacts.py`; prefer the smallest strengthening that keeps P15/P16 gates stable.
- Whether P16 should reuse existing `write_workload_report()` internally or replace it with a new canonical workload runner; avoid breaking P05 artifacts either way.
- Whether wrapper evidence should include telemetry artifact refs or leave cross-artifact linkage only in `quant_summary.json`.

## Worker instructions

- Implement only this stage.
- Do not commit.
- Do not weaken harness or safety rules.
- Keep P16 at 6 real Valkey nodes and do not implement future management/fault stages.
- Prefer reusable telemetry/workload helpers over ad hoc writes in `docker_runtime.py`, but keep the patch small enough for the P16 scope.
- Treat Docker/resource failures as blocked-stage evidence, not as permission to emit fake PASS artifacts.
