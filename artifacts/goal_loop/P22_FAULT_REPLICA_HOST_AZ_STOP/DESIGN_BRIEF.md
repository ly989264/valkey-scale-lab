# DESIGN_BRIEF - P22_FAULT_REPLICA_HOST_AZ_STOP

## Objective

Implement real P22 fault-matrix evidence for `replica_stop`, `node_host_stop`, and `az_stop` using only project-owned Valkey processes/containers. The stage must emit schema-validated fault, topology, workload, event, metric, quantification, evidence, and cleanup artifacts for real 6/10-node runs plus at least one 30+ node row when resource preflight passes. Logical host and virtual AZ faults must be topology abstractions only; no physical host, interface, route, firewall, or real AZ operation is allowed.

## Repository findings

- `codex/phase_manifest.json` already defines P22 as automatic, real-Valkey, `max_nodes=100`, and requires `fault_matrix_report.json`, `fault_results.jsonl`, `fault_topology_snapshots.jsonl`, `workload_impact_report.json`, common quant artifacts, and cleanup.
- The P22 real gate currently calls `scripts/fault_safety_gate.py --phase P22_FAULT_REPLICA_HOST_AZ_STOP --config templates/configs/scale_100.yaml --min-nodes 6`. That script is still a single `network_delay` sandbox smoke gate and does not implement P22 rows, grouped stops, workload impact, topology snapshots, canonical quant artifacts, or P22 cleanup aggregation.
- `src/valkey_scale_lab/fault/sandbox.py` already supports `node_stop` through `python3 -m valkey_scale_lab.cli fault apply`, stopping either a single owned container or a single Valkey PID inside an owned nodehost container, and `fault clear` restarts it. This is the correct primitive for `replica_stop` and grouped logical host/AZ stop.
- `src/valkey_scale_lab/runtime/docker_runtime.py` process-runtime state includes `logical_id`, `role`, `host_id`, `az_id`, `nodehost_id`, `pid`, `config_file`, and `nodehost_container_name`; these fields are enough to select P22 targets from topology.
- `_uses_docker_process_runtime()` currently recognizes P20/P21 scale sample scenarios but not P22. `_scenario_node_count_allowed()` also lacks P22 scenario allowances, so P22 cannot safely reuse the optimized process runtime for 30+ rows without runtime changes.
- Existing configs provide `scale_10.yaml`, `scale_30.yaml`, and `scale_100.yaml`; `single_mac_6node.yaml` is single-AZ and is a poor fit for `az_stop`. P22 should add a small multi-AZ 6-node config rather than weakening existing configs.
- Current `scale_*` configs have one physical/logical `host_id: local`. For a meaningful logical node-host stop, P22 should use P22-specific configs with multiple logical host IDs that all map to local Docker. These are project topology labels, not physical hosts.
- `scripts/assert_fault_matrix_coverage.py` already names the three P22 fault rows and checks generic safe implementation paths, safety scope, cleanup, targets, and workload references. It does not yet prove replica role selection, no-successful-promotion semantics, host/AZ target grouping, required node counts, 30+ preflight behavior, or absence of physical host mutation.
- `scripts/assert_workload_impact.py` validates global canonical windows, but P22 needs per-fault-row windows and comparisons.
- `scripts/assert_quant_artifacts.py` has P16/P20/P21 semantic checks, but no P22-specific count/sample/fault-runtime checks.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `scripts/fault_safety_gate.py` | Extend | Add a P22 controller that runs replica, logical host, and virtual AZ stop rows; writes P22 artifacts; runs cleanup in all paths. |
| `src/valkey_scale_lab/runtime/docker_runtime.py` | Extend | Admit P22 setup scenarios at exact 6/10 and selected 30/50/100 node counts and route them through docker-process runtime where useful. |
| `templates/configs/p22_6.yaml` | Add | Provide multi-AZ, multi-logical-host 6-node topology for required P22 evidence. |
| `templates/configs/p22_10.yaml` | Add or derive | Provide 10-node topology with multiple logical hosts for required P22 evidence. |
| `templates/configs/p22_30.yaml` or controller use of `scale_30.yaml` | Add/modify likely | Provide a resource-gated 30+ P22 topology with logical hosts; prefer a P22-specific config if host grouping must differ from existing scale configs. |
| `scripts/assert_fault_matrix_coverage.py` | Strengthen | Enforce P22 row semantics, node counts, role/group targeting, safe implementation paths, cleanup, and skipped-with-reason rules. |
| `scripts/assert_workload_impact.py` | Strengthen | Require canonical workload windows and comparisons for every P22 fault row/sample. |
| `scripts/assert_quant_artifacts.py` | Strengthen | Require P22 events/metrics to cover every fault row/sample and quant counts to match JSONL files. |
| `schemas/artifact/fault_result.schema.json` | Possibly strengthen | Add optional P22 fields only if assertion-level checks are not enough. |
| `schemas/artifact/fault_matrix_report.schema.json` | Possibly strengthen | Keep permissive unless schema validation needs P22-specific row structure. |
| `tests/unit/test_goal_loop_assertions.py` | Add tests | Cover P22 fault/workload/quant assertions and rejection cases. |
| `tests/integration/test_docker_runtime_contract.py` | Add tests | Cover P22 scenario admission, exact node counts, process-runtime routing, and continued rejection of 200-node P22. |
| `tests/fault/test_sandbox_fault.py` | Possibly add tests | Cover any grouped stop helper if implemented in the fault package rather than only in the gate script. |
| `artifacts/harness_exception/P22_FAULT_REPLICA_HOST_AZ_STOP.md` | Add if controlled scripts/templates change | Required because P22 likely strengthens locked harness files. |
| `codex/gate_lock.json` | Update if controlled files change | Refresh only after documenting the strengthening; do not bypass lock checks. |

