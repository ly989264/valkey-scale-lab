# DESIGN_BRIEF — P24_PARTITION_SPLIT_BRAIN_MATRIX

## Objective

Implement real Valkey evidence for the P24 partition and split-brain matrix rows:

- `network_partition_minority`
- `network_partition_majority`
- `split_brain_window_detection`

The stage must emit detector-backed `partition_report.json`, `split_brain_report.json`, `fault_results.jsonl`, `fault_topology_snapshots.jsonl`, `workload_impact_report.json`, common quant artifacts, and a compatible `fault_matrix_report.json`. It must not use host firewall/routing/interface mutation, host `sudo`, fake-only evidence, or P25 cross-stage consolidation.

## Repository findings

- `scripts/fault_safety_gate.py` has full P22 and P23 controllers, but no P24 controller. For P24 it currently falls through to the older generic sandbox smoke path, which cannot satisfy P24 artifacts or rows.
- `src/valkey_scale_lab/runtime/docker_runtime.py` admits P22/P23 process-runtime scenarios through `_p22_fault_matrix_node_count()` and `_p23_fault_matrix_node_count()`, but there is no `_p24_fault_matrix_node_count()`. P24 currently cannot start a dedicated bounded process-runtime scenario such as `p24_partition_matrix_6`.
- P23’s `SandboxNetworkProxy` in `src/valkey_scale_lab/fault/network_proxy.py` safely records delay/loss/flap effects for client traffic to one target endpoint. It does not yet express bidirectional partition groups or cluster-bus/server-to-server isolation.
- The existing process runtime groups logical nodes into owned nodehost containers by virtual AZ and publishes each Valkey port on `127.0.0.1`. This gives a safe basis for side-specific probing from the controller and, if needed, `docker exec` probes from inside owned nodehost containers.
- `scripts/assert_fault_matrix_coverage.py` names P24 required fault types, but only generic checks run for P24. It does not yet verify explicit partition groups, both-side probes, majority/minority semantics, side-view comparison, or split-brain detector linkage.
- `scripts/assert_split_brain_report.py` checks that zero windows require detectors, but it does not yet require the full detector set from `08_FAULT_MATRIX_SPEC.md`, indicator timing fields, side-view comparisons, or explicit missing-detector reasons for detectors not run.
- `scripts/assert_workload_impact.py` has P22/P23-specific semantics but no P24-specific workload assertions.
- `scripts/assert_quant_artifacts.py` has P22/P23-specific semantics but no P24-specific event/metric/topology/report cross-reference checks.
- `schemas/artifact/partition_report.schema.json` and `schemas/artifact/split_brain_report.schema.json` are permissive. They validate basic shape only; P24 stage assertions must supply fail-closed semantic checks unless schemas are strengthened.
- Existing config templates include `p23_6.yaml` and `p23_10.yaml` with sandbox proxy mode, two AZs, and logical-only hosts. P24 needs equivalent dedicated templates so the P24 gate is not coupled to `scale_100.yaml` defaults except through the manifest command interface.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `scripts/fault_safety_gate.py` | modify | Add `P24_PHASE`, P24 row constants, scenario setup, partition planner, apply/clear lifecycle, side probes, split-brain detectors, workload windows, reports, evidence, and cleanup aggregation. |
| `src/valkey_scale_lab/runtime/docker_runtime.py` | modify | Admit bounded P24 process-runtime scenarios, enforce max 100 nodes, and keep P24 out of 200/1000-node exception paths. If container-netns isolation is used, add only stage-scoped owned-container capability/config support. |
| `src/valkey_scale_lab/fault/network_proxy.py` | modify if proxy path is chosen | Extend proxy rule/counters for explicit partition/block semantics, or leave untouched if P24 uses owned container namespace/network controls instead. |
| `src/valkey_scale_lab/fault/sandbox.py` | modify if CLI fault apply/clear participates | Preserve backwards compatibility while recording P24 partition parameters and safety metadata for `network_partition`. |
| `templates/configs/p24_6.yaml` | add | Deterministic small real P24 partition cluster with virtual AZ/host labels and sandbox safety flags. |
| `templates/configs/p24_10.yaml` | add | Mandatory 10-node real P24 row coverage matching P22/P23 bounded gate pattern. |
| `scripts/assert_fault_matrix_coverage.py` | modify | Add P24-specific required row and partition semantics checks. |
| `scripts/assert_split_brain_report.py` | modify | Require detector-backed zero, timing fields or missing reasons, side-view comparisons, and explicit missing-detector reasons. |
| `scripts/assert_workload_impact.py` | modify | Add P24 sample/window/comparison checks for the three required rows. |
| `scripts/assert_quant_artifacts.py` | modify | Add P24 event/metric/fault/topology/report count and cross-reference checks. |
| `schemas/artifact/partition_report.schema.json` | strengthen if needed | Require groups, traffic policy, side probes, recovery, and safety fields at schema level where practical. |
| `schemas/artifact/split_brain_report.schema.json` | strengthen if needed | Require detector details, indicator timing, side view comparison, and missing-detector objects where practical. |
| `tests/unit/test_goal_loop_assertions.py` | modify | Add positive/negative P24 assertion fixtures, including rejecting assumed-zero split-brain windows. |
| `tests/integration/test_docker_runtime_contract.py` | modify | Assert P24 bounded scenario admission and rejection of 200/1000-node scenarios. |
| `tests/fault/test_network_proxy.py` | modify if proxy path changes | Cover partition/block counters and host-network safety metadata. |

