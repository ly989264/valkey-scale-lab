# DESIGN_BRIEF — P41_NODEHOST_DENSITY_GLOBAL_CONFIG

## Objective

Implement repository-level nodehost density configuration so fake, smoke, 30/50/100/200 real-Valkey, and >200 dry-run paths all use the same effective runtime density plan instead of hardcoding one Docker nodehost per AZ. The required merge order is built-in defaults < `config/valkey_scale_lab_global.yaml` < scenario config < CLI override. All legacy templates must still parse, 100/200-node profiles must split by `max_logical_nodes_per_nodehost`, and all required artifacts must record the nodehost density fields.

## Repository findings

The current repository has no top-level `config/` directory. Config parsing starts in `src/valkey_scale_lab/config/validation.py` via `parse_config_file()` plus `normalize_config()`, and it currently fills runtime defaults but does not load a global config file or preserve a merge provenance.

Planner nodehost placement is duplicated. `src/valkey_scale_lab/planner/plan.py` currently assigns `nodehost_id = nodehost-<az_id>` and `_nodehost_summaries()` emits one nodehost per AZ, so `scale_100.yaml` produces 2 nodehosts with 50 logical nodes each and `scale_200.yaml` produces 2 nodehosts with 100 logical nodes each. Runtime process mode repeats the same one-nodehost-per-AZ behavior in `src/valkey_scale_lab/runtime/docker_runtime.py::_process_nodehosts()`.

Resource preflight in `src/valkey_scale_lab/resource.py` checks config semantics, node count, Docker, CPU, memory, disk, ports, FD limits, and cleanup state, but it does not compute nodehost count, enforce `max_nodehosts`, or fail when a nodehost exceeds density. Port checks count logical nodes only, not both client and cluster bus ports as a total-port invariant.

Schemas are permissive enough to accept added fields (`schemas/config/run_config.schema.json`, `schemas/artifact/cluster_plan.schema.json`, `schemas/artifact/resource_preflight.schema.json`, `schemas/artifact/phase_summary.schema.json` all allow additional properties), but there is no dedicated `nodehost_density_plan` schema. `schemas/artifact/report_index.schema.json` and `schemas/artifact/analysis_summary.schema.json` should be extended or verified to require density provenance for P41 artifacts.

Existing tests cover config validation, planner placement, process runtime contracts, scale/dry-run gates, and strict exact-scale assertions, but no tests cover global config merge order, density-limited nodehost planning, fail-closed density preflight, or partial scale coverage. Existing assertions such as `scripts/assert_exact_scale_real_evidence.py` and `scripts/assert_200_plus_dry_run.py` do not inspect nodehost density.

