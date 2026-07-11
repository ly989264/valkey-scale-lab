# DESIGN_BRIEF - P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG

## Objective

Make the Valkey server profile a real repository-wide configuration path, not a YAML-only setting. The effective profile must flow through config validation, planning, resource preflight, generated `valkey.conf`, run state, real Valkey evidence, dry-run projections, reports, and fail-closed harness assertions. P42 must prove the same profile behavior for smoke, 30, 50, 100, and 200 real Valkey paths, and prove greater-than-200 remains projection-only.

## Repository findings

- `config/valkey_scale_lab_global.yaml` currently only carries P41 nodehost-density defaults. It does not define `runtime.server_profile`, `runtime.valkey.*`, or global `cluster.node_memory_limit_mb`.
- `src/valkey_scale_lab/config/validation.py` already implements the required merge order `built-in defaults < global config < scenario config < CLI override`, but only P41 nodehost fields are normalized/reported. `config_validation_report` does not yet include requested/effective io-thread or memory fields.
- `src/valkey_scale_lab/planner/plan.py` writes `resource_limits.memory_mb` from `cluster.node_memory_limit_mb`, and host capacity checks use that raw value. There is no effective profile artifact, io-thread budget, or per-node effective memory evidence in plans.
- `src/valkey_scale_lab/resource.py` has resource preflight, but `_memory_check` is a fixed 8192 MB floor estimate and does not record `node_count * node_memory_limit_mb`, per-nodehost memory projection, host available memory, or memory budget status. No io-thread budget check exists.
- `src/valkey_scale_lab/runtime/docker_runtime.py` generates process-mode config in `_process_config_text()`. It never emits `io-threads`, `maxmemory`, profile metadata, or runtime memory-enforcement evidence. Process-mode node configs are already written under `artifacts/phases/<phase>/node_configs/*.conf`, which is a good place to attach P42 evidence.
- `scripts/valkey_e2e_gate.py` copies `state.runtime`, `state.nodehosts`, and a limited `node_processes_from_state()` projection into evidence. It must include effective profile fields so the independent wrapper evidence can be asserted without trusting source code.
- P41 established useful patterns: P41 manifest gates run real 10/30/50/100/200 paths, then a stage artifact builder and assertion scripts validate coverage. P42 should mirror that shape with profile-specific scripts.
- `templates/configs/scale_200.yaml`, `templates/configs/scale_1000_dryrun_optin.yaml`, and P37-generated dry-run configs currently use `node_memory_limit_mb: 32`; this can mask the new global 64 MB default unless intentionally rewritten or explicitly justified as an override.
- P42 is not yet in `codex/phase_manifest.json`; `scripts/codex_gate.py` only recognizes P15-P26 goal-loop handoffs and P27-P40 strict handoffs. P42 needs manifest/harness support rather than an out-of-band pass.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `config/valkey_scale_lab_global.yaml` | Update | Add required global `runtime.server_profile`, `runtime.valkey.*`, and `cluster.node_memory_limit_mb: 64`. |
| `schemas/config/run_config.schema.json` | Update | Validate `runtime.server_profile`, nested `runtime.valkey`, `log_format`, and memory defaults/overrides. |
| `schemas/artifact/config_validation_report.schema.json` | Update | Require or describe P42 requested/effective io-thread and memory budget fields. |
| `schemas/artifact/resource_preflight.schema.json` | Update | Capture P42 memory and io-thread budget status fields. |
| `schemas/artifact/cluster_plan.schema.json` | Update | Allow/validate effective profile fields in runtime and nodes. |
| `schemas/artifact/effective_server_profile.schema.json` | Add | Schema for `effective_server_profile.json`. |
| `src/valkey_scale_lab/server_profile.py` or `src/valkey_scale_lab/config/server_profile.py` | Add | Central resolver for profiles, io-thread auto calculation, budgets, memory enforcement fields, and report payloads. |
| `src/valkey_scale_lab/config/validation.py` | Update | Add built-in defaults, semantic validation, effective profile report fields, and fail-closed/degrade reasons. |
| `src/valkey_scale_lab/cli.py` | Update | Replace nodehost-only override helper with profile-aware CLI overrides for config/plan/gate/resource. |
| `src/valkey_scale_lab/planner/plan.py` | Update | Attach effective server profile to plan runtime and every node; use effective memory in capacity checks. |
| `src/valkey_scale_lab/resource.py` | Update | Add io-thread budget preflight and real memory projection fields; block insufficient memory. |
| `src/valkey_scale_lab/runtime/docker_runtime.py` | Update | Support P42 scenarios; generate profile-aware `valkey.conf`; record generated config manifest, run-state fields, and memory enforcement. |
| `scripts/valkey_e2e_gate.py` | Update | Include effective profile fields in `node_processes` and evidence. |
| `scripts/p42_server_profile_artifacts.py` | Add | Build P42 aggregate artifacts, coverage ledger, effective profile artifact, dry-run projection, summaries, and report indexes after real gates. |
| `scripts/assert_server_profile_config.py` | Add | Fail closed on missing global config, merge-order, schema, CLI override, and forbidden blind `io_threads=6` behavior. |
| `scripts/assert_io_thread_memory_evidence.py` | Add | Fail closed when generated configs, run state, preflight, or evidence lack effective io-thread/memory fields. |
| `scripts/assert_no_server_profile_partial_coverage.py` | Add | Require fake/schema, smoke, 30, 50, 100, 200, and greater-than-200 projection rows; reject fake evidence as real. |
| `codex/phase_manifest.json` | Update | Add P42 gates/artifacts/audit paths, likely `automatic: false`, `real_valkey_required: true`, `max_nodes: 200`. |
| `codex/gate_lock.json` | Update | Refresh harness hashes after strengthening locked harness files/scripts. |
| `templates/configs/*.yaml` and `scripts/p37_200_plus_dry_run_artifacts.py` | Update | Ensure scale configs inherit or explicitly record 64 MB defaults; avoid stale 32 MB projections unless marked intentional. |
| `tests/config/test_config_validation.py` | Update | Cover profile parsing, merge order, validation report fields, invalid profiles, and excessive io-thread settings. |
| `tests/planner/test_planner.py` | Update | Cover effective profile fields in plans and nodes. |
| `tests/scale/test_scale_ladder.py` and/or new `tests/unit/test_server_profile.py` | Update/Add | Cover auto io-thread budget, memory preflight, insufficient memory block, and 200 exception interaction. |
| `tests/integration/test_docker_runtime_contract.py` | Update | Cover generated `valkey.conf` behavior for `io_threads=1` and `io_threads=2`, plus maxmemory evidence. |
| `tests/unit/test_server_profile_assertions.py` | Add | Unit-test the three new assertion scripts with passing and failing fixtures. |
| `tests/unit/test_cli_contract.py` | Update | Cover new CLI override flags. |

