# DESIGN_BRIEF - P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE

## Objective

Move Valkey `cluster-node-timeout` from hidden runtime and gate hardcodes into a repository-wide, artifact-visible configuration profile. The default effective value must become `30000` ms for normal dev/correctness/failover paths. Fake/schema, smoke, 30/50/100/200 real Valkey, and greater-than-200 dry-run projection paths must all expose requested value, effective value, and source. Non-`30000` values are allowed only when an explicit profile, scenario, or CLI source is recorded.

## Repository findings

- `config/valkey_scale_lab_global.yaml` currently only defines `runtime.server_profile`, `runtime.valkey` io-thread fields, nodehost density, and `cluster.node_memory_limit_mb`; there is no cluster timeout or timeout matrix config.
- Config merge currently lives in `src/valkey_scale_lab/config/validation.py` and is only `built-in defaults < global config < scenario config < CLI override`. There is no selected-profile pass between global and scenario.
- Runtime hidden overrides exist in `src/valkey_scale_lab/runtime/docker_runtime.py`: `_process_config_text` defaults generated configs to `60000`, `_start_container` defaults Docker CLI to `5000`, and `_spec` hardcodes `600000` for P13/P30/P31/P32/P36 and `5000` for P24.
- Run-state node entries currently record server-profile fields via `node_effective_fields`, but do not record `requested_cluster_node_timeout_ms`, `effective_cluster_node_timeout_ms`, or `cluster_node_timeout_source`.
- Planner output in `src/valkey_scale_lab/planner/plan.py` records server profile in runtime/nodes, but no cluster timeout provenance.
- `scripts/valkey_e2e_gate.py` copies node process fields into evidence, but its field whitelist does not include cluster timeout fields. It also creates P42 `run_state.json` from state only for P30/P42.
- `scripts/fault_failover_gate.py` applies `CONFIG SET cluster-node-timeout` after startup with default `15000`. That is a hidden runtime mutation relative to generated `valkey.conf` and must become config/CLI-visible. Existing artifacts use `failover_node_timeout_ms`, not the P43 matrix names.
- P20/P21/P33/P34/P35 failover samples can already pass a timeout via `--failover-node-timeout-ms`, but sample rows do not include `timeout_config_ms`, `kill_to_pfail_ms`, `pfail_to_cluster_ok_ms`, `kill_to_client_recovered_ms`, `false_pfail_count`, or `false_failover_count`.
- P42 artifact patterns are the closest model: `scripts/p42_server_profile_artifacts.py` builds config validation, effective profile, generated config manifest, coverage ledger, dry-run projection, quant, analysis, and report artifacts over 10/30/50/100/200 plus >200 projection. P43 should use the same artifact-first shape but for cluster timeout.
- Existing tests explicitly assert legacy hidden values: `tests/integration/test_docker_runtime_contract.py` expects `600000` for P13/P32; `tests/unit/test_server_profile.py` and `tests/unit/test_p13_process_bootstrap_batching.py` construct nodes with `5000` or `600000`.
- `codex/phase_manifest.json` does not yet contain P43. P42 is present as a non-automatic stage with the real scale coverage gates that P43 can mirror and strengthen.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `config/valkey_scale_lab_global.yaml` | update | Add `cluster.cluster_node_timeout_ms`, `fault.cluster_node_timeout_matrix_ms`, and timeout profiles required by P43. |
| `src/valkey_scale_lab/cluster_timeout.py` | new | Centralize timeout defaults, profile selection, source provenance, validation helpers, node fields, and Valkey config provenance lines. |
| `src/valkey_scale_lab/config/validation.py` | update | Add built-in timeout defaults, selected profile merge pass, semantic validation, validation report timeout fields, and config source recording. |
| `schemas/config/run_config.schema.json` | update | Formalize `cluster.cluster_node_timeout_ms`, `cluster.cluster_node_timeout_profile`, `fault.cluster_node_timeout_matrix_ms`, and top-level `profiles`. |
| `schemas/artifact/config_validation_report.schema.json` | update | Require or document P43 timeout fields in validation reports. |
| `schemas/artifact/effective_cluster_timeout.schema.json` | new | Validate the effective timeout profile artifact. |
| `schemas/artifact/timeout_matrix_report.schema.json` | new | Validate timeout matrix rows and forbid fake PASS rows. |
| `src/valkey_scale_lab/planner/plan.py` | update | Add effective timeout/runtime provenance to `cluster_plan`, planned nodes, and >200 dry-run projection. |
| `src/valkey_scale_lab/runtime/docker_runtime.py` | update | Remove hidden per-phase timeout hardcodes, generate Valkey configs from effective config, write source comments/provenance, propagate node/run-state fields, and include timeout in generated config manifests. |
| `src/valkey_scale_lab/cli.py` | update | Add CLI override(s), likely `--cluster-node-timeout-ms` and optional `--cluster-node-timeout-profile`, routed through existing override plumbing. |
| `src/valkey_scale_lab/resource.py` | update | Include effective timeout evidence in resource preflight and exact-200 preflight artifacts. |
| `scripts/valkey_e2e_gate.py` | update | Include timeout node fields in `node_processes`, evidence runtime, and generated config/run-state checks. |
| `scripts/fault_failover_gate.py` | update | Default to config-visible `30000`, retain explicit CLI matrix selection, record P43 matrix fields, and stop silently mutating live timeout without source evidence. |
| `scripts/p43_cluster_timeout_artifacts.py` | new | Build P43 aggregate artifacts, coverage ledger, >200 projection, timeout matrix summary, analysis, report, events, metrics, workload windows, and phase summary. |
| `scripts/assert_cluster_timeout_config.py` | new | Assert global/default/profile/scenario/CLI timeout config, generated `valkey.conf` lines, source provenance, run_state fields, and real scale coverage. |
| `scripts/assert_no_hidden_timeout_override.py` | new | Scan source/templates/scripts for hidden phase timeout overrides and unproven non-30000 defaults. |
| `scripts/assert_timeout_matrix_artifacts.py` | new | Validate timeout matrix row semantics, required fields, PASS evidence refs, NOT_RUN/BLOCKED reasons, no fake/static matrix claims, and no silent downscale. |
| `scripts/assert_server_profile_config.py` | update | Keep P42 assertions compatible with new global `cluster` and `profiles` keys. |
| `scripts/assert_no_server_profile_partial_coverage.py` | update | Avoid rejecting P43-added timeout evidence and optionally reuse coverage checks. |
| `scripts/strict_coverage_defs.py` and `scripts/build_strict_coverage_registry.py` | update | Add timeout config/source fields to scenario compiler output where scale configs are represented. |
| `codex/phase_manifest.json` | update | Add non-automatic P43 stage gates and required artifacts. |
| `codex/gate_lock.json` | update | Refresh lock transparently after strengthening harness-controlled files. |
| `templates/configs/*.yaml` | likely update only if needed | Do not use templates as the only implementation. Add explicit scenario/profile selectors only where a non-default timeout is genuinely needed. |
| `tests/unit/test_cluster_timeout.py` | new | Unit tests for global merge, profile override, CLI override, matrix validation, and invalid timeout values. |
| `tests/unit/test_cluster_timeout_assertions.py` | new | Unit tests for new assertion scripts rejecting hidden overrides, missing provenance, fake matrix PASS, and silent downscale. |
| `tests/config/test_config_validation.py` | update | Verify validation report timeout fields and invalid values. |
| `tests/planner/test_planner.py` | update | Verify plan/projection timeout fields for 30/50/100/200 and >200 dry-run. |
| `tests/integration/test_docker_runtime_contract.py` | update | Replace legacy `600000` expectations with effective config-source checks and generated `cluster-node-timeout 30000` evidence. |
| `tests/unit/test_server_profile.py` and `tests/unit/test_p13_process_bootstrap_batching.py` | update | Adjust synthetic nodes/config text to include timeout provenance and 30000 defaults. |
| `tests/failover/test_failover_contract.py` and/or `tests/unit/test_goal_loop_assertions.py` | update | Cover failover default timeout, matrix field derivation, and selected timeout options. |

