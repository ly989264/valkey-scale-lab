# WORKER_SUMMARY — P41_NODEHOST_DENSITY_GLOBAL_CONFIG

## Scope implemented

The P41 implementation was already present when this worker pass began. I inspected the required goal-loop context, current diff, P41 gate result, required P41 artifacts, and real-smoke/cleanup evidence. I did not edit source code, tests, schemas, harness controls, or gate artifacts. This file is the only file written by this worker pass.

Implemented scope observed: repository-level nodehost density defaults and effective config merge, shared density planning, planner/runtime/resource-preflight propagation, P41 harness entry, fail-closed nodehost assertion scripts, P41 artifact builder, P41 required artifacts, and focused unit/integration/scale tests.

## Changed files

| Path | Summary |
|---|---|
| `config/valkey_scale_lab_global.yaml` | Adds repository-level runtime nodehost density defaults. |
| `src/valkey_scale_lab/nodehost_density.py` | Adds shared density config extraction, density-limited nodehost plan generation, validation, and evidence extraction helpers. |
| `src/valkey_scale_lab/config/validation.py` | Adds built-in/global/scenario/CLI merge order, `load_effective_config`, density defaults, source provenance, and semantic density validation. |
| `src/valkey_scale_lab/planner/plan.py` | Routes cluster planning through shared density logic and records density evidence in plans. |
| `src/valkey_scale_lab/runtime/docker_runtime.py` | Routes process nodehost layout and runtime/cleanup artifacts through density planning. |
| `src/valkey_scale_lab/resource.py` | Adds density-aware resource preflight, nodehost count/density checks, total port count, FD, and memory evidence. |
| `src/valkey_scale_lab/cli.py` | Wires config validation/planning paths to effective config loading and density override plumbing. |
| `schemas/config/run_config.schema.json` | Defines runtime nodehost density fields while preserving legacy config compatibility through normalization. |
| `schemas/artifact/nodehost_density_plan.schema.json` | Adds schema coverage for P41 nodehost density plan artifacts. |
| `scripts/assert_nodehost_density_config.py` | Adds fail-closed assertion for global config, merge provenance, and density validity across legacy/scale configs. |
| `scripts/assert_runtime_nodehost_distribution.py` | Adds artifact cross-checks for required density fields, count consistency, max limits, and 200-node distribution. |
| `scripts/assert_no_nodehost_partial_coverage.py` | Adds coverage ledger assertion for fake/schema, smoke, 30/50/100/200, and >200 dry-run rows. |
| `scripts/p41_nodehost_density_artifacts.py` | Builds the P41 phase artifacts from planner/preflight code paths. |
| `codex/phase_manifest.json` | Adds P41 gate and artifact definitions. |
| `codex/gate_lock.json` | Updated for the strengthened harness-controlled file set. |
| `docs/codex/goal-loop/stages/P41_NODEHOST_DENSITY_GLOBAL_CONFIG.md` | Adds the P41 stage contract. |
| `artifacts/harness_exception/P41_NODEHOST_DENSITY_GLOBAL_CONFIG.md` | Records the stage/harness defect and strengthening rationale. |
| `tests/unit/test_nodehost_density.py` | Covers merge order, density planning, and fail-closed resource/density semantics. |
| `tests/unit/test_nodehost_density_assertions.py` | Covers negative cases for the new assertion scripts. |
| `tests/planner/test_planner.py` | Adds planner expectations for density-limited nodehost counts. |
| `tests/integration/test_docker_runtime_contract.py` | Adds process-runtime nodehost distribution contract coverage. |
| `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/*` | Contains P41 required artifacts, 100/200 density plans, >200 dry-run projection, and copied small real-smoke/cleanup evidence. |
| `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/*` | Contains the P41 gate result and per-gate stdout/stderr logs. |

## Commands run

