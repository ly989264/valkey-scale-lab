# M1-S01 Design Brief

stage_id: M1-S01
designer: design subagent
mode: read-only

## Goal

Turn the repository into a run-oriented experiment platform. New milestone1 runs must default to `runs/<run_id>/artifacts|logs|reports|state`, emit complete `run_metadata.json`, write a `run_manifest.json`, keep explicit legacy paths compatible, and ensure analysis/report can read metadata through the manifest.

## Relevant Paths

- `src/valkey_scale_lab/runtime/docker_runtime.py`: scenario lifecycle, state, cleanup, and artifact writes.
- `src/valkey_scale_lab/planner/plan.py`: dry-run planning path.
- `src/valkey_scale_lab/resource.py`: preflight and blocked-run path.
- `src/valkey_scale_lab/analysis/summary.py`: artifact reader and analysis aggregator.
- `src/valkey_scale_lab/report/render.py`: summary report renderer and report index.
- `schemas/artifact`: artifact schemas.
- `tests`: unit/integration/report coverage.

## Propagation Plan

- schema: add `run_metadata.schema.json` and `run_manifest.schema.json`; allow analysis/report index metadata refs.
- writer: centralize run layout, metadata, manifest, artifact/log/report/state roots, hash helpers, and structured missing values.
- reader/analyzer: resolve input as run root, manifest path, or legacy artifact dir; include metadata refs and findings.
- renderer: include run metadata in report index and visible report output.
- fixture/tests: cover fake, dry-run, blocked, failure, cleanup, report, and legacy compatibility paths with structured reasons.
- gate: add `scripts/assert_run_metadata_contract.py` to validate layout, schemas, metadata completeness, manifest/report linkage, and no new default legacy placement.

## Coverage Matrix Draft

| behavior | execution_shape | scale_rung | functional_path | data_path | outcome | status |
|---|---|---|---|---|---|---|
| default run directory | unit/fake | small_cluster | config/plan/runtime | schema/writer | success | PASS target |
| complete metadata | unit/smoke | small_cluster | cluster_setup | schema/writer/reader | success | PASS target |
| dry-run metadata | unit/integration | scale_200_plus_dry_run_planning | plan/resource_preflight | writer/reader | SKIPPED_WITH_REASON | PASS target |
| blocked run artifact | unit | scale_30/50/100/200 | resource_preflight | writer/schema | BLOCKED_WITH_REASON | PASS target |
| failure path metadata | integration | small_cluster | cluster_setup | writer/cleanup | command_failure | PASS target |
| cleanup awareness | unit/integration | small_cluster/scale_200 | cleanup | reader/writer | cleanup_residual | PASS target |
| report metadata ref | report test | small_cluster | report | renderer/index | success/report_input_missing | PASS target |
| legacy compatibility | integration | existing phases | analysis/report | reader/regression | success | PASS target |

## Risks

- Weak schemas with `additionalProperties` can hide missing required metadata unless gate checks required fields directly.
- Real Docker/Valkey gates may be blocked locally; blocked artifacts must be explicit.
- Broad edits to large runtime files could break historical gates, so the first implementation should introduce a common helper and minimally wire safe paths.