## Implementation plan

1. Add central timeout computation.
   - Create `cluster_timeout.py` with built-in default `30000`, matrix `[5000, 10000, 15000, 30000, 60000]`, valid range, profile merge helpers, `compute_effective_cluster_timeout(config)`, `cluster_timeout_node_fields(profile)`, and `valkey_cluster_timeout_config_lines(profile)`.
   - Effective artifact shape should include `requested_cluster_node_timeout_ms`, `effective_cluster_node_timeout_ms`, `cluster_node_timeout_source`, `cluster_node_timeout_profile`, `cluster_node_timeout_allow_override`, `cluster_node_timeout_matrix_ms`, and `merge_order`.

2. Implement merge order without hiding overrides.
   - In `normalize_config`, merge built-ins and global config, determine selected timeout profile from raw scenario and/or CLI profile selector, merge that profile before scenario config, then merge scenario config and CLI overrides.
   - Record `_config_sources.cluster_node_timeout` with source `global`, `profile`, `scenario`, or `cli`, plus the exact config path or profile name. Use `scenario` if the scenario explicitly set the timeout even when the value is `30000`.
   - Keep built-in fallback internal only; final artifacts should not report `built-in` as a P43 source.

3. Update validation and schemas.
   - Add semantic errors for non-integer, boolean, <=0, outside range, matrix missing/non-list/non-integer, or selected profile not found.
   - Add validation report fields required by P43.
   - Keep existing server profile behavior stable.

