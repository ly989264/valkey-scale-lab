# DESIGN_BRIEF - P34_FAULT_FAILOVER_MATRIX_100_REAL

## Stage Objective

Execute and prove the complete strict fault/failover matrix on exactly 100 real Valkey 9.1.x nodes for `P34_FAULT_FAILOVER_MATRIX_100_REAL`.

P34 must not reuse P33's 50-node evidence, downshift node count, substitute dry-run/generated artifacts, skip required rows, or mutate host networking. Passing evidence must show `nodes_requested=100`, `nodes_observed=100`, all 12 `100.fault.*` rows `PASS`, at least three independent `primary_stop_failover` samples, split-brain detectors actually ran, workload impact was measured for every row, and cleanup passed.

## Current Repo Facts

- `docs/codex/goal-loop-strict/stages/P34_FAULT_FAILOVER_MATRIX_100_REAL.md` requires exactly 100 real Valkey nodes and lists the 20 required P34 phase artifacts and 8 required assertions.
- `codex/phase_manifest.json` already has a P34 manifest entry with `max_nodes=100`, `real_valkey_required=true`, `scale_100.yaml`, scenario `strict_fault_matrix_100_fault_failover`, `--min-nodes 100`, and strict assertions for exact scale, fault matrix, failover curve, split brain, quant completeness, coverage registry, no-bypass, and cleanup.
- `templates/configs/scale_100.yaml` defines `cluster.shards=50`, `replicas_per_shard=1`, `port_base=7500`, `cluster_bus_port_base=17500`, `valkey/valkey:9.1.0`, and safety settings that forbid host network mutation.
- `artifacts/coverage/strict_coverage_registry.json` contains 12 P34-owned `100.fault.*` rows, all currently `PENDING`.
- `artifacts/coverage/strict_scenario_plan.json` includes a P34 fault scenario and all 12 `100.fault.*` coverage IDs.
- `scripts/assert_fault_matrix_strict.py`, `scripts/assert_failover_latency_curve.py`, and `scripts/assert_split_brain_report.py` already recognize P34/P35 exact scales.
- `scripts/assert_quant_completeness.py` currently recognizes strict fault semantics only for `P33_FAULT_FAILOVER_MATRIX_50_REAL`; P34 will get only generic checks unless this is strengthened.
- `scripts/fault_failover_gate.py` has a strict fault matrix controller, but it is currently P33/50-specific: constants, config path, resource preflight, coverage IDs, run ID, work dir, sample IDs, event IDs, summaries, `scale`, `node_count`, and fallback rows are hard-coded to P33/50.
- `scripts/fault_failover_gate.py` dispatches the strict controller only when `args.phase == P33_FAULT_FAILOVER_MATRIX_50_REAL` and scenario is `strict_fault_matrix_50_fault_failover`; P34 currently falls through to the older single primary-stop path, which cannot emit the P34 strict artifact family.
- `src/valkey_scale_lab/runtime/docker_runtime.py` admits `P33_FAULT_FAILOVER_MATRIX_50_REAL/strict_fault_matrix_50` through `_p33_fault_matrix_node_count()`, but does not admit `P34_FAULT_FAILOVER_MATRIX_100_REAL/strict_fault_matrix_100`.
- `codex/gate_lock.json` locks `scripts/fault_failover_gate.py`, `scripts/assert_quant_completeness.py`, `src/valkey_scale_lab/runtime/docker_runtime.py` is not listed in the checked subset I inspected, and script edits will require harness-control documentation and lock refresh if hashes change.
- `artifacts/harness_exception/P33_FAULT_FAILOVER_MATRIX_50_REAL.md` is the precedent for documenting locked script strengthening.
- `artifacts/goal_loop_strict/P34_FAULT_FAILOVER_MATRIX_100_REAL/CONTEXT_RELOAD.md` exists and says P34 starts from clean state except the new P34 handoff directory.
- 待验证: whether local Docker resources can actually pass preflight and run exactly 100 Valkey processes during the real gate.
- 待验证: whether the existing P33 controller behavior remains fully stable after parameterization.

## Exact Implementation Plan

1. Document the harness defect before editing locked script controls.
   - Create `artifacts/harness_exception/P34_FAULT_FAILOVER_MATRIX_100_REAL.md`.
   - State that P34 manifest/gates exist but the strict fault controller and quant assertion are P33-only, so leaving them unchanged would weaken/fail the P34 harness.
   - Do not edit gate results, phase state, or prior artifacts to force success.

