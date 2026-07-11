# DESIGN_BRIEF - P33_FAULT_FAILOVER_MATRIX_50_REAL

## Fresh read confirmation

Read the required documents in the order specified by `docs/codex/goal-loop-strict/00_INDEX.md`, including `AGENTS.md`, `CODEX_START_HERE.md`, `CODEX_GOAL_LOOP_START.md`, `CODEX_STRICT_MATRIX_LOOP_START.md`, all listed legacy goal-loop docs, all listed strict-loop docs, `docs/codex/goal-loop-strict/stages/P33_FAULT_FAILOVER_MATRIX_50_REAL.md`, `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md`, and the strict design template. Also inspected P30-P32 handoff artifacts, strict manifest entries, fault runtime code, fault/failover gate code, assertion scripts, schemas, and coverage registry helpers. Current observed git status before writing this file: only `artifacts/goal_loop_strict/P33_FAULT_FAILOVER_MATRIX_50_REAL/` is untracked because the main agent added `CONTEXT_RELOAD.md`; this design pass writes only this design brief.

## Stage objective

Execute and quantify the complete strict fault/failover matrix on exactly 50 real Valkey 9.1.x nodes. P33 can pass only if resource preflight records `can_run=true`, `nodes_requested=50`, `nodes_observed=50`, all 12 required `50.fault.*` rows are `PASS`, `primary_stop_failover` has at least three independent real samples, network faults use `container_netns_tc` or `sandbox_proxy`, partition probes compare sides where feasible, split-brain detectors actually ran, workload impact is measured for every row, coverage registry rows for `50.fault.*` are `PASS`, cleanup is `PASS`, and review/audit pass.

## Current repository findings

- `docs/codex/goal-loop-strict/stages/P33_FAULT_FAILOVER_MATRIX_50_REAL.md` requires exact 50 real nodes, the full 12-row fault matrix, three primary failover samples, strict telemetry artifacts, fault reports, split-brain detector evidence, workload impact, cleanup, and registry PASS rows.
- `codex/phase_manifest.json` already declares P33 automatic, `real_valkey_required=true`, `max_nodes=50`, and required artifacts under `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/`.
- The P33 manifest command calls `scripts/fault_failover_gate.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL --scenario strict_fault_matrix_50_fault_failover --config templates/configs/scale_50.yaml ... --min-nodes 50 --require-data-path`.
- `templates/configs/scale_50.yaml` defines a 25-shard, one-replica cluster for exactly 50 nodes using `valkey/valkey:9.1.0`, ports `7400-7449` and bus ports `17400-17449`, sandbox network required, and host network mutation forbidden.
- `scripts/fault_failover_gate.py` has real primary-stop controller logic for P20/P21 and a single primary-stop path for other phases, but it does not yet produce the complete P33 artifact set: `fault_operation_results.jsonl`, `failover_samples.jsonl`, `failover_latency_curve.json`, `partition_report.json`, `split_brain_report.json`, `fault_topology_snapshots.jsonl`, `fault_command_log.jsonl`, `coverage_ledger.json`, `resource_preflight.json`, `cluster_plan.json`, `run_state.json`, and P33-specific `phase_summary.json`/`quant_summary.json`.
- `scripts/assert_failover_latency_curve.py` currently accepts only `--phase`; P33 manifest already passes `--scale 50 --min-samples 3`, so the script must be strengthened to parse and validate strict P33-P35 curves.
- `scripts/assert_split_brain_report.py` currently accepts only `--phase` and validates only `P24_PARTITION_SPLIT_BRAIN_MATRIX`; P33 manifest already passes `--scale 50`, so the script must be generalized for strict P33-P35 while preserving P24 behavior.
- `scripts/assert_fault_matrix_strict.py` checks row presence and PASS status but is loose: it reads `faults` or `rows`, while the schema uses `fault_rows`, and it does not yet enforce required P33 result fields, implementation paths, partition groups, detector references, workload refs, or three independent failover samples.
- `scripts/assert_quant_completeness.py` has strong P29 and P30-P32 management semantics, but no strict fault-stage semantics for P33/P34/P35. P33 needs exact fault telemetry checks, not just artifact presence.
- `scripts/assert_workload_impact.py` already validates older P22-P24 fault workload patterns but does not yet cover strict P33 all-row exact-scale workload impact.
- `src/valkey_scale_lab/fault/sandbox.py` supports `node_stop`, `network_delay`, `network_loss`, `network_partition`, and `network_flap`; network faults are recorded with `sandbox_proxy` or `container_netns_tc` implementation paths and forbid host network mutation.
- `src/valkey_scale_lab/fault/network_proxy.py` provides a project-owned `SandboxNetworkProxy` for delay/loss/flap behavior. Partition behavior through proxy or owned Docker network control for P33 is 待验证.
- `src/valkey_scale_lab/runtime/docker_runtime.py` contains the P30-P32 strict management artifact and coverage update pattern, including exact-scale telemetry, workload windows, command logs, topology snapshots, `coverage_ledger.json`, and global `artifacts/coverage/strict_coverage_registry.json` updates.
- `scripts/strict_coverage_defs.py` defines required P33 rows as `50.fault.primary_stop_failover`, `50.fault.replica_stop`, `50.fault.node_host_stop`, `50.fault.az_stop`, `50.fault.network_delay`, `50.fault.network_loss`, `50.fault.network_flap`, `50.fault.network_partition`, `50.fault.minority_partition`, `50.fault.majority_partition`, `50.fault.split_brain_window_detection`, and `50.fault.fault_period_workload_impact`.
- `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md` records P30-P32 exact-scale management PASS rows only; it explicitly says P33 must begin exact 50-node real fault/failover without reusing management evidence as fault evidence.