## Implementation plan

1. Add a central effective-profile resolver. Inputs: normalized config, logical node count, nodehost count, host CPU count, optional source label. Outputs: `effective_server_profile`, requested/effective io threads, auto calculation inputs, budget statuses, requested/effective memory, log format, total Valkey io-thread budget, memory enforcement plan, and a list of decisions/reasons.
2. Define conservative profile defaults:
   - `correctness`: `io_threads=1`, auto off, low budgets, text logs, 64 MB memory.
   - `one_b_dev`: default profile, `io_threads=1` or at most 2, auto off by default, 64 MB memory.
   - `one_b_perf`: may use auto/higher values, but only within `io_threads_max_per_node` and `io_threads_max_total`.
3. Add config/schema support. Global config must define the required keys; built-in defaults must remain safe if the global file is absent. Explicit excessive non-auto io-thread values should fail closed; auto-derived values may degrade with a recorded reason.
4. Extend CLI overrides for server profile and Valkey settings. Keep existing nodehost override flags backward-compatible.
5. Route planner through the resolver after node/nodehost counts are known. Add runtime-level and per-node effective profile fields; host capacity checks must use `effective_node_memory_limit_mb`.
6. Route resource preflight through the same resolver. Add top-level and check-level fields for `node_count * node_memory_limit_mb`, `projected_nodehost_memory_mb`, `host_available_memory_mb`, `can_run`, `io_thread_budget_status`, and `memory_budget_status`. Insufficient memory must return `status=FAIL`, `can_run=false`.
7. Route runtime config generation through the same resolver. For every process-mode node config:
   - omit `io-threads` when `effective_io_threads == 1`;
   - include `io-threads <N>` when `effective_io_threads > 1`;
   - enforce memory with Valkey `maxmemory <bytes>` if supported, and record `runtime_memory_limit_enforced=true`; otherwise record `runtime_memory_limit_enforced=false` with reason and do not claim enforcement.