4. Route runtime and planner through effective timeout.
   - Remove `_spec` phase checks that inject `600000` or `5000`.
   - Add effective timeout fields to every node spec and planned node.
   - Generate `cluster-node-timeout <effective_ms>` in both Docker-container and process-runtime paths.
   - Add a Valkey config comment such as `# vslab cluster-node-timeout-source source=<source> requested=<requested> profile=<profile>` so generated config files carry provenance as well as the machine-readable manifest.
   - Add timeout fields to `_runtime_state`, `_process_runtime_state`, `generated_valkey_configs_manifest`, `effective_cluster_timeout.json`, resource preflight, and dry-run projections.

5. Make failover timeout selection explicit.
   - Change `fault_failover_gate.py` default from `15000` to the effective config value, expected to be `30000`.
   - Keep `--failover-node-timeout-ms` as a CLI override, but record source as `cli`. Consider adding alias `--timeout-config-ms` for matrix clarity.
   - If `CONFIG SET cluster-node-timeout` remains necessary for live failover tests, record it as an explicit CLI/config/profile adjustment in evidence and fail if the live setting differs from generated config without such source.
   - Add helper derivations for P43 matrix fields. `false_pfail_count` and `false_failover_count` may be `0` only when detectors ran; otherwise use `MISSING`/`NOT_RUN_WITH_REASON` with reason.

6. Add timeout matrix runner.
   - New `scripts/failover_rto_timeout_matrix.py` or P43 artifact builder subcommand should accept explicit `--scale` and repeated `--timeout-ms` values from the configured matrix.
   - It must not default to all 30/50/100/200 x 5 timeout cells. Unselected cells should be absent or recorded as `NOT_RUN_WITH_REASON` with a reason; selected cells with insufficient preflight should be `BLOCKED`.
   - PASS rows must cite live evidence, command log, run-state/config refs, exact node count, and non-static timestamps.

7. Add harness assertions and artifacts.
   - Build P43 artifacts after real gates using the P42 pattern, but with timeout evidence.
   - Assertions must fail closed for missing generated config lines, missing source provenance, non-30000 without explicit source, fake-only/smoke-only coverage, static matrix PASS rows, and silent downscale.

8. Update P43 manifest.
   - Add P43 as non-automatic, real-Valkey-required, max_nodes 200.
   - Mirror P42 scale gates for 10/30/50/100/200 with scenario names like `p43_cluster_timeout_scale_30`, plus P43 artifact builder and the three new assertions.
   - Required artifacts should include phase summary, effective timeout, config validation, resource preflight, cluster plan, run_state, generated config manifest, valkey evidence for 10/30/50/100/200, timeout matrix report, coverage ledger, >200 dry-run projection, events, metrics, workload windows, quant summary, analysis summary, report index, cleanup report, and goal-loop Markdown outputs.

## Harness, schema, and gate plan

- `scripts/assert_cluster_timeout_config.py` should validate:
  - global config includes the exact P43 keys and default `30000`;
  - effective config for scale_10/30/50/100/200 is `30000` unless explicitly overridden;
  - config validation report has requested/effective/source fields;
  - run_state nodes and valkey_e2e node_processes have timeout fields;
  - every generated config file contains `cluster-node-timeout 30000` and source comment/provenance;
  - >200 dry-run projection contains timeout config while `real_valkey` is false.
- `scripts/assert_no_hidden_timeout_override.py` should scan `src`, `scripts`, `tests`, `templates`, `config`, and `codex/phase_manifest.json` with allowlisted locations for global config, stage docs, matrix constants, tests intentionally checking rejection, and explicit scenario/profile config. It should flag `spec["cluster_node_timeout"] = ...`, default fallbacks like `"5000"`/`"60000"` in runtime generation, and parser defaults like `15000`.
- `scripts/assert_timeout_matrix_artifacts.py` should validate `timeout_matrix_report.json` against schema and require each PASS row to have:
  - `timeout_config_ms` in configured matrix;
  - exact selected `node_count` and no downscale;
  - live evidence refs with `real_valkey=true`;
  - non-static source refs to run_state/config/evidence;
  - the P43 metric fields.
  Rows not run must be `NOT_RUN_WITH_REASON` or `BLOCKED` with a reason and no fabricated numeric metrics.
- Schemas should be strict enough for P43 artifacts but not break existing completed P42 artifacts unless the manifest points P42 at older permissive schemas.
- `codex_gate.py` should not be weakened. If manifest/gate lock changes are necessary, document them in the worker summary and review.

## Test plan