## Scope boundaries

Implement only P33. Do not implement P34/P35 scale changes except by writing reusable, scale-parameterized helpers that are necessary for P33 and naturally support later strict fault stages. Do not mark lifecycle/full-flow rows, management rows, P34/P35 rows, or >200 dry-run rows as PASS. Do not weaken harness controls, edit phase state, edit gate results, fabricate artifacts, downshift below 50 nodes, or use fake Valkey evidence.

## Implementation plan

1. Add a strict P33 controller path to `scripts/fault_failover_gate.py`.
   - Detect `phase in {P33_FAULT_FAILOVER_MATRIX_50_REAL}` and `scenario == strict_fault_matrix_50_fault_failover`.
   - Require `--min-nodes 50`, `templates/configs/scale_50.yaml`, `--fault-report`, `--workload-window-report`, and `--cleanup-report`.
   - Run resource preflight before starting runtime and write `resource_preflight.json`; if `can_run=false`, write `BLOCKED.md`, fail the gate, and do not emit passing artifacts.
   - Start one exact 50-node cluster through `python3 -m valkey_scale_lab.cli gate scenario` or equivalent existing runtime path, record `run_state.json`, `cluster_plan.json`, and live version/topology proof.
   - Preserve deterministic setup and cleanup paths from existing runtime; all owned resources must be cleaned even on fault failure.

2. Execute all required fault rows on real 50-node Valkey evidence.
   - `primary_stop_failover`: run at least three independent real samples. Use distinct sample IDs, target primaries, state refs, timing signatures, and workload refs; record promotion, slot coverage, read/write recovery, cleanup ref, and split-brain detector ref for each sample.
   - `replica_stop`: target a live replica, stop through owned runtime/fault API, verify no unintended promotion is counted as success, measure workload impact, restore, and verify cleanup.
   - `node_host_stop`: map logical host IDs from the plan/state, stop all nodes on one logical host through owned controls, record role/AZ/slot impact, restore group, and measure recovery.
   - `az_stop`: target a virtual AZ from placement, stop all nodes in that AZ, record minority/majority implications, measure workload and split-brain indicators, restore, and verify cleanup.
   - `network_delay`, `network_loss`, and `network_flap`: use `sandbox_proxy` or `container_netns_tc` only; record parameters, direction, target set, duration, observed proxy/netns effect, workload impact, and recovery.
   - `network_partition`, `minority_partition`, and `majority_partition`: record majority/minority/isolated groups, block-between-groups policy, within-group allowance, side-specific probes where feasible, workload impact, and recovery.
   - `split_brain_window_detection`: run detectors for overlapping primary slot claims, divergent partition-side cluster views, conflicting write probes, and old-primary write acceptance after promotion. `split_brain_window_ms=0` is allowed only when detector evidence says they ran and observed no indicator.
   - `fault_period_workload_impact`: aggregate per-row windows and comparisons for every fault row; this row should PASS only when all row impact refs are present.

