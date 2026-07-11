# REVIEW — P41_NODEHOST_DENSITY_GLOBAL_CONFIG

## Scope reviewed

Fresh-context re-review after the initial P41 review failure. I inspected the required review prompt/template, goal-loop documents, P41 stage contract, context reload, design brief, updated worker summary addendum, current git diff/status, current full P41 gate result, gate stdout/stderr inventory, real Valkey evidence artifacts for 10/30/50/100/200, coverage ledger, cleanup reports, >200 dry-run projection, assertion scripts, source changes for config/planner/runtime/preflight, and focused tests.

## Documents and artifacts read

- `AGENTS.md`
- `CODEX_START_HERE.md`
- `CODEX_GOAL_LOOP_START.md`
- `docs/codex/goal-loop/00_INDEX.md`
- `docs/codex/goal-loop/01_GOAL_CONTRACT.md`
- `docs/codex/goal-loop/02_STAGE_MANIFEST.md`
- `docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md`
- `docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md`
- `docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md`
- `docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md`
- `docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md`
- `docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md`
- `docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md`
- `docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md`
- `docs/codex/goal-loop/stages/P41_NODEHOST_DENSITY_GLOBAL_CONFIG.md`
- `artifacts/goal_loop/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/CONTEXT_RELOAD.md`
- `artifacts/goal_loop/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/DESIGN_BRIEF.md`
- `artifacts/goal_loop/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/WORKER_SUMMARY.md`
- `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/gate_result.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/coverage_ledger.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/{smoke_10_valkey_e2e_evidence,valkey_e2e_evidence_30,valkey_e2e_evidence_50,valkey_e2e_evidence_100,valkey_e2e_evidence_200}.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/{phase_summary,nodehost_density_plan,nodehost_density_plan_200,resource_preflight,resource_preflight_30,resource_preflight_50,resource_preflight_100,resource_preflight_200,run_state,cluster_plan,analysis_summary,report_index,cleanup_report,dry_run_gt_200_projection}.json`

## Diff review

The diff implements the P41 scope: global density defaults in `config/valkey_scale_lab_global.yaml`; effective config merge order in `src/valkey_scale_lab/config/validation.py`; shared density planning in `src/valkey_scale_lab/nodehost_density.py`; planner/runtime/preflight propagation; P41 real scale scenarios; P41 manifest gates; new density assertions; a P41 artifact builder; schema coverage; and focused unit/integration tests.

The first-review blockers were addressed. P41 no longer relies on plan-only PASS rows for 30/50/100/200: the manifest now runs real `scripts/valkey_e2e_gate.py` gates for 10, 30, 50, 100, and 200 nodes, and `scripts/assert_no_nodehost_partial_coverage.py` now requires real rows to reference `valkey_e2e_evidence` artifacts with `real_valkey=true`, PASS probe status, sufficient observed nodes, and density-limited runtime fields.

## Gate review

| Gate/check | Evidence | Result |
|---|---|---:|
| Aggregate P41 gate | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/gate_result.json` status `PASS` | PASS |
| Safety static scan | `stdout/safety_static_scan.log` says `PASS safety_scan` | PASS |
| Compile scripts/src | `scripts_compile` gate exit code 0 | PASS |
| Focused tests | `nodehost_density_tests.log` says `117 passed` | PASS |
| Real smoke 10 | `smoke_10_valkey_e2e_evidence.json`: 10 observed, `real_valkey=true`, data path PASS | PASS |
| Real scale 30 | `valkey_e2e_evidence_30.json`: 30 observed, Valkey 9.1.0, data path PASS | PASS |
| Real scale 50 | `valkey_e2e_evidence_50.json`: 50 observed, Valkey 9.1.0, data path PASS | PASS |
| Real scale 100 | `valkey_e2e_evidence_100.json`: 100 observed, Valkey 9.1.0, data path PASS | PASS |
| Real scale 200 | `valkey_e2e_evidence_200.json`: 200 observed, Valkey 9.1.0, data path PASS | PASS |
| P41 artifact builder | `build_nodehost_density_artifacts` gate exit code 0 | PASS |
| Density config assertion | `assert_nodehost_density_config.py --phase P41...` rerun/readback PASS | PASS |
| Runtime distribution assertion | `assert_runtime_nodehost_distribution.py --phase P41...` rerun/readback PASS | PASS |
| No partial coverage assertion | `assert_no_nodehost_partial_coverage.py --phase P41...` rerun/readback PASS | PASS |

## Artifact/schema review

All P41 manifest-required artifacts exist. The main density artifacts record `nodehost_strategy=density_limited`, `nodehost_distribution=round_robin_by_az`, `max_nodehosts=64`, `nodehosts_per_az=2`, `max_logical_nodes_per_nodehost=25`, `actual_nodehost_count`, and `logical_nodes_per_nodehost`.

The 100-node plan records 4 nodehosts with 25 logical nodes each. The 200-node plan and 200 real evidence record 8 nodehosts with 25 logical nodes each, closing the regression where 200 logical nodes were concentrated into two Docker nodehost containers. The 30 and 50 real evidence artifacts also carry density-limited runtime evidence and remain below the per-nodehost cap.

## Real Valkey evidence review

The current P41 gate result contains required real Valkey gates for 10/30/50/100/200 and all passed. The corresponding evidence artifacts are P41-scoped, declare `real_valkey=true`, use Valkey `9.1.0`, observe the requested node counts, observe cluster state `ok`, and record `data_path_result=PASS`.

`coverage_ledger.json` now records `execution_mode=real_valkey` and `status=PASS` for smoke, 30, 50, 100, and 200 rows, each referencing the corresponding real evidence artifact. The strengthened partial-coverage assertion rejects plan-only references for these real rows.

## Safety review

No host firewall, routing, PF, nftables, iptables, interface mutation, `sudo` network path, or unrelated process control was observed in the P41 diff or gate logs. The real runs use owned Docker/process runtime resources with deterministic P41 names and cleanup artifacts. The >200 artifact remains a dry-run planning projection: it is a cluster plan for the opt-in 1000-node dry-run profile and records `constraints.dry_run=true`, `constraints.no_execution=true`, and `constraints.above_200_dry_run_only=true`; it does not claim real Valkey evidence or created runtime resources.

## Quantitative coverage review

P41 coverage now includes fake/schema, smoke, real 30, real 50, real 100, real 200, and >200 dry-run projection rows. Missing 30/50/100/200 real runtime evidence is no longer masked as plan evidence. Runtime/preflight artifacts record density checks for 30/50/100/200, and the real evidence artifacts record observed node counts plus nodehost density distribution.

## Cleanup review

`artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/cleanup_report.json` is now `status=PASS`, has `resources_remaining=[]`, and corresponds to the final 200-node P41 run. It records cleanup of the eight owned nodehost containers and the owned Docker network. Intermediate process-exit and stop-timeout observations are encoded as `SKIPPED_WITH_REASON`, followed by successful container/network removal and no remaining resources.

## Blocking findings

| ID | Severity | Finding | Required fix |
|---|---|---|---|
| None | n/a | No blocking findings in this re-review. | n/a |

## Non-blocking notes

- `P41_NODEHOST_DENSITY_GLOBAL_CONFIG` is manifest-marked `automatic=false` and `real_valkey_required=false`, but the stage-specific P41 gates explicitly require and successfully ran real 10/30/50/100/200 Valkey evidence.
- `planner/plan.py` still contains an unused legacy `_nodehost_summaries()` helper with one-nodehost-per-AZ naming. It is not referenced by the current code path, but removing it later would reduce future confusion.

## Decision

Decision: PASS
