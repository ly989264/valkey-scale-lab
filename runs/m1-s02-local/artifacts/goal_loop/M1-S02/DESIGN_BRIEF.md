# M1-S02 Design Brief

stage_id: M1-S02
designer: design subagent
mode: read-only

## Goal

Turn local cluster setup from “started successfully” into schema-backed bottleneck telemetry. M1-S02 must capture required setup phase durations, per-node readiness, per-nodehost process metrics, cleanup timing, analysis TopN summaries, and Chinese report sections without limiting the implementation to P13 or one scale rung.

## Relevant Paths

- `src/valkey_scale_lab/runtime/setup_timeline.py`: existing P13 timeline builder and validation primitives.
- `src/valkey_scale_lab/runtime/docker_runtime.py`: setup execution, process/nodehost startup, cluster formation, and cleanup timing.
- `src/valkey_scale_lab/cli.py`: currently instantiates timeline only for P13; M1-S02 needs common setup telemetry output.
- `src/valkey_scale_lab/analysis/summary.py`: must read and aggregate setup telemetry.
- `src/valkey_scale_lab/report/render.py`: must render Chinese setup waterfall/ranking/slow-node sections from artifacts.
- `schemas/artifact`: add common setup telemetry schema and extend downstream schemas if needed.
- `tests` and `scripts`: fixtures and stage-specific assertion gate.

## Required Artifact

Add a common `setup_telemetry.json` artifact with `artifact_type: setup_telemetry`. It must include required milliseconds metrics:

`config_parse_ms`, `config_validate_ms`, `resource_preflight_ms`, `plan_build_ms`, `port_check_ms`, `nodehost_start_ms`, `node_config_generate_ms`, `node_config_distribute_ms`, `process_start_ms`, `process_ready_wait_ms`, `cluster_meet_ms`, `cluster_slots_assign_ms`, `replica_replicate_ms`, `cluster_convergence_probe_ms`, `full_cluster_probe_ms`, `cleanup_ms`, `total_setup_ms`.

It must also include per-node/per-nodehost data:

`node_ready_ms`, `node_ping_ready_ms`, `node_cluster_known_nodes`, `node_cluster_state`, `node_role`, `node_pid`, `nodehost_start_ms`, `nodehost_process_count`, `slowest_nodes_topN`, `slowest_replica_replicate_topN`.

Missing or skipped runtime-only values must use structured `MISSING` or `SKIPPED_WITH_REASON` values with reason and impact.

## Propagation Plan

- schema: add `schemas/artifact/setup_telemetry.schema.json`.
- writer: add common setup telemetry builder/validator under runtime setup telemetry code; write artifact for local setup and blocked/dry-run/failure fixtures.
- reader/aggregator: `analysis_summary` loads `setup_telemetry.json`, aggregates phase duration ranking, slow nodes, slow replicas, and missing setup metrics.
- renderer: summary report writes Chinese sections for `集群拉起瀑布图`, `阶段耗时排序`, and `慢节点 TopN`, plus CSV/SVG outputs from setup telemetry.
- fixtures: add `tests/fixtures/setup_telemetry/` for fake success, dry-run, blocked, missing metric, and cleanup residual.
- gate: add `scripts/assert_setup_timeline_coverage.py`.
- docs/coverage: update stage coverage matrix and stage artifacts under `runs/m1-s02-local`.

## Coverage Plan

M1-S02 coverage must include:

- fake/small cluster/schema+fixture/success
- unit/small cluster/artifact writer/success
- integration/small cluster/analysis reader+aggregator/success
- smoke/small cluster/report renderer/success
- real-local 30/50/100/200 same-schema evidence or `BLOCKED_WITH_REASON`
- dry-run 200+ planning with structured skipped runtime fields
- blocked 30/50/100/200 resource/preflight path with reason
- cleanup small/200 path with `cleanup_ms`
- failure path with structured command failure, timeout, and missing metric values

## Gate Design

`scripts/assert_setup_timeline_coverage.py` must fail unless:

- `setup_telemetry.json` is schema-valid and non-empty.
- all required phase metric keys are present as numeric ms or structured reason values.
- per-node samples exist for runtime paths, or dry-run/blocked reason exists.
- 30/50/100/200 fixtures or evidence use the same schema.
- cleanup timing and residual check are present.
- analysis contains setup aggregates.
- report index references setup CSV/SVG and report Markdown/HTML contains Chinese setup sections.
- no empty JSONL, hard-coded PASS, or report-derived metrics are accepted.

## Real Heavy Strategy

Attempt the small real Valkey smoke if local ports/Docker are available. If sandboxed, write `real_heavy_gate_blocked.json` with `BLOCKED_WITH_REASON`, exact command, stderr, affected scale rungs, and no fake PASS.

## Risks

- Existing setup timeline is P13-biased and schema-limited to 50/100 nodes.
- Splitting `config_parse_ms` and `config_validate_ms` may require lower-level config instrumentation or structured reason fallback.
- Per-node readiness timing must avoid slowing large local runs.
- Report renderer is currently summary-oriented; M1-S02 must add setup-specific Chinese sections now, not defer all report work to M1-S08.