## Implementation plan

1. Add a first-class P24 controller in `scripts/fault_safety_gate.py`.
   - Follow the P23 controller shape: run real bounded sub-runs, collect rows, write JSON/JSONL artifacts, cleanup each sub-run, then aggregate status.
   - Use mandatory real node counts `6` and `10`, matching the current P22/P23 assertion pattern. Optional larger P24 rows can remain future work unless resource preflight is added, but no 200-node P24 rows.
   - Add `P24_FAULT_TYPES = ["network_partition_minority", "network_partition_majority", "split_brain_window_detection"]`; if `fault_result.fault_type` must align with existing assertion constants, update assertion constants to these exact stage-required row names rather than the current generic names.

2. Add P24 runtime admission.
   - Add `_p24_fault_matrix_node_count(phase, scenario)` accepting only `p24_partition_matrix_(6|10|30|50|100)`.
   - Include P24 in `_uses_docker_process_runtime()` and `_scenario_node_count_allowed()` with `<=100`.
   - Add `templates/configs/p24_6.yaml` and `p24_10.yaml` with two or three virtual AZs, three logical hosts, deterministic port bases not colliding with P23, `require_sandbox_network: true`, `forbid_host_network_mutation: true`, and `sandbox_mode` set to the selected safe implementation path.

3. Implement safe partition application/clear.
   - Preferred path: use owned container namespace or owned Docker network/proxy controls only. Do not mutate physical host networking.
   - If using `container_netns_tc`, perform a stage preflight that proves the target owned nodehost container has the required capability/tooling before attempting the row. Command logs must clearly show container scope and no host mutation. `待验证`: current Valkey image may not include `tc`; if absent, this path cannot be the only passing path.
   - If using `sandbox_proxy`, extend it so the cluster/control/data traffic being measured actually traverses the proxy. A client-only proxy is insufficient for the partition row because it does not block Valkey gossip or cluster-bus traffic between groups.
   - If using owned Docker network controls, record the implementation as owned sandbox/container control only if the schema/assertions are intentionally updated to allow it. Confirm recovery preserves or reestablishes cluster addresses before treating it as PASS. `待验证`: reconnecting an owned container to the Docker network with the same IP may be required for clean recovery.

4. Build a live topology-based partition planner.
   - Parse live probes and state nodes to map logical ID, node ID, role, slots, AZ, host, nodehost container, and endpoint.
   - For `network_partition_minority`, isolate a side with fewer primaries/votes/nodes when feasible and record `groups.majority`, `groups.minority`, and optional `groups.isolated`.
   - For `network_partition_majority`, make the majority side the measured available side and record the opposite side as minority/isolated.
   - Preserve within-group traffic where feasible and record any deviations as `MISSING` or `SKIPPED_WITH_REASON` with reasons. Do not claim within-group preservation if the implementation blocks all traffic on a side.

