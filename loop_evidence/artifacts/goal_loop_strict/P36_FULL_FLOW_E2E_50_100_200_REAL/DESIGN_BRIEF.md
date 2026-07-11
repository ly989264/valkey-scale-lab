# DESIGN_BRIEF — P36_FULL_FLOW_E2E_50_100_200_REAL

## Fresh read confirmation

Read and used the strict design prompt, `AGENTS.md`, `CODEX_START_HERE.md`, `CODEX_GOAL_LOOP_START.md`, `CODEX_STRICT_MATRIX_LOOP_START.md`, all required `docs/codex/goal-loop/` and `docs/codex/goal-loop-strict/` core documents, `docs/codex/goal-loop-strict/stages/P36_FULL_FLOW_E2E_50_100_200_REAL.md`, `artifacts/goal_loop_strict/P36_FULL_FLOW_E2E_50_100_200_REAL/CONTEXT_RELOAD.md`, and `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md`.

This design is bounded to P36 only. It does not include P37 dry-run, P38 cross-scale analysis, P39 visual report quality, or P40 final audit work except where P36 artifact provenance must be compatible with those later stages.

## Stage objective

P36 must prove an end-to-end real product flow at exact 50, 100, and 200 Valkey nodes. For each scale, the flow must include config validation, resource preflight, plan, cluster creation, baseline workload, telemetry collection, a representative management operation sequence, a representative fault/failover sequence, recovery verification, analysis generation from artifacts, report rendering from artifacts, and cleanup verification.

P36 may reuse implementation modules from P30-P35, but it must emit its own P36 artifacts and exact-scale scoped real evidence under `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/`.

## Current repository findings