3. Produce canonical P33 artifacts from the real run.
   - Write JSONL artifacts directly from observed commands/probes/workload samples: `events.jsonl`, `metrics_timeseries.jsonl`, `fault_operation_results.jsonl`, `failover_samples.jsonl`, `fault_topology_snapshots.jsonl`, and `fault_command_log.jsonl`.
   - Write JSON artifacts: `phase_summary.json`, `valkey_e2e_evidence.json`, `resource_preflight.json`, `cluster_plan.json`, `run_state.json`, `cleanup_report.json`, `workload_windows.json`, `quant_summary.json`, `coverage_ledger.json`, `fault_matrix_report.json`, `failover_latency_curve.json`, `partition_report.json`, `split_brain_report.json`, and `fault_workload_impact.json`.
   - Use `MISSING` objects/strings with reasons only for non-core optional values such as `old_primary_rejoined_at_ms`; required row evidence must not be missing in a PASS stage.

4. Add or strengthen strict P33 assertions.
   - Update `scripts/assert_failover_latency_curve.py` to accept `--scale` and `--min-samples`, recognize P33/P34/P35 strict fault stages, validate `failover_samples.jsonl` and `failover_latency_curve.json`, require exact node count, unique sample IDs/run IDs/state refs/timing signatures, numeric required timestamps, sample_count >= 3, cleanup PASS, workload refs, and derived p50/p95/max from raw samples.
   - Update `scripts/assert_split_brain_report.py` to accept `--scale`, validate P33/P34/P35 reports, require exact scale/node count, non-empty detector results, side view comparisons, core detectors run for zero-window claims, and indicator consistency.
   - Strengthen `scripts/assert_fault_matrix_strict.py` to read `fault_rows` as canonical, require all 12 rows, require exact `50.fault.*` coverage IDs, exact node count, PASS status, `real_execution_verified=true`, allowed implementation paths, required fault result fields, non-empty source evidence refs, partition group evidence, split-brain report refs, workload refs, and cleanup verification.
   - Extend `scripts/assert_quant_completeness.py` for strict P33 fault semantics: exact scale 50, `fault_runtime_claimed=true`, 12 PASS coverage rows, at least three failover samples, canonical event/metric fields, workload source metrics, no forbidden null/NaN/undefined placeholders, and strict artifact counts.
   - Extend `scripts/assert_workload_impact.py` only if the manifest or worker adds it to P33 gates; otherwise keep P33 workload checks inside `assert_quant_completeness.py` and `assert_fault_matrix_strict.py`.

5. Update coverage from evidence only.
   - Add helper logic analogous to P30 `_p30_coverage_ledger`/`_p30_update_global_coverage_registry`, scoped to fault rows.
   - `coverage_ledger.json` should be a strict registry snapshot with exactly the 12 `50.fault.*` rows updated to `PASS`, source artifacts pointing to P33 real evidence, validation artifacts pointing to P33 strict reports/assertions, metric refs pointing to `metrics_timeseries.jsonl`, cleanup ref pointing to P33 cleanup, review ref pointing to P33 review, and commit SHA left as `PENDING_REVIEW_AND_COMMIT` until completion.
   - Global `artifacts/coverage/strict_coverage_registry.json` should update only P33-owned `50.fault.*` rows. Preserve prior P30-P32 management PASS rows and leave P34/P35 fault, lifecycle/full-flow, and dry-run rows pending.

6. Add focused tests without fake-only pass evidence.
   - Unit tests should validate assertion failures for missing P33 rows, skipped rows, wrong node count, bad network implementation path, insufficient failover samples, zero split-brain window without detectors, missing workload refs, and invalid coverage transitions.
   - Integration-level tests should validate P33 manifest command compatibility and argument parsing for `--scale`/`--min-samples`, plus fault sandbox safety around no host network mutation.
   - Tests may use fixtures for assertion behavior, but real P33 PASS evidence must come only from the live gate.

## Harness plan

Expected development and stage commands:

```bash
python3 scripts/codex_gate.py precheck --phase P33_FAULT_FAILOVER_MATRIX_50_REAL
python3 scripts/safety_scan.py
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
python3 scripts/assert_strict_stage_contract.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL
python3 scripts/assert_no_bypass.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL
python3 scripts/codex_gate.py run --phase P33_FAULT_FAILOVER_MATRIX_50_REAL
python3 scripts/assert_exact_scale_real_evidence.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL --nodes 50
python3 scripts/assert_fault_matrix_strict.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL --scale 50 --require-all-rows
python3 scripts/assert_failover_latency_curve.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL --scale 50 --min-samples 3
python3 scripts/assert_split_brain_report.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL --scale 50
python3 scripts/assert_quant_completeness.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL --category fault --scale 50
python3 scripts/assert_coverage_registry.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL --scale 50 --category fault
python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/cleanup_report.json
python3 scripts/codex_gate.py postcheck --phase P33_FAULT_FAILOVER_MATRIX_50_REAL
```