5. Probe both sides and compare views.
   - Capture before/during/recovered topology snapshots in `fault_topology_snapshots.jsonl`.
   - Majority-side probes can use normal host-published endpoints when reachable.
   - Minority-side probes should use host-published endpoints if reachable; otherwise use `docker exec` within the owned nodehost container to run local `valkey-cli` probes so the side’s cluster view is still measured.
   - Partition report must include per-side `CLUSTER INFO`, parsed `CLUSTER NODES`, reachable endpoints, slot ownership views, and errors/timeouts.

6. Implement split-brain detectors from `08_FAULT_MATRIX_SPEC.md`.
   - Detectors to run where feasible:
     - `primary_slot_assignment_overlap`
     - `partition_side_cluster_view_divergence`
     - `conflicting_write_probe`
     - `old_primary_accepts_write_after_promotion`
   - `split_brain_window_ms=0` is valid only when at least the first three detectors ran and observed no indicator, or when any omitted detector has an explicit `missing_detectors_with_reason` entry and assertions allow that omission.
   - Use detector start/end timestamps and record `indicator_start_ms`, `indicator_end_ms`, `split_brain_window_ms`, `conflicting_slots`, `conflicting_nodes`, and `conflicting_write_keys`. If no indicator is observed, use empty conflict arrays and `indicator_observed=false`.

7. Reuse and adapt P22/P23 workload helpers.
   - Emit canonical windows for every P24 sample: `baseline`, `pre_event`, `event`, `recovery`, `post_recovery`, `all_run`.
   - During partition, run side-aware workload probes against reachable majority and minority entries where feasible. Record side labels in window metadata.
   - Compare fault window QPS ratio, p99 delta, error-rate delta, recovery duration, and post-recovery QPS ratio.