- `codex/phase_manifest.json` already declares P36 automatic, real-Valkey-required, `max_nodes=200`, and a bounded 200-node exception. Its P36 gates include three `scripts/valkey_e2e_gate.py` runs for `strict_full_flow_50`, `strict_full_flow_100`, and `strict_full_flow_200`, then `assert_full_flow_e2e.py`, exact-scale checks for each scoped evidence directory, quant completeness, lifecycle coverage registry, and cleanup.
- `artifacts/coverage/strict_scenario_plan.json` contains `full_flow_e2e_50_real`, `full_flow_e2e_100_real`, and `full_flow_e2e_200_real` scenarios with lifecycle coverage IDs and representative `fault_sequence` entries.
- `artifacts/coverage/strict_coverage_registry.json` currently has all 36 P36 lifecycle rows in `PENDING` with empty source, validation, metric, cleanup, and review refs.
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/`, `artifacts/gates/P36_FULL_FLOW_E2E_50_100_200_REAL/`, and `audit/P36_FULL_FLOW_E2E_50_100_200_REAL/` do not yet exist.
- `scripts/assert_full_flow_e2e.py` currently verifies only scale presence in `full_flow_matrix.json`, scale presence in `full_flow_results.jsonl`, and `status=PASS`; it does not yet verify the required full-flow step sequence, exact source evidence refs, management/fault orchestration evidence, analysis/report provenance, or cleanup-per-scale.
- `scripts/assert_quant_completeness.py` has only generic `full_flow` handling: it requires `real_valkey_claimed=true` plus the canonical event/metric/window artifacts, but it does not yet enforce P36 lifecycle rows, full-flow windows, or analysis/report provenance.
- `scripts/assert_coverage_registry.py --phase P36... --category lifecycle --scales 50,100,200` currently selects rows but does not by itself require selected lifecycle rows to be `PASS`. This is too weak for the P36 pass criteria.
- `scripts/assert_exact_scale_real_evidence.py` supports P36 scoped evidence through `--artifact-scope full_flow_50|full_flow_100|full_flow_200` and checks parent `cleanup_report.json`.
- `src/valkey_scale_lab/runtime/docker_runtime.py` currently does not list `P36_FULL_FLOW_E2E_50_100_200_REAL/strict_full_flow_*` in `create_scenario`, `_uses_docker_process_runtime`, or `_scenario_node_count_allowed`. 待验证, but present code appears unable to start the P36 scenarios.
- `src/valkey_scale_lab/runtime/docker_runtime.py`, `src/valkey_scale_lab/resource.py`, and `src/valkey_scale_lab/planner/plan.py` currently allow exact 200-node bounded exceptions for P21/P32/P35 paths, not clearly for P36. This is a likely blocker for `strict_full_flow_200`.
- `templates/configs/scale_200.yaml` keeps `default_max_nodes: 100` and `bounded_exception_phase: P21_FAILOVER_LATENCY_CURVE_200`; `scripts/safety_scan.py` explicitly permits this marker. Avoid changing the default cap or enabling broad >100 real execution.
- `src/valkey_scale_lab/cli.py` exposes `config validate`, `plan`, `gate scenario`, `gate cleanup`, `fault apply`, `fault clear`, `analyze`, and `report`. The `plan` and `config validate` commands do not currently accept a phase/scenario bounded-exception context.
- P30-P32 artifacts show exact-scale real management evidence; P33-P35 artifacts show exact-scale real fault/failover evidence. P36 must not merely cite those as runtime proof; it needs new P36 exact-scale evidence and P36 lifecycle source artifacts.

## Scope boundaries

- Do implement only P36 lifecycle/full-flow orchestration and the harness checks needed to make P36 fail closed.
- Do not mark management or fault rows as newly satisfied by P36. P36 targets lifecycle coverage IDs only.
- Do not rerun every P30-P35 matrix row unless needed by the chosen implementation. A representative management sequence and representative fault/failover sequence are sufficient for the P36 stage contract, provided the artifacts prove real execution through orchestration.
- Do not change `default_max_nodes` from 100.
- Do not alter `P14_SCALE_1000_OPTIN_DRYRUN` behavior.
- Do not start real clusters above 200 nodes.
- Do not mutate host firewall, routing, PF, nftables, iptables, host interfaces, or global OS network services.

## Implementation plan

1. Add P36 scenario support to the runtime:
   - Accept `strict_full_flow_50`, `strict_full_flow_100`, and `strict_full_flow_200` for `P36_FULL_FLOW_E2E_50_100_200_REAL`.
   - Use the Docker process runtime path used by P30-P35 for large exact-scale scenarios.
   - Add exact node-count validation for 50/100/200 and fail if the observed/requested node count differs.
   - Add P36 to exact-200 bounded exception logic in runtime/resource/planner paths without changing the global default cap.

2. Build a P36 full-flow artifact producer:
   - Prefer a focused helper in `src/valkey_scale_lab/runtime/docker_runtime.py` or a new narrowly scoped module such as `src/valkey_scale_lab/orchestrator/full_flow.py`, called from `create_scenario` after cluster creation and before cleanup.
   - For each scale, write scoped artifacts under `full_flow_<scale>/` for config validation, resource preflight, cluster plan, run state, workload/recovery observations, management/fault orchestration evidence, analysis summary, report index, and scoped cleanup/evidence refs.
   - Update aggregate parent artifacts after each scale so the final parent directory contains all required P36 artifacts.

3. Full-flow sequence details per scale:
   - `config_validate`: generate a scoped config validation artifact. For 200 nodes, use a P36-aware bounded exception path; do not silently ignore `NODE_CAP_EXCEEDED` except for exact P36/200 with preflight.
   - `resource_preflight`: run `run_resource_preflight(..., phase_id=P36, scenario=strict_full_flow_<scale>)`; block if `can_run=false`.
   - `plan_cluster`: generate a P36-scoped plan with exact node count and bounded exception metadata for 200.
   - `create_cluster`, `meet_nodes`, `assign_slots`, `add_replica`: source from the live cluster bootstrap state and Valkey probes created by `valkey_e2e_gate.py`.
   - `baseline_workload`: run non-zero data-path/workload probes and emit workload windows.
   - `telemetry_collect`: emit strict event and metric rows with P36 lifecycle coverage IDs.
   - Representative management: execute at least one real management operation through the same owned runtime command path used by P30, such as a small explicit reshard/slot verification or a safe replica-first restart. Record command, topology before/after, workload impact, and source evidence under P36 artifacts.
   - Representative fault/failover: execute at least one real fault/failover action through project fault/runtime controls, such as `node_stop` on a replica or a bounded primary failover probe. Record apply/clear, recovery verification, topology before/during/after, workload impact, and no host-network mutation evidence.
   - `analysis_build`: run or call analysis generation from P36 JSON/JSONL artifacts only; write scoped analysis and source provenance.
   - `report_render`: run or call report rendering from P36 analysis artifacts only; write scoped report index and generated report paths.
   - `cleanup_verify`: preserve per-scale cleanup results from `valkey_e2e_gate.py` and aggregate them into parent `cleanup_report.json`.

4. Coverage update:
   - Produce `coverage_ledger.json` as a strict coverage registry-shaped artifact containing all 145 rows, with only the 36 P36 lifecycle rows updated to `PASS`.
   - Update `artifacts/coverage/strict_coverage_registry.json` with the same P36 lifecycle `PASS` transitions after source artifacts exist.
   - Each P36 lifecycle row must include `source_artifacts`, `validation_artifacts`, `metric_refs`, `cleanup_ref`, and `review_ref`.

5. Aggregate artifacts:
   - `full_flow_matrix.json` should list all three scales, expected lifecycle steps, representative management/fault steps, status, and source refs.
   - `full_flow_results.jsonl` should contain one row per scale with exact node count, all required step statuses, evidence refs, analysis/report refs, cleanup refs, and non-empty management/fault execution refs.
   - `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, and `quant_summary.json` should aggregate P36-scoped data from all three scales and use `MISSING` or `SKIPPED_WITH_REASON` with reasons where allowed. Required lifecycle data for a passing P36 row should not be missing.