8. Add P42 runtime scenarios, e.g. `p42_server_profile_scale_10`, `p42_server_profile_scale_30`, `p42_server_profile_scale_50`, `p42_server_profile_scale_100`, `p42_server_profile_scale_200`. Wire them into `_uses_docker_process_runtime()`, `_scenario_node_count_allowed()`, and exact-200 resource exception checks.
9. Add generated config evidence: a `generated_valkey_configs_manifest.json` with one row per logical node containing config artifact path, effective io threads, memory limit, whether an `io-threads` line exists, and memory-enforcement evidence.
10. Add P42 artifact builder to aggregate real gate outputs, effective profile evidence, config validation, resource preflight, coverage ledger, dry-run greater-than-200 projection, `quant_summary.json`, and concise report/index artifacts.
11. Add assertion scripts that independently inspect global config, normalized config reports, plans, preflight, run state, generated config text, real evidence, and coverage ledger. They must fail closed on missing files/fields.
12. Add P42 manifest gates and required artifacts. Keep P42 outside the automatic P15-P40 loop unless the main agent intentionally changes the user-requested stage policy; do not raise default node caps.

## Harness, schema, and gate plan

- Manifest gates should include:
  - `python3 scripts/safety_scan.py`
  - `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 -m compileall -q scripts src`
  - focused pytest gate for server profile/config/planner/runtime/resource/assertions plus existing P41/P37 regressions
  - real Valkey gates for 10, 30, 50, 100, 200 via `scripts/valkey_e2e_gate.py`
  - `python3 scripts/p42_server_profile_artifacts.py`
  - `python3 scripts/assert_server_profile_config.py --phase P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG`
  - `python3 scripts/assert_io_thread_memory_evidence.py --phase P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG`
  - `python3 scripts/assert_no_server_profile_partial_coverage.py --phase P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG`