`codex/phase_manifest.json` does not currently contain P41 based on text search. `docs/codex/goal-loop/stages/P41_NODEHOST_DENSITY_GLOBAL_CONFIG.md` is present but untracked, and `artifacts/harness_exception/P41_NODEHOST_DENSITY_GLOBAL_CONFIG.md` is also untracked. Harness integration for P41 is therefore likely required before `codex_gate.py precheck/run/postcheck` can pass.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `config/valkey_scale_lab_global.yaml` | Add | Repository-level global runtime density defaults required by the stage; likely set `runtime.nodehost_strategy: density_limited`, `runtime.max_nodehosts`, `runtime.nodehosts_per_az`, `runtime.max_logical_nodes_per_nodehost: 25`, and `runtime.nodehost_distribution: round_robin_by_az`. |
| `src/valkey_scale_lab/config/validation.py` | Modify | Implement built-in/global/scenario/CLI merge helpers, normalize density defaults for legacy configs, validate runtime density fields, and emit effective config/provenance in validation reports. |
| `schemas/config/run_config.schema.json` | Modify | Add explicit runtime density field definitions and allowed values while keeping legacy configs valid through normalization. |
| `src/valkey_scale_lab/planner/plan.py` | Modify | Replace one-nodehost-per-AZ hardcoding with shared density planner; add density fields to plan runtime, constraints, nodehosts, nodes, and top-level density plan refs. |
| `src/valkey_scale_lab/resource.py` | Modify | Use effective config and density planner; fail closed for requested nodehosts > max, invalid total port count, insufficient FD/memory estimates, and any nodehost over density. |
| `src/valkey_scale_lab/runtime/docker_runtime.py` | Modify | Use the shared density plan in `_node_specs()`, `_process_nodehosts()`, `_process_runtime_state()`, cleanup reports, strict management/fault/full-flow artifact writers, and scale ladder artifacts. |
| `src/valkey_scale_lab/analysis/summary.py` | Modify | Propagate density fields into `analysis_summary.json` from phase artifacts without deriving from logs. |
| `src/valkey_scale_lab/report/render.py` | Modify | Include density provenance and source artifacts in report indexes for summary reports. |
| `src/valkey_scale_lab/report/final.py` | Modify | Preserve/report density fields across final/strict report indexes and CSV/report derivations. |
| `src/valkey_scale_lab/cli.py` | Modify | Add narrowly scoped CLI override arguments if the worker chooses to expose them; otherwise route existing commands through effective config loading. |
| `schemas/artifact/nodehost_density_plan.schema.json` | Add | Schema for `nodehost_density_plan.json` required by P41. |
| `schemas/artifact/cluster_plan.schema.json` | Modify | Require or explicitly define density fields for P41-compatible cluster plans. |
| `schemas/artifact/resource_preflight.schema.json` | Modify | Require/define density checks and resource estimates. |
| `schemas/artifact/analysis_summary.schema.json` | Modify | Define density evidence/provenance fields. |
| `schemas/artifact/report_index.schema.json` | Modify | Define density evidence/provenance fields and source refs. |
| `schemas/artifact/coverage_matrix.schema.json` and/or `schemas/artifact/strict_coverage_registry.schema.json` | Modify | Ensure coverage ledger/matrix rows can record density coverage and execution mode. |
| `templates/configs/*.yaml` | Modify selectively | Add explicit density only where needed for clarity; legacy templates must pass even when fields are omitted, so avoid broad churn unless tests need canonical examples. |
| `scripts/assert_nodehost_density_config.py` | Add | Fail closed for missing global config, missing density fields, bad merge evidence, over-limit density, and >200 dry-run real claims. |
| `scripts/assert_no_nodehost_partial_coverage.py` | Add | Fail closed unless fake/smoke/30/50/100/200/>200 dry-run coverage rows and artifacts all include density evidence. |
| `scripts/assert_runtime_nodehost_distribution.py` | Add | Compare config, plan, run state, preflight, and density plan; fail if 100/200 concentrate into 2 nodehosts or actual count mismatches. |
| `scripts/codex_gate.py` | Modify | Add P41 to bounded/harness behavior only if manifest integration requires it; preserve existing strict gate semantics. |
| `codex/phase_manifest.json` | Modify | Add P41 phase entry, gates, schemas, required artifacts, and audit paths if P41 is to be run by the harness. |
| `codex/gate_lock.json` | Modify | Update transparently only after strengthening harness-controlled files. |
| `scripts/strict_harness_lib.py` or related strict assertion helpers | Modify if needed | Share density artifact loading and missing-data checks across new assertion scripts. |
| `tests/config/test_config_validation.py` | Modify | Add global merge/default/override and legacy-template validation tests. |
| `tests/planner/test_planner.py` | Modify | Add 100=>4 and 200=>8 density-limited plan tests with max 25 per nodehost. |
| `tests/integration/test_docker_runtime_contract.py` | Modify | Add runtime `_process_nodehosts()` distribution tests and small smoke config path checks without starting Docker. |
| `tests/unit/test_nodehost_density_assertions.py` | Add | Validate new assertion scripts fail on partial coverage, missing fields, over-limit density, and >200 fake real claims. |
| `tests/unit/test_resource_preflight_density.py` | Add | Validate resource preflight fail-closed conditions for max nodehosts, FD, memory, total ports, and per-nodehost limits. |
| `tests/report/test_*` and `tests/analysis/test_analysis_summary.py` | Modify | Ensure analysis/report indexes preserve density fields and artifact-only provenance. |
| `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/*` | Add | Required stage artifacts produced by commands/gates, not hand-invented. |

## Implementation plan