| Command | Result | Log/artifact path |
|---|---|---|
| `sed -n ...` required goal-loop docs, P41 context, and design brief | PASS, read-only | n/a |
| `git status --short` | PASS, inspected current dirty tree | n/a |
| `git diff --stat` and `git diff --name-only` | PASS, inspected tracked diff summary | n/a |
| `find artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG -maxdepth 2 -type f` | PASS, inspected P41 artifact inventory | n/a |
| `find artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG -maxdepth 3 -type f` | PASS, inspected P41 gate log inventory | n/a |
| `python3 -m json.tool artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/gate_result.json` | PASS, read-only JSON inspection | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/gate_result.json` |
| `python3 -m json.tool` on selected P41 artifacts | PASS, read-only JSON inspection | `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/{phase_summary,nodehost_density_plan,coverage_ledger,cleanup_report,resource_preflight,run_state,nodehost_density_plan_200,dry_run_gt_200_projection}.json` |
| Observed gate command: `python3 scripts/safety_scan.py` | PASS | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/stdout/safety_static_scan.log` |
| Observed gate command: `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 -m compileall -q scripts src` | PASS | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/stdout/scripts_compile.log` |
| Observed gate command: `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 -m pytest -q tests/unit/test_nodehost_density.py tests/unit/test_nodehost_density_assertions.py tests/config tests/planner tests/integration/test_docker_runtime_contract.py tests/scale/test_scale_ladder.py` | PASS, 117 passed | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/stdout/nodehost_density_tests.log` |
| Observed gate command: `python3 scripts/p41_nodehost_density_artifacts.py` | PASS | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/stdout/build_nodehost_density_artifacts.log` |
| Observed gate command: `python3 scripts/assert_nodehost_density_config.py --phase P41_NODEHOST_DENSITY_GLOBAL_CONFIG` | PASS | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/stdout/nodehost_density_config.log` |
| Observed gate command: `python3 scripts/assert_runtime_nodehost_distribution.py --phase P41_NODEHOST_DENSITY_GLOBAL_CONFIG` | PASS | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/stdout/runtime_nodehost_distribution.log` |
| Observed gate command: `python3 scripts/assert_no_nodehost_partial_coverage.py --phase P41_NODEHOST_DENSITY_GLOBAL_CONFIG` | PASS | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/stdout/no_nodehost_partial_coverage.log` |

## Gates and assertions