If Python cache writes fail in the sandbox, use `PYTHONPYCACHEPREFIX=/tmp/vslab-p33-pycache`. If locked harness files are strengthened, refresh `codex/gate_lock.json` transparently and cite the before/after behavior in worker/review artifacts.

## Schema and artifact plan

Likely schema updates:

- `schemas/artifact/fault_matrix_report.schema.json`: consider requiring `fault_rows`, `status`, `scale`/`node_count`, row names, coverage IDs, and source refs, while preserving compatibility with older P20/P21/P22-P24 where needed.
- `schemas/artifact/fault_result.schema.json`: add strict fields from `09_FAULT_FAILOVER_MATRIX_SPEC.md`, including `coverage_id`, `scale`, `node_count`, `status`, `real_execution_verified`, `observed_effect_started_at_ms`, `expected_impact`, `observed_impact`, topology refs, and source evidence refs.
- `schemas/artifact/failover_latency_sample.schema.json`: add P33-required fields such as target node/host/AZ IDs, replica candidates, primary unreachable, fault cleared, old primary rejoined missing reason, cleanup ref, and split-brain window semantics.
- `schemas/artifact/partition_report.schema.json`: add explicit majority/minority/isolated groups and traffic policy fields if current permissive schema cannot protect P33 semantics.
- `schemas/artifact/split_brain_report.schema.json`: add detector results, side view comparisons, and scale/node count if not enforced solely by assertions.
- `schemas/artifact/workload_impact_report.schema.json`: likely remains reusable; strict per-row enforcement can live in assertions.

Required P33 artifacts:

- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/phase_summary.json`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/valkey_e2e_evidence.json`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/resource_preflight.json`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/cluster_plan.json`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/run_state.json`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/cleanup_report.json`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/events.jsonl`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/metrics_timeseries.jsonl`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/workload_windows.json`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/quant_summary.json`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/coverage_ledger.json`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/fault_matrix_report.json`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/fault_operation_results.jsonl`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/failover_samples.jsonl`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/failover_latency_curve.json`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/partition_report.json`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/split_brain_report.json`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/fault_workload_impact.json`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/fault_topology_snapshots.jsonl`
- `artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/fault_command_log.jsonl`

Useful extra source artifacts: per-sample fault apply/clear reports, proxy snapshots, side-probe logs, detector raw observations, and setup/cleanup stdout/stderr logs under a deterministic P33 work directory.

## Coverage IDs targeted

- `50.fault.primary_stop_failover`
- `50.fault.replica_stop`
- `50.fault.node_host_stop`
- `50.fault.az_stop`
- `50.fault.network_delay`
- `50.fault.network_loss`
- `50.fault.network_flap`
- `50.fault.network_partition`
- `50.fault.minority_partition`
- `50.fault.majority_partition`
- `50.fault.split_brain_window_detection`
- `50.fault.fault_period_workload_impact`

No `100.fault.*`, `200.fault.*`, lifecycle/full-flow, management, or dry-run coverage IDs should be marked PASS in P33.

## Test and gate plan

Focused tests likely to add or update:

- `tests/failover/test_failover_contract.py` or new strict fault assertion tests for P33 failover sample validation and curve derivation.
- `tests/fault/test_sandbox_fault.py` for P33 fault spec safety and network implementation path behavior.
- `tests/unit/test_goal_loop_assertions.py` for P33 manifest command compatibility, strict assertion CLI flags, and no-bypass constraints.
- `tests/unit/test_strict_coverage_registry.py` or a new coverage transition test for updating only `50.fault.*` rows.
- `tests/integration/test_docker_runtime_contract.py` only if P33 needs new runtime admission/scenario behavior outside `fault_failover_gate.py`.

Focused command sequence before real gate:

```bash
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration tests/fault tests/failover
python3 scripts/safety_scan.py
python3 scripts/assert_strict_stage_contract.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL
python3 scripts/assert_no_bypass.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL
python3 scripts/codex_gate.py precheck --phase P33_FAULT_FAILOVER_MATRIX_50_REAL
```

Real gate and post-run assertions:

```bash
python3 scripts/codex_gate.py run --phase P33_FAULT_FAILOVER_MATRIX_50_REAL
python3 scripts/assert_exact_scale_real_evidence.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL --nodes 50
python3 scripts/assert_fault_matrix_strict.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL --scale 50 --require-all-rows
python3 scripts/assert_failover_latency_curve.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL --scale 50 --min-samples 3
python3 scripts/assert_split_brain_report.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL --scale 50
python3 scripts/assert_quant_completeness.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL --category fault --scale 50
python3 scripts/assert_coverage_registry.py --phase P33_FAULT_FAILOVER_MATRIX_50_REAL --scale 50 --category fault
python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/cleanup_report.json
```

## Safety constraints

- Never downshift P33 below exactly 50 nodes.
- Never default to 1000 nodes or start any real cluster above 200 nodes.
- Do not change physical host networking, host routes, host firewall/PF/nftables/iptables, host interfaces, or OS network services.
- Do not use `sudo` for network, route, firewall, or interface mutation.
- Network faults must be scoped to owned containers/namespaces or the project-owned sandbox proxy.
- All started containers/processes/proxies must have deterministic names/state files, owner labels where applicable, collision checks, and deterministic cleanup.
- Required P33 rows cannot pass with `SKIPPED_WITH_REASON`, `UNSUPPORTED_WITH_REASON`, generated values, replayed logs, or fake-only tests.
- Missing optional values must be encoded as `MISSING` with a non-empty reason; never use `null`, empty strings, `0`, `NaN`, `Infinity`, or omitted fields to hide missing data.

## Blocked conditions

- `resource_preflight.json` has `can_run=false`.
- Docker, Valkey 9.1.x image, required ports, memory, disk, or process/container limits are insufficient for exactly 50 nodes.
- `nodes_requested` or `nodes_observed` is not exactly 50.
- Any observed Valkey version does not start with `9.1.`.
- Any required P33 fault row is missing, skipped, unsupported, fake, replayed, or not `PASS`.
- Primary failover has fewer than three independent real samples.
- Network delay/loss/flap/partition requires host-level network mutation.
- Partition probes cannot compare sides where feasible and no valid reason is recorded.
- `split_brain_window_ms=0` is reported without detector evidence.
- Any required workload window or per-row workload impact comparison is absent.
- Coverage registry rows for `50.fault.*` are not PASS from P33 source artifacts.
- Cleanup report is missing, not `PASS`, or leaves owned resources without failing the stage.

## Risks

- Current `scripts/fault_failover_gate.py` is primary-stop focused; P33 requires a broader orchestration layer for 12 rows and may be large if implemented entirely in one script.
- `SandboxNetworkProxy` supports delay/loss/flap at TCP-proxy level, but integrating it with a Valkey Cluster workload path and partition-side probes may require careful endpoint routing.
- `container_netns_tc` may not be available on Mac Docker Desktop; P33 should use `sandbox_proxy` fallback rather than block if proxy can satisfy the row.
- Stopping a full logical host or AZ on a 50-node two-AZ plan may intentionally remove many nodes; detector logic must distinguish expected unavailability from unsafe split-brain.
- Existing schemas are permissive; relying only on schemas may allow weak artifacts. P33 assertions must enforce semantics.
- Updating global coverage from runtime must preserve P30-P32 management PASS rows and avoid marking P34/P35 future rows.
- Real P33 execution may take longer than the current 7200-second manifest timeout if all rows run sequentially with cleanup and detector windows.

## 待验证

- 待验证: local Docker resources can run exactly 50 Valkey 9.1.0 nodes plus workload, proxy/detector processes, and telemetry without preflight failure.
- 待验证: `scripts/fault_failover_gate.py` can safely reuse one 50-node cluster for all fault rows, or whether independent sub-runs are required for isolation and cleanup reliability.
- 待验证: existing `fault.sandbox` and `SandboxNetworkProxy` can produce observable network delay/loss/flap/partition impact for Valkey Cluster clients without modifying host networking.
- 待验证: logical host and AZ placement in `scale_50.yaml` and generated state are sufficient for node-host stop and AZ stop row semantics.
- 待验证: partition-side probes are feasible from current single-host Docker/runtime topology; otherwise the stage must fail or block rather than claim weak evidence.
- 待验证: split-brain detectors can run all four required detector classes and produce zero-window evidence only when no indicator is observed.
- 待验证: schemas can be tightened without breaking committed P20-P24 artifacts, or assertions must carry strict P33 semantics while keeping legacy compatibility.
- 待验证: locked harness file changes will require a transparent `codex/gate_lock.json` hash refresh.