1. Add a shared density configuration module or helper functions, likely under `src/valkey_scale_lab/config/validation.py` or a new small `src/valkey_scale_lab/config/effective.py`, that deep-merges built-in defaults, `config/valkey_scale_lab_global.yaml`, scenario config, and optional CLI overrides. Keep existing `normalize_config(raw)` behavior backward-compatible by making it call the shared defaults when no file path is available.
2. Define a single density planner, likely in `src/valkey_scale_lab/planner/plan.py` or a new `src/valkey_scale_lab/planner/nodehost_density.py`, returning `nodehost_strategy`, `max_nodehosts`, `nodehosts_per_az`, `max_logical_nodes_per_nodehost`, `actual_nodehost_count`, `logical_nodes_per_nodehost`, and `nodehost_distribution`. It should allocate nodehosts per AZ and round-robin logical nodes within each AZ so 200 nodes with max 25 per nodehost yields 8 nodehosts.
3. Replace hardcoded planner/runtime nodehost assignment with that shared density planner. Preserve P24 partition-special grouping only if it records a density-derived source or an explicit stage-specific transformation; otherwise it risks partial coverage. Mark this exact interaction 待验证.
4. Extend resource preflight to compute density before Docker execution and fail closed on all stage-required conditions. The preflight report should include `density_checks`, total port count, FD estimate, memory estimate per logical node and per nodehost, and clear `FAIL` reasons instead of silent fallback.
5. Add schema definitions and assertion scripts. Assertions should load config, plan, run state, preflight, coverage ledger/matrix, analysis summary, report indexes, and dry-run artifacts; reject missing density evidence, partial scale coverage, any nodehost over max, mismatched counts, and >200 dry-run artifacts that claim live Valkey/runtime execution.
6. Produce P41 artifacts from actual code paths: validate/plan/preflight, a fake/schema unit path, small smoke real path when Docker preflight passes, and artifact-only coverage records for 30/50/100/200 real evidence or SKIPPED_WITH_REASON when local resources are unavailable. Larger real gates must not be faked or silently downscaled.

## Harness, schema, and gate plan

P41 should be added to `codex/phase_manifest.json` if absent, with common strict gates plus stage-specific assertions:

- `python3 -m pytest -q tests/config tests/planner tests/integration/test_docker_runtime_contract.py tests/unit/test_nodehost_density_assertions.py tests/unit/test_resource_preflight_density.py`
- `python3 scripts/assert_nodehost_density_config.py --phase P41_NODEHOST_DENSITY_GLOBAL_CONFIG`
- `python3 scripts/assert_no_nodehost_partial_coverage.py --phase P41_NODEHOST_DENSITY_GLOBAL_CONFIG`
- `python3 scripts/assert_runtime_nodehost_distribution.py --phase P41_NODEHOST_DENSITY_GLOBAL_CONFIG`
- schema validation for `nodehost_density_plan.json`, `resource_preflight.json`, `cluster_plan.json`, `phase_summary.json`, `coverage_ledger.json`, `analysis_summary.json`, and `report_index.json`
- small real smoke wrapper when resource preflight passes, using existing real wrapper scripts rather than generated evidence

Schema additions should include `schemas/artifact/nodehost_density_plan.schema.json` and tightened definitions in existing config/plan/preflight/analysis/report schemas. The schema should require all seven density fields and require reason-bearing `MISSING` or `SKIPPED_WITH_REASON` where a path is legitimately not executed.

Harness updates must strengthen rather than bypass. If `codex/gate_lock.json` changes, the worker must document the before/after reason in `artifacts/harness_exception/P41_NODEHOST_DENSITY_GLOBAL_CONFIG.md` and prove the lock still detects unauthorized changes.

## Test plan

Unit tests:

- legacy templates still validate when density fields are omitted;
- global config supplies density fields;
- scenario config overrides global config;
- CLI override wins over scenario config, if implemented;
- 100 nodes with max 25 yields 4 nodehosts and max 25 per nodehost;
- 200 nodes with max 25 yields 8 nodehosts and max 25 per nodehost;
- >200 dry-run plans use density generically without claiming runtime execution;
- resource preflight fails for max-nodehost overflow, invalid port totals, low FD estimate, low memory estimate, and density overflow;
- new assertion scripts fail on missing global config, missing artifact fields, partial coverage, over-limit density, mismatched actual count, and >200 dry-run live claims.