8. Write artifacts from measured rows only.
   - `fault_results.jsonl` rows must contain real timings, explicit groups/targets, `implementation_path`, safety flags, cleanup status, workload refs, detector refs, and errors/missing fields.
   - `partition_report.json` should aggregate partition group definitions, traffic policy, probes, side comparisons, recovery observations, and safe path evidence.
   - `split_brain_report.json` should aggregate detector runs across P24 samples and never silently convert missing detectors into zero.
   - `fault_matrix_report.json`, `phase_summary.json`, `valkey_e2e_evidence.json`, `cleanup_report.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, and `quant_summary.json` should follow the P23 artifact conventions.

## Harness, schema, and gate plan

- Keep the manifest command shape unchanged unless a stronger current-stage harness fix is necessary.
- Strengthen `assert_fault_matrix_coverage.py` for P24:
  - require exact rows `network_partition_minority`, `network_partition_majority`, and `split_brain_window_detection`;
  - require real Valkey rows at 6 and 10 nodes;
  - reject 200-node rows;
  - require explicit `groups`, `traffic_policy.block_between_groups=true`, `traffic_policy.allow_within_group=true` or a measured deviation reason;
  - require side probes and view comparisons;
  - reject host/global network mutation flags.
- Strengthen `assert_split_brain_report.py`:
  - reject `split_brain_window_ms=0` unless detectors ran and each required detector either has a run result or a reasoned missing entry;
  - require indicator timing fields to be numeric or `MISSING` with reason;
  - require side-view divergence evidence, even when no split-brain indicator is observed.
- Add P24 branch to `assert_workload_impact.py`:
  - require all canonical windows per P24 sample;
  - require comparisons for every P24 sample ID;
  - require event-window attempted workload samples and side labels.
- Add P24 branch to `assert_quant_artifacts.py`:
  - cross-check fault IDs/sample IDs across events, metrics, topology snapshots, workload windows, partition report, split-brain report, and quant counts;
  - validate Valkey 9.1.x evidence and cleanup PASS.
- Strengthen schemas only when it makes the harness more fail-closed; do not loosen schemas to pass incomplete artifacts.

## Test plan

- Unit tests in `tests/unit/test_goal_loop_assertions.py`:
  - valid P24 bundle passes all P24 assertion branches;
  - missing `network_partition_majority` row fails;
  - `split_brain_window_ms=0` with no detectors fails;
  - missing detector reason fails;
  - missing side probes or group definitions fails;
  - host-network mutation flag or forbidden command-log token fails.
- Integration tests in `tests/integration/test_docker_runtime_contract.py`:
  - P24 admits only bounded `p24_partition_matrix_6`, `10`, `30`, `50`, `100`;
  - P24 rejects 200 and 1000-node/default-cap bypasses;
  - P24 uses process runtime if that is the selected implementation path.
- Fault/proxy tests if `network_proxy.py` changes:
  - partition/block rule rejects between-group connections and allows within-group connections in a local socket fixture;
  - proxy stats record accepted, blocked, and host-network-mutated=false.
- Run the standard gate sequence through `python3 scripts/codex_gate.py run --phase P24_PARTITION_SPLIT_BRAIN_MATRIX`, then the stage-specific assertions and review.

## Required artifacts

Under `artifacts/phases/P24_PARTITION_SPLIT_BRAIN_MATRIX/`:

- `phase_summary.json`
- `valkey_e2e_evidence.json`
- `cleanup_report.json`
- `events.jsonl`
- `metrics_timeseries.jsonl`
- `workload_windows.json`
- `quant_summary.json`
- `partition_report.json`
- `split_brain_report.json`
- `fault_results.jsonl`
- `fault_topology_snapshots.jsonl`
- `workload_impact_report.json`
- `fault_matrix_report.json` if the wrapper writes it through `--fault-report`
- Optional but recommended: `network_partition_command_log.jsonl` with safe apply/clear/probe command evidence

## Safety considerations

- Do not use host `iptables`, `nft`, `pfctl`, route changes, host interface mutation, host network services, or `sudo`.
- Any Docker commands must target owned containers/networks identified by deterministic labels and current run IDs.
- If command logs include network-control commands, they must prove scope is owned container namespace, owned Docker resources, or project sandbox proxy. Add `host_network_mutated=false`, `global_firewall_mutated=false`, and `physical_host_mutated=false` to rows/reports.
- Cleanup must clear partition state before owned container/network cleanup. A cleanup failure must make the stage fail.
- Do not encode missing detectors or missing workload samples as zero, `null`, empty string, or omission.

## Resource considerations

- Mandatory P24 real evidence should be bounded to 6 and 10 nodes unless the worker adds explicit resource preflight for larger rows.
- Keep all default configs at or below 100 nodes. Do not run P14 or any 1000-node path.
- The P24 manifest currently passes `templates/configs/scale_100.yaml` to the wrapper, but P22/P23 controllers use their own stage templates internally. P24 can follow that pattern while preserving CLI compatibility.
- Partition tests can temporarily make cluster health degrade. Timeouts should be long enough to record recovery, but failures must remain real failures rather than being converted to PASS.

## `待验证`

- Whether the Valkey image used by process-runtime nodehost containers contains `tc` and whether P24 can add container-scoped `NET_ADMIN` without breaking existing stages.
- Whether an extended sandbox proxy can practically carry cluster-bus/server-to-server traffic, not only client traffic, without reworking Valkey `cluster-announce-*` addresses.
- Whether owned Docker network disconnect/reconnect can preserve nodehost IPs and allow deterministic recovery; if it cannot, do not use it for PASS evidence.
- Whether all four split-brain detectors can run in the selected safe path. Missing detectors must be explicit with reasons, and assertions must decide which omissions are acceptable.
- Whether probing minority side via host-published ports remains feasible under the selected isolation path; otherwise implement owned-container `docker exec` probes.

## Worker instructions

- Implement only P24.
- Do not commit.
- Do not weaken harness or safety rules.
- Prefer adapting the existing P22/P23 gate/controller/report patterns to keep artifact shape consistent.
- Treat fake/static partition reports as failures. The evidence must come from live Valkey 9.1.x probes and measured workload/detector runs.
