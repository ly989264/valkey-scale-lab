# DESIGN_BRIEF — P23_FAULT_NETWORK_DELAY_LOSS_FLAP

## Objective

Implement real, sandboxed `network_delay`, `network_loss`, and `network_flap` fault rows for live Valkey, with apply/clear lifecycle evidence, workload impact windows, event/metric artifacts, cleanup proof, and command logs that prove no host firewall, routing, interface, or sudo network mutation occurred.

P23 must stay narrow: do not implement P24 partition, minority/majority partition, or split-brain-window behavior as this stage's deliverable.

## Repository findings

- `scripts/fault_safety_gate.py` has a strong P22 controller and reusable helpers for setup, cleanup, probing, workload windows, comparisons, events, metrics, and P22-style aggregate artifacts. It currently special-cases only `P22_FAULT_REPLICA_HOST_AZ_STOP`; P23 falls through to the older P07 smoke path, which only applies one `network_delay` lifecycle record and does not emit P23's required `network_fault_report.json`, `network_fault_command_log.jsonl`, three rows, or workload impact.
- `src/valkey_scale_lab/fault/sandbox.py` accepts `network_delay`, `network_loss`, and `network_flap`, but non-`node_stop` faults currently record a non-destructive lifecycle only. That is insufficient for P23 because the row must exercise at least one safe implementation path and observe real workload impact.
- `src/valkey_scale_lab/runtime/docker_runtime.py` admits P22 scale scenarios through `_p22_fault_matrix_node_count`; there is no P23 scenario matcher yet. A P23 controller that creates `p23_fault_matrix_<N>` scenarios will need runtime admission and node-count caps.
- Existing schemas are intentionally loose: `network_fault_report.schema.json`, `command_log_entry.schema.json`, `fault_result.schema.json`, `workload_impact_report.schema.json`, and `quant_summary.schema.json` validate shape but not P23 semantics. Semantic fail-closed checks should be added to assertion scripts rather than relying on schemas alone.
- `scripts/assert_fault_matrix_coverage.py` already knows P23 requires `network_delay`, `network_loss`, and `network_flap`, but it only checks generic safe paths today. It needs P23-specific validation of parameters, observed effect, safe implementation path, command log, and no host mutation.
- `scripts/assert_workload_impact.py` has detailed P20/P21/P22 stage checks but no P23-specific checks. It should require canonical windows and comparisons per P23 fault sample.
- `scripts/assert_quant_artifacts.py` has P16/P20/P21/P22 semantic checks but no P23-specific checks. It should connect P23 events/metrics/fault rows/network report/command log and real Valkey evidence.
- `templates/configs/local_az_3x2.yaml` already contains a config-level `network_delay` example. P22 has dedicated `p22_6.yaml`, `p22_10.yaml`, and `p22_30.yaml` templates for bounded real gates; P23 should follow that pattern instead of accidentally defaulting the gate to 100 nodes.
- `tests/integration/test_docker_runtime_contract.py` already checks that P22 is capped and does not admit 200-node scenarios. P23 needs equivalent coverage.
- The portable real implementation path should be `sandbox_proxy` first. `container_netns_tc` may be detected and used only if the owned container namespace actually has the required tooling and permissions. `待验证`: whether `valkey/valkey:9.1.0` contains `tc` and whether the current Docker run settings allow `NET_ADMIN`.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `scripts/fault_safety_gate.py` | Extend | Add a P23 controller modeled after P22: bounded node counts, real setup/probes, delay/loss/flap execution, workload windows, events, metrics, aggregate artifacts, and cleanup. |
| `src/valkey_scale_lab/fault/sandbox.py` | Extend | Implement real apply/clear lifecycle for `sandbox_proxy` network faults and optional `container_netns_tc` detection/application if safely available. |
| `src/valkey_scale_lab/fault/network_proxy.py` | Add | Project-owned TCP proxy process for delay, deterministic packet/connection loss, and flap cadence without host network mutation. |
| `src/valkey_scale_lab/runtime/docker_runtime.py` | Extend | Admit capped `p23_fault_matrix_(6|10|30|50|100)` scenarios and reject 200/1000; decide whether P23 uses process runtime for larger optional counts. |
| `templates/configs/p23_6.yaml` | Add | Bounded P23 real-gate template with safe sandbox settings and low workload. |
| `templates/configs/p23_10.yaml` | Add | Mandatory second bounded P23 template if worker follows P22's 6/10 proof pattern. |
| `templates/configs/p23_30.yaml` | Add if optional 30+ evidence is attempted | Resource-preflighted optional larger P23 run; may be skipped with reason if preflight fails. |
| `scripts/assert_fault_matrix_coverage.py` | Strengthen | Add `validate_p23`: exact row coverage, safe path, parameters, observed effect, command log safety, cleanup, no P24 partition rows. |
| `scripts/assert_workload_impact.py` | Strengthen | Add P23 canonical window and comparison checks per non-skipped sample. |
| `scripts/assert_quant_artifacts.py` | Strengthen | Add P23 event/metric/fault/report/command-log cross-reference checks and real Valkey claim checks. |
| `schemas/artifact/network_fault_report.schema.json` | Possibly strengthen | Require P23-relevant row fields only if this can be done without breaking future P24; assertions may be enough. |
| `schemas/artifact/command_log_entry.schema.json` | Possibly strengthen | Consider requiring command safety metadata for P23 command logs; assertions may be enough. |
| `tests/fault/test_sandbox_fault.py` | Extend | Unit tests for network fault apply/clear, safety guard, proxy lifecycle, and unsupported unsafe implementation paths. |
| `tests/fault/test_network_proxy.py` | Add | Focused unit tests for delay/loss/flap proxy behavior using local sockets or deterministic fake sockets. |
| `tests/integration/test_docker_runtime_contract.py` | Extend | P23 scenario admission, cap, and no-200-node tests. |
| `tests/unit/test_goal_loop_assertions.py` | Extend | Positive and negative fixtures for P23 fault, workload, and quant assertions. |
| `tests/config/test_config_validation.py` | Possibly extend | Validate any new P23 config templates and fault parameter validation. |
| `codex/gate_lock.json` | Update if required by harness | Only after protected harness/script/schema changes, preserving lock integrity. |

