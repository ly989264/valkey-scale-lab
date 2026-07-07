# REVIEW - P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE

## Scope reviewed

Fresh-context review after the latest telemetry fix. I inspected the P43 stage protocol inputs, prior P43 review findings P43-R1 through P43-R4, the current diff, gate result and logs, P43 phase artifacts, schemas, assertion scripts, real Valkey evidence, cleanup reports, and audit requirements. I did not implement code fixes.

## Documents and artifacts read

- `AGENTS.md`, `CODEX_START_HERE.md`, `CODEX_GOAL_LOOP_START.md`
- `docs/codex/02_PHASES.md`, `docs/codex/04_AUDITOR.md`
- Goal-loop docs `00_INDEX.md` through `10_AUDIT_AND_COMMIT_POLICY.md`
- `docs/codex/goal-loop/stages/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE.md`
- `artifacts/goal_loop/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/CONTEXT_RELOAD.md`
- `artifacts/goal_loop/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/DESIGN_BRIEF.md`
- `artifacts/goal_loop/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/WORKER_SUMMARY.md`
- `artifacts/goal_loop/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/FIX_LOG.md`
- `artifacts/gates/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/gate_result.json`
- P43 logs and artifacts under `artifacts/gates/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/` and `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/`

## Diff review

The P43 changes centralize `cluster-node-timeout` configuration, add global/profile/scenario/CLI source tracking, propagate timeout fields into planner/runtime/state/generated config/evidence artifacts, add an explicit timeout matrix runner, and strengthen P43 gates. Prior findings are resolved:

- P43-R1: failover timeout now resolves from effective config by default and records CLI overrides explicitly.
- P43-R2: `config_validation_report.schema.json` now requires requested/effective/source timeout fields.
- P43-R3: `codex/gate_lock.json` now locks the P43 stage doc, scripts, builder, runner, and schemas.
- P43-R4: `events.jsonl`, `metrics_timeseries.jsonl`, and `workload_windows.json` are schema-valid and now have manifest gates.

## Gate review

| Gate/check | Evidence | Result |
|---|---|---:|
| Full P43 run | `artifacts/gates/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/gate_result.json` has `status: PASS` | PASS |
| Safety scan | `stdout/safety_static_scan.log`: `PASS safety_scan` | PASS |
| Compile | `scripts_compile` gate exit 0 | PASS |
| Focused tests | `cluster_timeout_tests.log`: `115 passed` | PASS |
| Real Valkey 10/30/50/100/200 | `valkey_e2e_evidence*.json` exact requested counts, `real_valkey=true`, Valkey `9.1.0`, cluster state `ok` | PASS |
| P43 assertions | `cluster_timeout_config`, `no_hidden_timeout_override`, `timeout_matrix_artifacts` logs all PASS | PASS |
| Telemetry schemas | Event, metric, and workload-window schema gates all PASS; I reran the three validations | PASS |

## Artifact/schema review

Required P43 artifacts are present and covered by manifest schemas. I independently reran:

- `python3 scripts/validate_json_schema.py --schema schemas/artifact/event.schema.json --instance artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/events.jsonl --jsonl`
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/metric_sample.schema.json --instance artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/metrics_timeseries.jsonl --jsonl`
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/workload_windows.schema.json --instance artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/workload_windows.json`

All three returned PASS. `generated_valkey_configs_manifest.json` reports 200 configs with `cluster-node-timeout 30000` and source provenance present. `run_state.json` records `effective_cluster_node_timeout_ms=30000` and `cluster_node_timeout_source=global`.

## Real Valkey evidence review

The 10, 30, 50, 100, and 200 node evidence files all report `status=PASS`, `probe_result=PASS`, `real_valkey=true`, observed node count equal to the requested scale, `cluster_state_observed=ok`, Valkey versions starting with `9.1.`, and per-node timeout evidence of `30000` from `global`. Greater-than-200 evidence is limited to `dry_run_gt_200_projection.json` with `real_valkey=false`.

## Safety review

No reviewed P43 path uses sudo, host firewall/routing/interface mutation, or unrelated process control. Fault/failover paths remain project-scoped. The hidden-timeout assertion passes, and the timeout matrix default artifact records `NOT_RUN_WITH_REASON` instead of fabricated PASS values.

## Quantitative coverage review

P43 covers fake/schema tests, smoke 10, real 30/50/100/200, and greater-than-200 dry-run projection with timeout source evidence. The timeout matrix supports the required timeout values and does not auto-run all large cells. The telemetry artifacts now validate and encode the config-only workload window as an artifact-derived `all_run` window.

## Cleanup review

Aggregate and per-scale cleanup reports are `PASS` with `resources_remaining=[]`.

## Blocking findings

| ID | Severity | Finding | Required fix |
|---|---|---|---|
| None | - | No blocking findings remain. | - |

## Non-blocking notes

- The full failover RTO timeout matrix is implemented as explicit opt-in and was not executed by default, matching the P43 stage rule.
- I created the required audit artifacts because they were absent and the review decision is PASS.

## Decision

Decision: PASS