- Unit:
  - default global config merge yields `30000`, source `global`;
  - selected `failover_rto` and `management_safe` profiles yield profile source and `allow_override` behavior;
  - scenario timeout override beats profile;
  - CLI timeout override beats scenario;
  - invalid values fail: missing/empty matrix, non-integer, boolean, zero, negative, out-of-range, selected profile unknown;
  - non-30000 explicit scenario/profile/CLI source is accepted and recorded.
- Integration/fake runtime:
  - `_node_specs` for smoke, 30, 50, 100, 200 produces timeout fields and no legacy `600000`;
  - `_process_config_text` contains `cluster-node-timeout 30000` and source comment;
  - `_start_container` uses the effective timeout;
  - `_process_runtime_state` and `_runtime_state` node records include requested/effective/source;
  - generated config manifest validates line presence and provenance.
- Failover:
  - `fault_failover_gate.py` default timeout is `30000`;
  - explicit timeout matrix selection records `timeout_config_ms`;
  - matrix derivation rejects static PASS and accepts NOT_RUN/BLOCKED rows with reasons.
- Plan/artifact validators:
  - existing 30/50/100/200 plan tests updated to assert effective timeout evidence;
  - >200 dry-run projection includes timeout fields and does not claim real evidence.
- Real:
  - P43 manifest runs smoke 10 plus 30/50/100/200 real Valkey paths and validators confirm generated configs/run_state/evidence show `30000`.
  - Full matrix large-scale runs are selectable, not automatic. If selected resources fail, the matrix artifact must be BLOCKED/NOT_RUN, not PASS.

## Required artifacts

- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/phase_summary.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/effective_cluster_timeout.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/config_validation_report.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/resource_preflight.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/cluster_plan.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/run_state.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/generated_valkey_configs_manifest.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/valkey_e2e_evidence.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/valkey_e2e_evidence_30.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/valkey_e2e_evidence_50.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/valkey_e2e_evidence_100.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/valkey_e2e_evidence_200.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/timeout_matrix_report.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/coverage_ledger.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/dry_run_gt_200_projection.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/events.jsonl`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/metrics_timeseries.jsonl`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/workload_windows.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/cleanup_report.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/quant_summary.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/analysis_summary.json`
- `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/report_index.json`
- `artifacts/goal_loop/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/WORKER_SUMMARY.md`
- `artifacts/goal_loop/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/REVIEW.md`
- `audit/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/AUDIT.md`
- `audit/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/audit_decision.json`

## Safety considerations

- Do not change host network configuration. Timeout matrix and failover tests must use owned containers/processes and existing project fault APIs only.
- Do not use `sudo`, host firewall, PF, nftables, iptables, routing, host interface, or unrelated process mutation.
- Do not use fake or static timeout matrix data as PASS evidence. NOT_RUN/BLOCKED rows must not include invented timings.
- Do not silently downscale 30/50/100/200 real gates. Validators should compare requested, observed, and expected node counts.
- Do not remove or weaken cleanup, no-bypass, coverage, or real-evidence gates to compensate for the shorter timeout.
- Do not let P43 open a default >200 real path. Greater-than-200 remains dry-run projection only.

## Resource considerations

- P43's real 10/30/50/100/200 evidence mirrors P42 and can be expensive. The 200 run must remain preflight-gated and exact.
- Shortening cluster timeout to `30000` may expose real failover/cluster convergence issues that were masked by `600000`; such failures must be treated as real failures, not skipped final PASS.
- The full 4 scales x 5 timeouts failover matrix is intentionally not automatic. The runner should require explicit selected cells and should record resource/preflight decisions per selected cell.
- If Docker resources are unavailable, the stage must block rather than produce fake evidence.

## `待验证`

- Whether Valkey accepts `CONFIG SET cluster-node-timeout` at runtime consistently for all 9.1.x paths, or whether matrix runs should rely exclusively on generated config plus restart.
- Whether `cluster-node-timeout 30000` is sufficient for exact 200-node setup/failover on the current host without increasing setup or wait timeouts.
- Whether existing P20/P21 completed artifacts with legacy `15000`/`60000` should be regenerated for P43, or P43 should only prove new paths and assert future gates use the global profile.
- Whether source comments in `valkey.conf` are acceptable as generated-config provenance, or if a sidecar per-node config metadata file is preferred by the reviewer.
- Whether `false_pfail_count` and `false_failover_count` can be measured from current probe data alone or require additional polling snapshots during the fault period.

## Worker instructions

- Implement only this stage.
- Do not commit.
- Do not weaken harness or safety rules.
- Prefer one central timeout computation path; do not patch individual phases.
- Remove hidden hardcoded timeout defaults in runtime/gates or convert them to explicit config/profile/CLI evidence.
- Keep P43 scale-generic for future >200 real paths while preserving current >200 dry-run policy.