## Implementation plan

1. Add a P23-specific controller in `scripts/fault_safety_gate.py`.
   - Define `P23_PHASE = "P23_FAULT_NETWORK_DELAY_LOSS_FLAP"`, `P23_FAULT_TYPES = ["network_delay", "network_loss", "network_flap"]`, and canonical windows.
   - Run mandatory bounded real scenarios at 6 and 10 nodes unless the worker proves the stage document requires a different exact count. Optional 30+ evidence may be resource-preflighted, but a skipped optional larger run must be encoded as `SKIPPED_WITH_REASON`; mandatory rows must not be skipped.
   - Use `p23_fault_matrix_<node_count>` scenario names and P23 templates so the runtime does not accidentally start 100 nodes by default.

2. Implement safe path detection.
   - Probe `container_netns_tc` only inside owned containers/nodehost containers, with command logs proving the target container is owned by current phase/run labels. Do not use sudo, host `iptables`, host `nft`, host `pfctl`, host routes, or host interfaces.
   - Prefer `sandbox_proxy` as the portable path. A Python proxy can delay forwarding, deterministically close/drop a percentage of connections/commands, and flap between accepting and rejecting traffic.
   - Record unsupported detection results as `UNSUPPORTED_WITH_REASON` metadata, but at least one real safe path must be exercised for each required row.

3. Implement apply/clear lifecycle through `python3 -m valkey_scale_lab.cli fault apply` and `fault clear`.
   - For `sandbox_proxy`, `apply_fault` should start or activate a project-owned proxy with deterministic listen port, PID/state file, target endpoint, fault rule, and ownership metadata. `clear_fault` must terminate/deactivate it and verify no proxy process/state remains.
   - For `container_netns_tc`, if implemented, `apply_fault` should apply `tc netem` only inside the owned container namespace and `clear_fault` should delete only the owned qdisc state it created. Command logs must include namespace/container identity.
   - Every fault state file should include implementation path, target logical IDs, target endpoint, parameters, started/cleared timestamps, cleanup state, and safety checks.