- Required manifest artifacts should include at least:
  - `phase_summary.json`
  - `effective_server_profile.json`
  - `config_validation_report.json`
  - `resource_preflight.json`
  - `cluster_plan.json`
  - `run_state.json`
  - `generated_valkey_configs_manifest.json`
  - `valkey_e2e_evidence.json` plus scale-specific `valkey_e2e_evidence_30/50/100/200.json`
  - `cleanup_report.json`
  - `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `quant_summary.json`
  - `coverage_ledger.json`
  - `dry_run_gt_200_projection.json`
  - `analysis_summary.json`, `report_index.json`
- `scripts/codex_gate.py` should be strengthened to recognize P42 handoff/review artifacts or a generic post-P40 user-requested stage handoff set. Do not weaken P15-P40 checks.
- Because `codex/phase_manifest.json`, `scripts/*.py`, `schemas/**/*.json`, and `docs/codex/**` are locked harness files, update `codex/gate_lock.json` only after the strengthening changes are complete and demonstrably checked by precheck/postcheck.

## Test plan

- Config tests:
  - global defaults load `server_profile=one_b_dev`, `effective_io_threads=1`, and `effective_node_memory_limit_mb=64`;
  - scenario overrides beat global config; CLI overrides beat scenario config;
  - invalid profile/log format fails;
  - explicit excessive `io_threads` fails closed or degrades with a reason in `config_validation_report`;
  - blind global `io_threads=6` across multi-node scale is rejected by assertion.
- Budget tests:
  - `io_threads=1` yields effective 1 and no generated `io-threads` line;
  - `io_threads=2` yields effective 2 and generated `io-threads 2`;
  - `io_threads_auto` uses host CPU count, nodehost count, and node count and never exceeds total/per-node budget;
  - `total_valkey_threads <= io_threads_max_total`;
  - insufficient memory reports `can_run=false` and does not downscale.
- Runtime/planner tests:
  - cluster plan runtime and every node carry `effective_io_threads` and `effective_node_memory_limit_mb`;
  - process `valkey.conf` includes `maxmemory` or records non-enforcement;
  - `run_state` and `valkey_e2e_evidence` expose the same effective profile fields.
- Assertion tests:
  - each new script accepts a minimal valid fixture;
  - each script rejects missing generated configs, missing run-state fields, fake evidence in real rows, partial scale coverage, stale 32 MB memory evidence, and `io_threads>1` without matching config text.
- Regression tests:
  - existing P37 dry-run tests still reject live claims;
  - P41 nodehost-density tests still pass with the new profile fields;
  - exact-200 exception remains bounded and does not raise default max nodes.

## Required artifacts

- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/effective_server_profile.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/generated_valkey_configs_manifest.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/config_validation_report.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/resource_preflight.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/cluster_plan.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/run_state.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/node_configs/*.conf`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/valkey_e2e_evidence.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/valkey_e2e_evidence_30.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/valkey_e2e_evidence_50.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/valkey_e2e_evidence_100.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/valkey_e2e_evidence_200.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/cleanup_report.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/events.jsonl`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/metrics_timeseries.jsonl`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/workload_windows.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/quant_summary.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/coverage_ledger.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/dry_run_gt_200_projection.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/analysis_summary.json`
- `artifacts/phases/P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG/report_index.json`

## Safety considerations

- Do not add host network, firewall, route, PF, nftables, iptables, interface, or sudo paths. P42 should only change generated Valkey config, Docker-owned runtime options if used, and project artifacts.
- Do not treat fake/unit fixtures as real Valkey evidence. Coverage rows for 30/50/100/200 must reference real wrapper outputs with `real_valkey=true`.
- Do not silently reduce node count when memory or io-thread preflight fails. Resource failure blocks/fails the stage.
- Do not raise the default max node cap above 100. The 200-node P42 real path must remain a bounded exception with explicit preflight.
- Do not make `io_threads=6` a global default. If an explicit high setting is tested, it must fail closed or degrade with reason.

## Resource considerations

- 200 real nodes at 64 MB projects to at least 12,800 MB before nodehost/workload overhead; P42 can block on memory preflight and must not pass by using 32 MB unless an explicit override is justified and recorded.
- `io_threads_auto` must usually resolve to 1 for 30/50/100/200 on ordinary developer hosts because total budgets and CPU count are tight. That is acceptable if recorded.
- Host available memory collection is platform-sensitive. Prefer deterministic helper fields and use `MISSING`/`SKIPPED_WITH_REASON` only where the gate explicitly allows it; for required 200 real runs, insufficient measured memory should fail/block.
- Real 30/50/100/200 gates need free ports matching the templates and no leftover owned resources. Cleanup must run and evidence must cite cleanup reports.

## `待验证`

- `待验证`: Whether Valkey 9.1.x supports a native JSON log format directive. If not, `runtime.valkey.log_format=json` should fail closed or be marked unsupported with reason; do not emit an invalid config line.
- `待验证`: Exact Valkey `maxmemory` syntax accepted in generated config. Prefer bytes to avoid suffix ambiguity if tests/probes confirm it.
- `待验证`: Whether current Docker Desktop memory visibility is sufficient for `host_available_memory_mb`; if not, define a conservative Docker-specific measurement or block when unavailable for real 200.
- `待验证`: Whether P42 should be `automatic:false` like P41 or added to an extended automatic loop. Current context says P42 is user-requested and not in the manifest, so the conservative plan is non-automatic.
- `待验证`: Existing committed artifacts may still show 32 MB or lack profile fields. P42 assertions should validate P42 artifacts and current templates, not retroactively rewrite unrelated historical evidence unless gates require it.

## Worker instructions

- Implement only P42.
- Do not commit.
- Do not weaken harness or safety rules.
- Keep merge order intact and reuse the same effective-profile resolver everywhere.
- Prefer fail-closed semantics for explicit unsafe settings; use degradation only for auto-derived values and always record the reason.
- Run focused tests before real gates, then run P42 precheck/run/postcheck only after real evidence and review artifacts are in place.