## Implementation plan

1. Add P22-specific configs for 6 and 10 nodes with `virtual_az_mode: multi`, two AZs, multiple logical host IDs that all use local Docker, `allow_1000_nodes: false`, `default_max_nodes: 100`, and deterministic non-overlapping ports. Add a 30+ config or reuse a safe existing one after confirming logical host grouping.
2. Add P22 runtime admission for scenarios such as `p22_fault_matrix_6`, `p22_fault_matrix_10`, and `p22_fault_matrix_30`/`50`/`100`. Keep P22 capped at 100 and explicitly reject P22 200-node scenarios.
3. In `fault_safety_gate.py`, branch on `phase == P22_FAULT_REPLICA_HOST_AZ_STOP` and run a P22 controller instead of the old network-delay smoke path.
4. The controller should run mandatory real 6-node and 10-node subruns. For 30+, run resource preflight for candidate configs from largest safe up to 100 down to 30, select the largest passing candidate, and record `SKIPPED_WITH_REASON` if no 30+ preflight passes.
5. For each selected node count, create a fresh scenario through `python3 -m valkey_scale_lab.cli gate scenario`, independently probe Valkey endpoints for version `9.1.x`, cluster state, topology, and data path before faults.
6. Select targets from the state/live topology:
   - `replica_stop`: one node verified as replica before stop.
   - `node_host_stop`: all nodes with one selected logical `host_id`; record that this is a topology label and all physical execution remains local/owned.
   - `az_stop`: all nodes with one selected `az_id`; record minority/majority implications from the planned node distribution.