4. Ensure real workload impact is not bypassed.
   - For the proxy path, either proxy all workload endpoints or choose keys that map to slots owned by the proxied target so MOVED redirects do not bypass the proxy.
   - Reuse or mirror the `key_slot` / `key_for_slot_range` helper pattern from `scripts/fault_failover_gate.py`.
   - Record target slot/key provenance in `fault_parameters` or `observed_impact`.

5. Produce one row per required fault type per mandatory node count.
   - `network_delay`: include `delay_ms`, `jitter_ms`, `affected_direction`, `target_set`, and `duration_seconds`; observed impact should show latency increase or measured proxy delay counts.
   - `network_loss`: include `loss_percent`, `correlation` if used, `affected_direction`, `target_set`, and `duration_seconds`; observed impact should show dropped/closed attempts, errors, timeouts, or loss counters.
   - `network_flap`: include `up_ms`, `down_ms`, `iterations`, `target_set`, and observed transition counts.

6. Emit P23 artifacts derived from real runs.
   - Required common artifacts plus `network_fault_report.json`, `fault_results.jsonl`, `workload_impact_report.json`, and `network_fault_command_log.jsonl`.
   - Also write `fault_matrix_report.json` to the `--fault-report` path for compatibility with the manifest gate and P22/P24 patterns.

7. Keep failure semantics honest.
   - A row can be `PASS` only when real Valkey was probed, the impairment path was exercised, workload impact exists, cleanup passed, and safety checks are true.
   - Unsupported `tc` must not make the stage pass unless `sandbox_proxy` rows pass. Missing values must be `MISSING`, `SKIPPED_WITH_REASON`, or `UNSUPPORTED_WITH_REASON` with reasons.

## Harness, schema, and gate plan

- Keep the existing manifest gate commands unless a real command mismatch is discovered. The current P23 gate already calls `scripts/fault_safety_gate.py` and then the quant, fault matrix, workload impact, and cleanup assertions.
- Strengthen `scripts/assert_fault_matrix_coverage.py` with P23-specific checks:
  - required real fault types are exactly `network_delay`, `network_loss`, and `network_flap` for mandatory counts;
  - no `network_partition`, `minority_partition`, `majority_partition`, or split-brain-only rows appear in P23;
  - real rows use `container_netns_tc` or `sandbox_proxy`, not `owned_runtime_control`;
  - unsupported rows are allowed only for non-selected implementation-path detection and require reasons;
  - every row has parameters, target set, observed effect, `real_valkey=true`, `host_network_mutated=false`, `safety_scope_verified=true`, and `cleanup_verified=true`;
  - `network_fault_command_log.jsonl` has apply/clear entries per fault ID and no forbidden host mutation tokens.
- Strengthen `scripts/assert_workload_impact.py` for P23:
  - all canonical windows exist for every non-skipped P23 sample;
  - comparisons include `fault_window_qps_ratio`, `fault_window_p99_delta_ms`, `fault_window_error_rate_delta`, `recovery_window_duration_ms`, and `post_recovery_qps_ratio`;
  - fault-window impact is backed by actual window metrics rather than constants.
- Strengthen `scripts/assert_quant_artifacts.py` for P23:
  - event/metric counts match `quant_summary.json`;
  - all real fault IDs appear in events and harness metrics;
  - `network_fault_report.json` and `fault_results.jsonl` reference the same real samples;
  - `valkey_e2e_evidence.json` is PASS, real Valkey, Valkey `9.1.x`, and observes at least the mandatory node count;
  - cleanup status is PASS and `resources_remaining` is empty.
- Schema changes should be minimal. If the worker keeps schemas broad and enforces semantics in assertions, that is acceptable. If schemas are strengthened, update tests and `codex/gate_lock.json` transparently without weakening protected harness behavior.

## Test plan

- Unit tests:
  - `fault/sandbox.py` rejects network faults without `forbid_host_network_mutation=true`.
  - `sandbox_proxy` apply writes state, starts/records a proxy PID or deterministic process handle, and clear removes/deactivates it.
  - delay/loss/flap proxy rules produce deterministic counters and safe cleanup in unit-level proxy tests.
  - command logs reject forbidden host mutation tokens.
  - P23 assertion fixtures pass for valid delay/loss/flap rows and fail for missing parameters, unsafe implementation paths, skipped mandatory rows, missing workload windows, missing command-log entries, and accidental P24 partition rows.
  - P23 runtime matcher admits only capped `p23_fault_matrix_(6|10|30|50|100)` scenarios and rejects 200.