Integration tests:

- fake/schema path writes density evidence without live claims;
- small 6/10 process-runtime smoke config produces density plan and run state with matching nodehosts;
- P20/P21/P30-P36 scale paths call the same density planner, not stage-local hardcoded counts;
- cleanup report includes density fields and remains PASS only when owned resources are removed.

Gate tests:

- Run `python3 -m compileall -q scripts src`.
- Run focused pytest first, then full `python3 -m pytest -q tests/unit tests/integration tests/config tests/planner tests/analysis tests/report` if feasible.
- Run the three new assertion scripts against intentionally bad temp artifacts and then against P41 artifacts.
- Run `scripts/valkey_e2e_gate.py` for a small smoke profile only when Docker and preflight pass; if unavailable, encode SKIPPED_WITH_REASON and do not claim real proof for that row.

## Required artifacts

- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/phase_summary.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/nodehost_density_plan.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/resource_preflight.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/run_state.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/cluster_plan.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/coverage_ledger.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/analysis_summary.json`
- `artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/report_index.json`
- Gate logs under `artifacts/gates/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/`
- Review/audit artifacts under `artifacts/goal_loop/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/` and `audit/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/`

Each JSON artifact should include the seven density fields, producer/provenance, source artifact refs, and missing/skipped reasons where applicable.

## Safety considerations

This stage increases the number of owned Docker nodehost containers for 100/200 node profiles. That is acceptable only inside owned Docker namespaces/networks with deterministic names, labels, state files, and cleanup. It must not alter host network configuration, firewall, routing, PF, nftables, iptables, interfaces, or OS services.

Fail-closed behavior is central: the implementation must not silently reduce 200 to 100, swap real runtime with dry-run, skip density checks, or fabricate real Valkey evidence. Any unavailable local Docker resource must be recorded with `SKIPPED_WITH_REASON` or block the real gate rather than passed off as proof.

P24 partition grouping currently has a special nodehost layout. The worker must preserve partition safety while ensuring P41 density assertions do not accidentally force unsafe or semantically invalid partition placement. This interaction is 待验证.

## Resource considerations

With max 25 logical nodes per nodehost, expected nodehost counts are: 6/10 smoke likely 1 or 2 depending AZ split, 30=>2, 50=>2, 100=>4, 200=>8. More nodehost containers increase Docker startup overhead, exposed port bindings, bundle copies, memory overhead, FD usage, and cleanup time.

Preflight should estimate both logical-node resource use and nodehost-container overhead. FD estimates must include Valkey client ports, cluster bus ports, process pid/log/config files, workload clients, and Docker exec/probe overhead. Total port count should include client and cluster-bus ports and must fail if any range is invalid or unavailable.

The 200-node bounded exception remains bounded; this stage must not make >200 real execution automatic. >200 is dry-run projection only unless a future explicit resource policy changes it.

## `待验证`

- Whether P41 should extend the existing strict P27-P40 manifest sequence or is a one-off user-added stage after P40.
- Whether `scripts/codex_gate.py` needs `STRICT_STAGE_IDS`, bounded exception, and harness-only lists updated for P41.
- Whether Docker is available locally for the small real smoke gate during the worker run.
- Whether existing committed 30/50/100/200 artifacts should be regenerated or whether P41 can prove compatibility through new P41 artifacts plus validator checks.
- Exact best home for the shared density planner: `planner/plan.py` versus a new module.
- Exact CLI override shape; only implement if the stage gates or user workflow need a stable public override.
- P24 partition-special nodehost grouping compatibility with global density distribution.

## Worker instructions

- Implement only this stage.
- Do not commit.
- Do not weaken harness or safety rules.
- Keep legacy template configs valid when density fields are omitted.
- Do not hardcode nodehost count in any phase; route planner, runtime, preflight, analysis, and report through the shared density implementation.
- Treat missing metrics as `MISSING` or `SKIPPED_WITH_REASON` with reason; never invent values.
- Do not claim >200 dry-run artifacts are real runtime evidence.