7. Apply stops only through `valkey_scale_lab.cli fault apply` with `type: node_stop`, one logical node at a time. For grouped host/AZ faults, stop every target logical node by PID/container identity from the owned state; do not stop a physical host or modify networking.
8. Measure baseline, pre_event, event, recovery, post_recovery, and all_run workload windows for every row. Reads/writes may use an unaffected primary when the target set removes the chosen slot owner, but the row must record target-set role/slot impact and any failures observed.
9. Clear every applied fault through `valkey_scale_lab.cli fault clear`, wait for restored endpoints and cluster health when expected, and run deterministic scenario cleanup in `finally` logic.
10. Emit `fault_results.jsonl` with one row per fault/node-count sample. Include target selector, selected targets with `logical_id`, `role`, `host_id`, `az_id`, `nodehost_id`, slot/primary impact, timing fields, expected/observed impact, split-brain detector fields for AZ stop, safety scope, cleanup status, and workload references.
11. Emit `fault_topology_snapshots.jsonl` with before/during/after/recovered snapshots for every row, including nodes, roles, target membership, slot summary, cluster state, and probe status.
12. Emit top-level P22 `fault_matrix_report.json`, `workload_impact_report.json`, `workload_windows.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `quant_summary.json`, `phase_summary.json`, `valkey_e2e_evidence.json`, and aggregate `cleanup_report.json`.

## Harness, schema, and gate plan

- Keep the P22 manifest `max_nodes` at 100. Do not reuse the P21 200-node exception.
- Prefer making the existing manifest gate command stage-aware inside `fault_safety_gate.py`; update the manifest only if the gate needs explicit P22 config flags. If the manifest changes, document it as a harness strengthening.
- Strengthen `assert_fault_matrix_coverage.py` for P22:
  - require `replica_stop`, `node_host_stop`, and `az_stop` rows at 6 and 10 nodes;
  - require at least one 30+ row when a P22 30+ preflight artifact has `can_run=true`;
  - require skipped 30+ rows to be `SKIPPED_WITH_REASON` with preflight reason when preflight fails;
  - require `replica_stop` target role to be replica and reject rows that count promotion as success unless `unexpected_promotion_observed` is recorded as impact;
  - require `node_host_stop` targets to all share the selected logical `host_id` and no non-target host IDs;
  - require `az_stop` targets to all share the selected `az_id` and no non-target AZ IDs;
  - require `physical_host_mutated=false`, `host_network_mutated=false`, and implementation path `owned_runtime_control` or `owned_container_control`.
- Strengthen `assert_workload_impact.py` so every P22 fault sample has all six canonical windows and comparison refs.
- Strengthen `assert_quant_artifacts.py` so P22 event/metric JSONL rows cover every `fault_id`, phase IDs match, missing metric values include reasons, and `quant_summary.counts` matches file counts.
- Existing schemas are permissive enough; add schema requirements only where assertions cannot express fail-closed behavior cleanly.
- Run `scripts/assert_cleanup.py` against the aggregate cleanup report and make aggregate cleanup fail if any subrun leaves owned resources or fault-state files.

## Test plan

- `python3 -m compileall -q scripts src`
- `python3 -m pytest -q tests/unit tests/integration`
- Focused tests:
  - P22 runtime allows exact `p22_fault_matrix_6`, `p22_fault_matrix_10`, and selected 30+ scenarios and rejects 200 nodes.
  - P22 fault assertion accepts a valid synthetic bundle and rejects missing rows, wrong replica role, host/AZ target leakage, unsafe implementation path, missing cleanup, and fake 30+ skips.
  - P22 workload assertion rejects a row missing any canonical window or comparison.
  - P22 quant assertion rejects mismatched event/metric counts and missing `fault_id` coverage.
  - Fault API tests continue to prove `node_stop` targets only owned PID/container state.
- Stage gates:
  - `python3 scripts/codex_gate.py precheck --phase P22_FAULT_REPLICA_HOST_AZ_STOP`
  - `python3 scripts/safety_scan.py`
  - `python3 scripts/assert_goal_loop_stage.py --phase P22_FAULT_REPLICA_HOST_AZ_STOP`
  - `python3 scripts/codex_gate.py run --phase P22_FAULT_REPLICA_HOST_AZ_STOP`
  - `python3 scripts/assert_quant_artifacts.py --phase P22_FAULT_REPLICA_HOST_AZ_STOP`
  - `python3 scripts/assert_fault_matrix_coverage.py --phase P22_FAULT_REPLICA_HOST_AZ_STOP`
  - `python3 scripts/assert_workload_impact.py --phase P22_FAULT_REPLICA_HOST_AZ_STOP`
  - `python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/cleanup_report.json`

## Required artifacts

- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/phase_summary.json`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/valkey_e2e_evidence.json`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/cleanup_report.json`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/events.jsonl`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/metrics_timeseries.jsonl`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/workload_windows.json`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/quant_summary.json`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/fault_matrix_report.json`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/fault_results.jsonl`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/fault_topology_snapshots.jsonl`
- `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/workload_impact_report.json`
- Recommended generated diagnostics: P22 resource preflight artifacts for 30+/50/100 candidates, per-subrun state, setup logs, fault apply/clear logs, probe logs, workload raw samples, and child cleanup reports.

## Safety considerations

- Do not stop, restart, or mutate a physical host. `node_host_stop` is a logical topology-group stop over owned Valkey nodes only.
- Do not stop a physical AZ. `az_stop` is a virtual placement-group stop over owned Valkey nodes only.
- Do not use `sudo`, host route changes, host firewall changes, PF, nftables, iptables, interface changes, global network services, or unrelated host process operations.
- Grouped faults must stop only logical nodes present in the state file and must use owned PID/container identity from that state.
- Every apply must have paired clear/cleanup logic. Any uncleared fault state, live owned container, live owned Valkey process after cleanup, or residual network must fail the stage.
- Do not widen defaults beyond 100 nodes. P22 must not use P21's 200-node exception or P14's 1000-node dry-run path.

## Resource considerations

- Run subruns sequentially so peak resource use is one cluster at a time.
- Mandatory 6/10 rows should be small. The 30+ row should run only after preflight passes and should prefer the largest safe existing scale up to 100.
- Lower workload QPS is acceptable only as a recorded, non-zero, resource-aware setting; it cannot replace workload windows or data-path proof.
- If 30+ preflight fails, encode `SKIPPED_WITH_REASON` with the exact preflight artifact/reason. Do not invent a 30+ PASS row.
- If mandatory 6/10 real evidence cannot run because Docker or Valkey setup fails, the stage is blocked/failing and must not be marked complete.

## `待验证`

- Whether P22 should target 30, 50, or 100 as the 30+ evidence row on the current host; resource preflight must decide.
- Whether P22-specific multi-logical-host configs are preferable to reusing existing `scale_10.yaml`/`scale_30.yaml`; current existing configs use only `host_id: local`.
- Whether grouped `az_stop` of half the nodes in a two-AZ, one-replica topology reliably recovers after restart without manual cluster repair; failures must be real `FAIL` or quantified impact, not hidden.
- Whether existing `node_stop` clear logic restarts multiple grouped process faults reliably when clearing in sequence.
- Whether split-brain indicator measurement for `az_stop` can safely report `0` after running overlap detectors, or must use `MISSING` with reason for some subruns.
- Whether the current P22 manifest timeout is enough for 6/10 plus 30+ grouped fault rows.

## Worker instructions

- Implement only P22.
- Do not commit.
- Do not weaken harness or safety rules.
- Do not implement P23 network delay/loss/flap or P24 partition behavior beyond recording P22-safe split-brain indicators for AZ stop.
- Do not use physical host/AZ controls, host networking mutation, or any default scale above 100 nodes.