## Harness plan

- Strengthen `scripts/assert_full_flow_e2e.py` to fail closed on:
  - missing any of scales 50/100/200;
  - `nodes_requested` or `nodes_observed` mismatch;
  - missing required sequence steps;
  - step status not `PASS`;
  - missing source evidence refs for each step;
  - missing management and fault orchestration execution refs;
  - analysis/report refs missing or not generated from P36 artifacts;
  - cleanup not `PASS` per scale;
  - 200-node downshift or dry-run substitution.
- Strengthen P36 handling in `scripts/assert_quant_completeness.py` for `--category full_flow` to validate P36-specific lifecycle coverage, event/metric dimensions, workload windows, and runtime claims. P36 should require `real_valkey_claimed=true`, `management_runtime_claimed=true`, and `fault_runtime_claimed=true` or a similarly explicit `full_flow_runtime_claimed=true` plus management/fault execution evidence. The current schema requires management/fault booleans, so using them is simplest.
- Strengthen `scripts/assert_coverage_registry.py` selected-row behavior for P36 lifecycle rows so `--phase P36 --category lifecycle --scales 50,100,200` requires all selected rows to be `PASS` and to include source/validation/metric/cleanup/review refs.
- Keep `scripts/assert_exact_scale_real_evidence.py` artifact-scope behavior; optionally strengthen it to verify scoped evidence `scenario` matches `strict_full_flow_<scale>` and parent cleanup contains the matching scale entry.
- Add focused unit/integration tests for the strengthened assertions, P36 scenario allowlists, and exact 200 bounded exception behavior.

## Schema and artifact plan

Required P36 artifacts:

- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/phase_summary.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_matrix.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_results.jsonl`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_50/valkey_e2e_evidence.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_100/valkey_e2e_evidence.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_200/valkey_e2e_evidence.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/events.jsonl`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/metrics_timeseries.jsonl`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/workload_windows.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/quant_summary.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/coverage_ledger.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/cleanup_report.json`

Recommended additional P36 artifacts:

- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_<scale>/config_validation_report.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_<scale>/resource_preflight.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_<scale>/cluster_plan.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_<scale>/run_state.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_<scale>/management_sequence.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_<scale>/fault_sequence.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_<scale>/analysis_summary.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_<scale>/report_index.json`
- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/full_flow_<scale>/cleanup_report.json`

Schema changes likely needed:

- Add `schemas/artifact/full_flow_matrix.schema.json`.
- Add `schemas/artifact/full_flow_result.schema.json`.
- Update `codex/phase_manifest.json` P36 artifact schemas from `strict_generic_report.schema.json` to the new schemas if the harness lock/update policy permits. If manifest schema changes are not made, assertion scripts must enforce the stronger semantics.

## Coverage IDs targeted

P36 targets exactly these lifecycle IDs:

```text
50.lifecycle.config_validate
50.lifecycle.resource_preflight
50.lifecycle.plan_cluster
50.lifecycle.create_cluster
50.lifecycle.meet_nodes
50.lifecycle.assign_slots
50.lifecycle.add_replica
50.lifecycle.baseline_workload
50.lifecycle.telemetry_collect
50.lifecycle.analysis_build
50.lifecycle.report_render
50.lifecycle.cleanup_verify
100.lifecycle.config_validate
100.lifecycle.resource_preflight
100.lifecycle.plan_cluster
100.lifecycle.create_cluster
100.lifecycle.meet_nodes
100.lifecycle.assign_slots
100.lifecycle.add_replica
100.lifecycle.baseline_workload
100.lifecycle.telemetry_collect
100.lifecycle.analysis_build
100.lifecycle.report_render
100.lifecycle.cleanup_verify
200.lifecycle.config_validate
200.lifecycle.resource_preflight
200.lifecycle.plan_cluster
200.lifecycle.create_cluster
200.lifecycle.meet_nodes
200.lifecycle.assign_slots
200.lifecycle.add_replica
200.lifecycle.baseline_workload
200.lifecycle.telemetry_collect
200.lifecycle.analysis_build
200.lifecycle.report_render
200.lifecycle.cleanup_verify
```

P36 should reference P30-P35 management/fault modules as execution evidence for representative sequence steps, but it should not change ownership or status semantics for `*.management.*` or `*.fault.*` rows.

## Exact files likely to change

Likely source/runtime:

- `src/valkey_scale_lab/runtime/docker_runtime.py`
- `src/valkey_scale_lab/resource.py`
- `src/valkey_scale_lab/planner/plan.py`
- `src/valkey_scale_lab/config/validation.py` or `src/valkey_scale_lab/cli.py` if config validation/plan need bounded-exception context
- `src/valkey_scale_lab/analysis/summary.py` or a new P36-specific analysis helper
- `src/valkey_scale_lab/report/render.py` or a new P36-specific report helper
- Optional new module: `src/valkey_scale_lab/orchestrator/full_flow.py`

Likely harness:

- `scripts/assert_full_flow_e2e.py`
- `scripts/assert_quant_completeness.py`
- `scripts/assert_coverage_registry.py`
- `scripts/assert_exact_scale_real_evidence.py` if scoped cleanup/source checks are strengthened
- `codex/phase_manifest.json` only if new schemas or a build gate are added
- `codex/gate_lock.json` if locked harness files or schemas change; update transparently and cite in worker/review artifacts

Likely schemas:

- `schemas/artifact/full_flow_matrix.schema.json`
- `schemas/artifact/full_flow_result.schema.json`

Likely tests:

- `tests/unit/test_goal_loop_assertions.py`
- `tests/unit/test_strict_coverage_registry.py`
- New or existing `tests/unit/test_full_flow_e2e_assertion.py`
- `tests/integration/test_goal_loop_manifest.py`
- `tests/planner/test_planner.py`
- `tests/config/test_config_validation.py` if config validation gets P36 bounded-exception context
- `tests/integration/test_docker_runtime_contract.py` for P36 scenario allowlist/node-count behavior without starting large clusters

Generated/updated artifacts during worker:

- `artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/**`
- `artifacts/gates/P36_FULL_FLOW_E2E_50_100_200_REAL/**`
- `artifacts/coverage/strict_coverage_registry.json`
- `artifacts/goal_loop_strict/P36_FULL_FLOW_E2E_50_100_200_REAL/WORKER_SUMMARY.md`
- `artifacts/goal_loop_strict/P36_FULL_FLOW_E2E_50_100_200_REAL/REVIEW.md`
- `audit/P36_FULL_FLOW_E2E_50_100_200_REAL/AUDIT.md`
- `audit/P36_FULL_FLOW_E2E_50_100_200_REAL/audit_decision.json`

## Test and gate plan

Fast pre-real checks:

```bash
python3 scripts/codex_gate.py precheck --phase P36_FULL_FLOW_E2E_50_100_200_REAL
python3 scripts/safety_scan.py
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
python3 scripts/assert_strict_stage_contract.py --phase P36_FULL_FLOW_E2E_50_100_200_REAL
python3 scripts/assert_no_bypass.py --phase P36_FULL_FLOW_E2E_50_100_200_REAL
```

P36 stage gates:

```bash
python3 scripts/codex_gate.py run --phase P36_FULL_FLOW_E2E_50_100_200_REAL
python3 scripts/assert_full_flow_e2e.py --phase P36_FULL_FLOW_E2E_50_100_200_REAL --scales 50,100,200
python3 scripts/assert_exact_scale_real_evidence.py --phase P36_FULL_FLOW_E2E_50_100_200_REAL --nodes 50 --artifact-scope full_flow_50
python3 scripts/assert_exact_scale_real_evidence.py --phase P36_FULL_FLOW_E2E_50_100_200_REAL --nodes 100 --artifact-scope full_flow_100
python3 scripts/assert_exact_scale_real_evidence.py --phase P36_FULL_FLOW_E2E_50_100_200_REAL --nodes 200 --artifact-scope full_flow_200
python3 scripts/assert_quant_completeness.py --phase P36_FULL_FLOW_E2E_50_100_200_REAL --category full_flow
python3 scripts/assert_coverage_registry.py --phase P36_FULL_FLOW_E2E_50_100_200_REAL --category lifecycle --scales 50,100,200
python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P36_FULL_FLOW_E2E_50_100_200_REAL/cleanup_report.json
```

Closeout commands after worker and review pass:

```bash
python3 scripts/codex_gate.py postcheck --phase P36_FULL_FLOW_E2E_50_100_200_REAL
python3 scripts/codex_gate.py mark-complete --phase P36_FULL_FLOW_E2E_50_100_200_REAL
```

## Safety constraints

- 200 nodes are allowed only as the P36 exact bounded exception after resource preflight passes.
- Do not downshift 200 to 100.
- Do not fake Valkey or replay prior logs as P36 runtime proof.
- Do not run real clusters above 200 nodes.
- Do not use `sudo` for network, route, firewall, or interface changes.
- Do not mutate host PF, nftables, iptables, routes, interfaces, or OS network services.
- Fault behavior must use owned Docker/process controls, container namespaces, or project-owned sandbox proxy paths.
- Every process/container must have deterministic labels, state files, and cleanup.
- Do not manually edit gate results or phase state to force PASS.
- Do not commit or push from the worker before gates, review, postcheck, and mark-complete pass.

## Blocked conditions

- Docker/runtime unavailable for the required exact-scale runs.
- Resource preflight `can_run=false` for 50, 100, or 200.
- P36 200-node runtime cannot be allowed without weakening `default_max_nodes=100`.
- Any scale is omitted.
- `nodes_requested` or `nodes_observed` differs from the required scale.
- Representative management/fault sequence is only imported or described, not executed.
- Analysis/report artifacts are generated from fake data, prior logs, or non-P36 source artifacts.
- Required events, metrics, workload windows, or provenance are missing, `null`, `NaN`, `undefined`, or silently omitted.
- Cleanup fails for any scale or aggregate cleanup reports remaining owned resources.
- Coverage registry lifecycle rows remain `PENDING`, `MISSING`, `BLOCKED`, or lack source/validation refs.

## Risks

- The current P36 scenario names appear unsupported by runtime allowlists, so the first real P36 wrapper gate is likely to fail until scenario support is added.
- The exact-200 bounded-exception logic is split across runtime, resource preflight, planner, config/CLI behavior, and safety scan expectations. A narrow, consistent P36 allowance is needed.
- Current full-flow, quant, and coverage assertions are too weak to guard against placeholder P36 artifacts. Strengthening them is necessary before treating any P36 run as meaningful.
- Full-flow representative management/fault steps may extend runtime duration at 100/200 nodes; lower non-zero workload QPS is allowed only with recorded reason.
- `codex/gate_lock.json` may need an intentional update if locked harness files or schemas are changed. This must be documented as strengthening, not bypass.

## 待验证

- 待验证: whether the worker should implement P36 artifact generation inside `docker_runtime.py` or as a new `valkey_scale_lab.orchestrator.full_flow` module called by the runtime.
- 待验证: exact representative management operation best suited for P36 duration and safety at 200 nodes.
- 待验证: exact representative fault/failover operation best suited for P36 duration and safety at 200 nodes.
- 待验证: whether `config validate` and `plan` should gain optional phase/scenario arguments, or whether P36 can validly record bounded-exception validation/plan artifacts through internal APIs while preserving CLI backward compatibility.
- 待验证: whether new full-flow schemas should replace the manifest's current `strict_generic_report.schema.json` entries during P36, or whether semantic assertion strengthening is sufficient.
- 待验证: whether existing report rendering can consume P36 artifacts directly or needs a small P36-specific report/analysis path.