| Gate/assertion | Result | Evidence path |
|---|---:|---|
| P41 aggregate gate result | PASS | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/gate_result.json` |
| Safety static scan | PASS | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/stdout/safety_static_scan.log` |
| Scripts/source compile | PASS | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/stdout/scripts_compile.log` |
| Nodehost density focused tests | PASS, 117 passed | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/stdout/nodehost_density_tests.log` |
| P41 artifact builder | PASS | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/stdout/build_nodehost_density_artifacts.log` |
| Global density config assertion | PASS | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/stdout/nodehost_density_config.log` |
| Runtime nodehost distribution assertion | PASS | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/stdout/runtime_nodehost_distribution.log` |
| Partial coverage assertion | PASS | `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/stdout/no_nodehost_partial_coverage.log` |

## Artifacts produced

| Artifact | Schema/check | Result |
|---|---|---:|
| `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/phase_summary.json` | Manifest-required phase summary | PASS |
| `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/nodehost_density_plan.json` | `schemas/artifact/nodehost_density_plan.schema.json`; assertion-checked | PASS |
| `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/resource_preflight.json` | Manifest-required preflight; assertion-checked | PASS |
| `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/run_state.json` | Manifest-required run state; assertion-checked | PASS |
| `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/cluster_plan.json` | Manifest-required cluster plan; assertion-checked | PASS |
| `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/coverage_ledger.json` | Partial coverage assertion | PASS |
| `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/analysis_summary.json` | Manifest-required analysis summary | PASS |
| `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/report_index.json` | Manifest-required report index | PASS |
| `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/nodehost_density_plan_200.json` | Runtime distribution assertion checks 200=>8 nodehosts | PASS |
| `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/dry_run_gt_200_projection.json` | Partial coverage assertion rejects real-runtime claims | PASS |
| `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/smoke_10_valkey_e2e_evidence.json` | Real Valkey wrapper evidence copied into P41 artifact dir | PASS |
| `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/cleanup_report.json` | Cleanup status inspected | PASS |

## Quantitative evidence summary

P41 records the required density fields in the phase summary, nodehost density plan, resource preflight, run state, cluster plan, coverage ledger, analysis summary, and report index. The inspected 100-node density plan records `nodehost_strategy=density_limited`, `nodehost_distribution=round_robin_by_az`, `max_logical_nodes_per_nodehost=25`, `actual_nodehost_count=4`, and 25 logical nodes on each nodehost. The 200-node density artifact records 8 nodehosts, 25 logical nodes each, closing the two-nodehost concentration regression. The >200 projection is dry-run-only and the coverage assertion checks it does not claim `real_valkey` or runtime resource creation.

Small real smoke evidence path: `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/smoke_10_valkey_e2e_evidence.json`. It records `status=PASS`, `real_valkey=true`, Valkey version `9.1.0`, 10 requested/observed nodes, `cluster_state_observed=ok`, and data path `PASS`.

## Cleanup summary

Cleanup evidence path: `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/cleanup_report.json`. The inspected cleanup report records `status=PASS`, no `resources_remaining`, and density evidence for the 10-node smoke run with 4 nodehosts. It includes process-termination actions and owned container/network stop/remove actions. Several intermediate `verify_exit` actions are `SKIPPED_WITH_REASON` because processes were still observable or verification timed out before owned container removal, but later cleanup actions report PASS and no remaining resources.

## Deviations from design

The implementation appears narrower than the design brief in these ways:

- Analysis/report code paths were not visibly modified in the tracked diff; P41 `analysis_summary.json` and `report_index.json` are produced by `scripts/p41_nodehost_density_artifacts.py`.
- The P41 manifest marks `automatic=false` and `real_valkey_required=false`; the stage still carries a small real-smoke evidence artifact.
- The P41 coverage ledger records 30/50/100/200 rows as `PASS` based on shared planner/path evidence rather than freshly running 30/50/100/200 real-Valkey gates in this worker pass.
- `smoke_10_valkey_e2e_evidence.json` and `cleanup_report.json` are P41-directory artifacts whose internal `phase_id`/run identifiers come from the existing `P12_SCALE_LADDER_10_30` scale-10 wrapper path.

## Remaining risks or `待验证`

- Review should decide whether P41 may rely on shared path/plan evidence for 30/50/100/200 coverage rows, or whether any of those rows should be `SKIPPED_WITH_REASON` unless fresh real scale gates are run.
- Review should decide whether the small real-smoke evidence copied into the P41 artifact directory is acceptable despite its internal `phase_id` being `P12_SCALE_LADDER_10_30`.
- Review should verify whether `codex/gate_lock.json` was updated transparently and still protects strengthened harness files.
- Review should inspect whether P24 partition-specific nodehost grouping remains compatible with the new global density planner.
- Review should verify that P41 `automatic=false` is intentional for this user-added stage and not a harness sequencing gap.

## Review handoff notes

Start with `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/gate_result.json`, then inspect the three assertion scripts and `src/valkey_scale_lab/nodehost_density.py`. The most important artifact checks are `nodehost_density_plan.json` for 100=>4 nodehosts, `nodehost_density_plan_200.json` for 200=>8 nodehosts, `resource_preflight.json` for fail-closed checks, `coverage_ledger.json` for scale coverage semantics, and `smoke_10_valkey_e2e_evidence.json`/`cleanup_report.json` for real-smoke and cleanup status.

## Addendum after initial review failure

The initial fresh-context review correctly failed the stage because 30/50/100/200 rows were plan/code-path evidence rather than real Valkey evidence. The main agent fixed that by registering P41 runtime scenarios `p41_nodehost_density_scale_10`, `p41_nodehost_density_scale_30`, `p41_nodehost_density_scale_50`, `p41_nodehost_density_scale_100`, and `p41_nodehost_density_scale_200`; tightening `scripts/assert_no_nodehost_partial_coverage.py` so real rows require `real_valkey=true` wrapper artifacts; and adding those real wrapper gates to the P41 manifest before artifact-building and assertions.

The full P41 gate was rerun after this change and passed. `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/gate_result.json` now records PASS for real Valkey 10/30/50/100/200 gates, then PASS for artifact building and all nodehost density assertions. `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/coverage_ledger.json` now records `execution_mode=real_valkey` and `status=PASS` for smoke, 30, 50, 100, and 200. The final `cleanup_report.json` is PASS and corresponds to the final 200-node cleanup.