2. Generalize the P33 strict fault matrix controller into a scale-aware strict fault controller.
   - In `scripts/fault_failover_gate.py`, replace P33-only constants/helpers with a `StrictFaultProfile` or equivalent small table for P33 and P34.
   - P34 profile values:
     - phase: `P34_FAULT_FAILOVER_MATRIX_100_REAL`
     - setup scenario: `strict_fault_matrix_100`
     - wrapper scenario: `strict_fault_matrix_100_fault_failover`
     - scale/node count: `100`
     - config: `templates/configs/scale_100.yaml`
     - work dir suffix: `_p34_fault_matrix_work`
     - state file: `state_fault_matrix_100.json`
     - coverage prefix: `100.fault.`
     - sample prefix: `p34-primary-stop-sample`
     - operation/fault prefix: `p34`
   - Keep P33 behavior byte-semantically equivalent where possible, except for function names and shared helper names.
   - Update all hard-coded `50`, `P33`, `p33`, `strict_fault_matrix_50`, and `scale_50.yaml` values inside strict controller outputs to derive from the selected profile.
   - Ensure P34 artifacts contain `phase_id=stage_id=P34_FAULT_FAILOVER_MATRIX_100_REAL`, `scale=100`, `node_count=100`, `nodes_requested=100`, coverage IDs like `100.fault.network_delay`, and run IDs that cannot collide with P33.
   - Keep network rows using only `sandbox_proxy` or `container_netns_tc`; do not add host firewall, route, interface, PF, nftables, iptables, or `sudo` paths.
   - Keep the P34 `primary_stop_failover` loop at three independent samples and preserve sample independence checks through unique target primary selection, `sample_id`, `run_id`, `state_ref`, and timing signatures.

3. Admit the exact P34 runtime scenario.
   - In `src/valkey_scale_lab/runtime/docker_runtime.py`, replace or extend `_p33_fault_matrix_node_count()` to a strict fault matrix resolver that returns:
     - `50` for `P33_FAULT_FAILOVER_MATRIX_50_REAL/strict_fault_matrix_50`
     - `100` for `P34_FAULT_FAILOVER_MATRIX_100_REAL/strict_fault_matrix_100`
   - Update the scenario allowlist, `_uses_docker_process_runtime()`, and `_scenario_node_count_allowed()` to call the generalized resolver.
   - Add focused tests in `tests/integration/test_docker_runtime_contract.py` proving P34 accepts exactly 100 and rejects 50/99/101/200.
   - Do not enable P35's 200-node runtime in this stage unless a tiny shared helper shape needs a dormant table entry; if present, P35 behavior must remain blocked/not executed until P35.

4. Strengthen quant completeness for P34.
   - In `scripts/assert_quant_completeness.py`, add P34 to `STRICT_FAULT_STAGES` with:
     - `scale=100`
     - `coverage_prefix="100.fault."`
     - the same 12 required rows
     - `min_failover_samples=3`
   - Update any P33-specific error strings in shared strict fault helpers to say strict fault rows rather than P33-only rows.
   - Add focused assertion tests in `tests/unit/test_goal_loop_assertions.py` or a nearby existing assertion test to prove P34 strict quant semantics reject wrong scale, wrong coverage prefix, missing rows, and insufficient samples.

5. Preserve and refresh harness locks only after strengthening checks pass.
   - Because `scripts/*.py` are harness controls, refresh only changed locked hashes in `codex/gate_lock.json` after compile/focused tests/safety scan prove the changes strengthen the harness.
   - Do not alter `codex/phase_manifest.json` unless a manifest defect is discovered. Current P34 manifest commands are already scale-correct.

6. Run the real P34 gate and generate artifacts.
   - The worker/main stage loop should run `python3 scripts/codex_gate.py run --phase P34_FAULT_FAILOVER_MATRIX_100_REAL`.
   - If resource preflight cannot support 100 nodes, write `artifacts/goal_loop_strict/P34_FAULT_FAILOVER_MATRIX_100_REAL/BLOCKED.md`, keep artifacts/status as failing or absent according to the failed command, and stop without mark-complete.
   - If any required row fails, fix only P34-shared code and rerun from the worker step.

## Exact Files Likely To Change

- `scripts/fault_failover_gate.py`: parameterize the P33 strict fault controller and dispatch P34.
- `src/valkey_scale_lab/runtime/docker_runtime.py`: admit exact P34 process-runtime scenario and exact node-count validation.
- `scripts/assert_quant_completeness.py`: add strict P34 fault telemetry semantics.
- `tests/integration/test_docker_runtime_contract.py`: add P34 exact-100 runtime contract tests.
- `tests/unit/test_goal_loop_assertions.py` or another existing assertion-focused unit test: add P34 quant/fault assertion coverage.
- `codex/gate_lock.json`: refresh only hashes for changed locked harness-control files after verification.
- `artifacts/harness_exception/P34_FAULT_FAILOVER_MATRIX_100_REAL.md`: document the harness-control strengthening.
- Stage-generated artifacts under `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/`.
- Global coverage update: `artifacts/coverage/strict_coverage_registry.json` after P34 rows pass.
- Stage handoff/audit artifacts: `WORKER_SUMMARY.md`, `REVIEW.md`, `COMPLETION.md`, `audit/P34_FAULT_FAILOVER_MATRIX_100_REAL/AUDIT.md`, `audit/P34_FAULT_FAILOVER_MATRIX_100_REAL/audit_decision.json`, and `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md`.