- Integration/gate tests:
  - `python3 -m pytest -q tests/unit tests/integration`
  - focused tests for `tests/fault` and goal-loop assertion fixtures.
- Stage gates:
  - `python3 scripts/codex_gate.py precheck --phase P23_FAULT_NETWORK_DELAY_LOSS_FLAP`
  - `python3 scripts/safety_scan.py`
  - `python3 -m compileall -q scripts src`
  - `python3 -m pytest -q tests/unit tests/integration`
  - `python3 scripts/assert_goal_loop_stage.py --phase P23_FAULT_NETWORK_DELAY_LOSS_FLAP`
  - `python3 scripts/codex_gate.py run --phase P23_FAULT_NETWORK_DELAY_LOSS_FLAP`
  - `python3 scripts/assert_quant_artifacts.py --phase P23_FAULT_NETWORK_DELAY_LOSS_FLAP`
  - `python3 scripts/assert_fault_matrix_coverage.py --phase P23_FAULT_NETWORK_DELAY_LOSS_FLAP`
  - `python3 scripts/assert_workload_impact.py --phase P23_FAULT_NETWORK_DELAY_LOSS_FLAP`
  - `python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/cleanup_report.json`

## Required artifacts

- `artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/phase_summary.json`
- `artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/valkey_e2e_evidence.json`
- `artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/cleanup_report.json`
- `artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/events.jsonl`
- `artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/metrics_timeseries.jsonl`
- `artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/workload_windows.json`
- `artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/quant_summary.json`
- `artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/network_fault_report.json`
- `artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/fault_results.jsonl`
- `artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/workload_impact_report.json`
- `artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/network_fault_command_log.jsonl`
- `artifacts/phases/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/fault_matrix_report.json` for manifest `--fault-report` compatibility.
- Optional resource preflight artifacts if any 30+ P23 run is attempted.

## Safety considerations

- No host firewall, host routing, PF, nftables, iptables, host interface, OS network service, or sudo network changes.
- `sandbox_proxy` must bind deterministic local ports, write PID/state files, and be cleaned through owned state only.
- `container_netns_tc`, if implemented, must run only via `docker exec` in an owned container for the current phase/run and must log the owned container identity. It must never use host namespace commands.
- Command logs must be reviewed by assertions for forbidden tokens and must include `host_network_mutated=false`.
- The worker must not mark fake lifecycle records as PASS. A PASS row needs real Valkey probes and measured workload impact.
- Cleanup must remove proxy processes/state and clear any container namespace qdisc state that was applied. Leftover owned resources must fail the stage.

## Resource considerations

- Normal defaults remain capped at 100 nodes; P23 must not use the P21 200-node exception and must never run 1000 nodes.
- Use low but non-zero workload rates for P23 because the signal needed is relative latency/error impact, not throughput saturation.
- Mandatory real evidence should be bounded enough for local Docker. Optional 30+ evidence should run only after resource preflight and must be skipped with reason if unavailable.
- Proxy ports must be deterministic, collision-checked, and included in cleanup state.

## `待验证`

- Whether `valkey/valkey:9.1.0` contains `tc`/netem tooling and whether owned containers can use it without adding unsafe host capabilities.
- Whether adding `--cap-add NET_ADMIN` to P23-owned containers is necessary or desirable if `container_netns_tc` is selected; the proxy path should avoid requiring this.
- Whether P23 should require real rows at both 6 and 10 nodes, or one 6-node real row set is sufficient under the stage doc. P22 used 6/10 mandatory rows; matching that pattern is safer.
- Whether the worker should strengthen JSON schemas or keep schemas broad and enforce all P23 semantics through assertions.
- Whether proxying one target-owned slot is sufficient for review, or whether proxying all workload endpoints is simpler evidence. The chosen path must prevent MOVED redirects from bypassing impairment.

## Worker instructions

- Implement only this stage.
- Do not commit.
- Do not weaken harness or safety rules.
- Prefer the portable `sandbox_proxy` real path unless `container_netns_tc` is proven available inside owned containers.
- Do not implement P24 partition/minority/majority/split-brain behavior.
- Do not pass P23 with lifecycle-only or fake network-fault evidence.