## Schemas And Gates

No new schema appears necessary. P34 should use existing schemas:

- `schemas/artifact/phase_summary.schema.json`
- `schemas/artifact/valkey_e2e_evidence.schema.json`
- `schemas/artifact/resource_preflight.schema.json`
- `schemas/artifact/cluster_plan.schema.json`
- `schemas/artifact/strict_generic_report.schema.json`
- `schemas/artifact/cleanup_report.schema.json`
- `schemas/artifact/goal_loop_event.schema.json`
- `schemas/artifact/goal_loop_metric_sample.schema.json`
- `schemas/artifact/workload_windows.schema.json`
- `schemas/artifact/quant_summary.schema.json`
- `schemas/artifact/strict_coverage_registry.schema.json`
- `schemas/artifact/fault_matrix_report.schema.json`
- `schemas/artifact/fault_result.schema.json`
- `schemas/artifact/failover_latency_sample.schema.json`
- `schemas/artifact/failover_latency_curve.schema.json`
- `schemas/artifact/partition_report.schema.json`
- `schemas/artifact/split_brain_report.schema.json`
- `schemas/artifact/workload_impact_report.schema.json`
- `schemas/artifact/topology_snapshot.schema.json`
- `schemas/artifact/command_log_entry.schema.json`

Required gates from the manifest/stage doc:

```bash
python3 scripts/codex_gate.py precheck --phase P34_FAULT_FAILOVER_MATRIX_100_REAL
python3 scripts/safety_scan.py
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
python3 scripts/assert_strict_stage_contract.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL
python3 scripts/assert_no_bypass.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL
python3 scripts/fault_failover_gate.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL --scenario strict_fault_matrix_100_fault_failover --config templates/configs/scale_100.yaml --out artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/valkey_e2e_evidence.json --failover-report artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/failover_report.json --fault-report artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/fault_report.json --workload-window-report artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/workload_windows.json --cleanup-report artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/cleanup_report.json --min-nodes 100 --require-data-path
python3 scripts/assert_exact_scale_real_evidence.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL --nodes 100
python3 scripts/assert_fault_matrix_strict.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL --scale 100 --require-all-rows
python3 scripts/assert_failover_latency_curve.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL --scale 100 --min-samples 3
python3 scripts/assert_split_brain_report.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL --scale 100
python3 scripts/assert_quant_completeness.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL --category fault --scale 100
python3 scripts/assert_coverage_registry.py --phase P34_FAULT_FAILOVER_MATRIX_100_REAL --scale 100 --category fault
python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/cleanup_report.json
```

## Required Artifact List

P34 phase artifacts:

- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/phase_summary.json`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/valkey_e2e_evidence.json`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/resource_preflight.json`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/cluster_plan.json`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/run_state.json`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/cleanup_report.json`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/events.jsonl`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/metrics_timeseries.jsonl`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/workload_windows.json`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/quant_summary.json`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/coverage_ledger.json`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/fault_matrix_report.json`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/fault_operation_results.jsonl`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/failover_samples.jsonl`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/failover_latency_curve.json`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/partition_report.json`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/split_brain_report.json`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/fault_workload_impact.json`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/fault_topology_snapshots.jsonl`
- `artifacts/phases/P34_FAULT_FAILOVER_MATRIX_100_REAL/fault_command_log.jsonl`

P34 loop/audit artifacts:

- `artifacts/goal_loop_strict/P34_FAULT_FAILOVER_MATRIX_100_REAL/DESIGN_BRIEF.md`
- `artifacts/goal_loop_strict/P34_FAULT_FAILOVER_MATRIX_100_REAL/WORKER_SUMMARY.md`
- `artifacts/goal_loop_strict/P34_FAULT_FAILOVER_MATRIX_100_REAL/REVIEW.md`
- `artifacts/goal_loop_strict/P34_FAULT_FAILOVER_MATRIX_100_REAL/COMPLETION.md` only after pass
- `artifacts/goal_loop_strict/P34_FAULT_FAILOVER_MATRIX_100_REAL/BLOCKED.md` only if blocked
- `audit/P34_FAULT_FAILOVER_MATRIX_100_REAL/AUDIT.md`
- `audit/P34_FAULT_FAILOVER_MATRIX_100_REAL/audit_decision.json`
- `artifacts/gates/P34_FAULT_FAILOVER_MATRIX_100_REAL/gate_result.json`
- `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md`

## Coverage IDs Targeted

- `100.fault.primary_stop_failover`
- `100.fault.replica_stop`
- `100.fault.node_host_stop`
- `100.fault.az_stop`
- `100.fault.network_delay`
- `100.fault.network_loss`
- `100.fault.network_flap`
- `100.fault.network_partition`
- `100.fault.minority_partition`
- `100.fault.majority_partition`
- `100.fault.split_brain_window_detection`
- `100.fault.fault_period_workload_impact`

## Commands To Run

Focused pre-real verification after edits:

```bash
PYTHONPYCACHEPREFIX=/tmp/vslab-p34-pycache python3 -m compileall -q scripts src
python3 -m pytest -q -p no:cacheprovider tests/fault tests/failover tests/unit/test_goal_loop_assertions.py tests/integration/test_docker_runtime_contract.py
python3 scripts/safety_scan.py
python3 scripts/codex_gate.py precheck --phase P34_FAULT_FAILOVER_MATRIX_100_REAL
```

Full required gate:

```bash
python3 scripts/codex_gate.py run --phase P34_FAULT_FAILOVER_MATRIX_100_REAL
```

Post-review close commands only after worker artifacts, real gates, review, and audit pass:

```bash
python3 scripts/codex_gate.py postcheck --phase P34_FAULT_FAILOVER_MATRIX_100_REAL
python3 scripts/codex_gate.py mark-complete --phase P34_FAULT_FAILOVER_MATRIX_100_REAL
git status --short
git add <intentional P34 files>
git commit -m "P34_FAULT_FAILOVER_MATRIX_100_REAL: prove 100-node fault matrix"
git push
```

Do not run mark-complete, commit, or push from the design subagent.

## Safety Constraints

- Run exactly 100 real nodes for P34; no downshift and no dry-run substitution.
- Never default to 1000 nodes and never start real execution above 200 nodes.
- Do not mutate physical host network config.
- Do not use host firewall, routing, PF, nftables, iptables, host interface changes, OS network services, or `sudo` for network mutation.
- Network faults must use `sandbox_proxy` or container namespace `tc/netem` scoped to owned containers only.
- Every started process/container must be owned/labeled and cleaned through deterministic cleanup.
- Resource preflight must pass with `can_run=true`; if not, P34 is blocked.
- Missing values must be encoded as `MISSING` or `SKIPPED_WITH_REASON` with a reason; required P34 rows may not pass as skipped/missing.
- Do not manually edit `codex/status/phase_state.json`, gate results, or artifacts to manufacture PASS.

## Blocked Conditions

- `resource_preflight.json` has `can_run=false` or `status!=PASS`.
- `valkey_e2e_evidence.json` does not show `nodes_requested=100` and `nodes_observed=100`.
- Any Valkey version does not start with `9.1.`.
- Any required `100.fault.*` row is missing, skipped, or not `PASS`.
- `primary_stop_failover` has fewer than three independent real samples.
- Network fault implementation requires host-level mutation.
- Partition reports lack majority/minority/isolated groups or feasible side probes.
- Split-brain report records `split_brain_window_ms=0` without detector evidence that all required detectors actually ran.
- Workload event window or workload impact reference is missing for any fault row.
- Cleanup does not pass or leaves owned resources.
- Review or audit is missing or not `Decision: PASS`.

## Review Focus Points

- Confirm the strict controller is genuinely scale-parameterized and P34 artifacts contain no stale `50.fault.*`, `node_count=50`, `scale=50`, `P33`, `p33`, or `strict_fault_matrix_50` values except in compatibility code/tests.
- Confirm `scripts/fault_failover_gate.py` dispatches P34 to the strict matrix controller, not the legacy single primary-stop path.
- Confirm `src/valkey_scale_lab/runtime/docker_runtime.py` admits only exact P34/100 and rejects smaller/larger P34 counts.
- Confirm `scripts/assert_quant_completeness.py` applies strict fault semantics to P34, not just generic quant checks.
- Confirm P33 artifacts and behavior remain compatible after refactor.
- Confirm failover samples use unique sample IDs, run IDs, state refs, target/timing signatures, and real Valkey probe evidence.
- Confirm network rows use `sandbox_proxy` or `container_netns_tc` only and safety scan/no-bypass do not report host network mutation.
- Confirm global coverage registry updates only the 12 P34 rows and preserves immutable fields.
- Confirm `gate_result.json`, review, audit, and postcheck cite all required artifacts and the gate result SHA.
