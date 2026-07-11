# DESIGN_BRIEF — P20_FAILOVER_LATENCY_CURVE_30_50_100

## Objective

Produce real primary-stop failover latency curve evidence for exactly the 30, 50, and 100 node rungs, with at least three independent real Valkey samples per rung. The stage must block on failed resource preflight or real-gate failure; it must not pass by fake sample reuse, generated static values, or downshifting the 100-node rung.

## Repository findings

- `codex/phase_manifest.json` already defines P20 as automatic, real-Valkey, `max_nodes=100`, and requires `failover_latency_samples.jsonl`, `failover_latency_curve.json`, `fault_matrix_report.json`, and `workload_impact_report.json`.
- The current P20 manifest real gate calls `scripts/fault_failover_gate.py` once with `--config templates/configs/scale_100.yaml`, `--scenario failover_curve_30_50_100`, and `--min-nodes 30`. As written, this does not force 30/50/100 rung execution or three samples per rung.
- `scripts/fault_failover_gate.py` currently performs one setup, one primary-stop fault, one promotion wait, one clear, and one cleanup. It writes `failover_report.json` and optional fault/workload reports, but it does not write P20 `failover_latency_samples.jsonl`, `failover_latency_curve.json`, canonical `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, or `quant_summary.json`.
- `src/valkey_scale_lab/runtime/docker_runtime.py` does not allow P20 scenarios in `create_scenario`, `_scenario_node_count_allowed`, or `_uses_docker_process_runtime`. P12/P13 already have a process-based scale runtime for 30/50/100 nodes that is safer and lighter than one-container-per-node.
- `src/valkey_scale_lab/fault/sandbox.py` supports `node_stop` on both whole owned containers and Valkey processes inside owned nodehost containers. This is the correct safety boundary for P20 primary-stop samples.
- `templates/configs/scale_30.yaml`, `scale_50.yaml`, and `scale_100.yaml` exist and produce 30, 50, and 100 nodes respectively, all with `allow_1000_nodes: false` and `forbid_host_network_mutation: true`.
- `src/valkey_scale_lab/resource.py` has a `resource preflight` CLI, but it maps 30 to P12 and 50/100 to P13. P20 needs rung preflight artifacts tied to P20, or the failover gate must normalize/report them under the P20 phase.
- `scripts/assert_failover_latency_curve.py` checks expected rungs and sample count, but it should be strengthened for P20 to require unique sample IDs/run IDs, real status/provenance, target primary fields, replica candidate/fault method/detection method fields, cleanup evidence per sample, and curve statistics derived from raw samples.
- `scripts/assert_workload_impact.py` expects canonical rows named `baseline`, `pre_event`, `event`, `recovery`, `post_recovery`, and `all_run`. The current failover gate writes a differently shaped `workload_window_report` if `--workload-window-report` is passed, so P20 must emit the canonical `workload_impact_report.json`.
- The current schemas for `failover_latency_sample`, `failover_latency_curve`, `fault_matrix_report`, and `workload_impact_report` are permissive. P20 can either strengthen schemas or add assertion-level semantic checks; assertion-level changes are lower blast radius for this stage.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `scripts/fault_failover_gate.py` | Strengthen/extend | Add P20 multi-rung/multi-sample orchestration, rung preflight, raw sample JSONL, curve derivation, canonical quant/workload/fault artifacts, and aggregate cleanup. |
| `scripts/assert_failover_latency_curve.py` | Strengthen | Fail closed on fake/reused samples, missing provenance, missing cleanup refs, missing detection/fault method fields, non-P20 rungs, downshifted 100-node samples, and derived statistics not matching raw samples. |
| `scripts/assert_workload_impact.py` | Possibly strengthen | Ensure P20 workload impact rows reference failover sample IDs/rungs and include canonical metrics for all windows. |
| `scripts/assert_quant_artifacts.py` | Possibly strengthen | Add P20-specific checks that events/metrics cover all nine samples and that quant summary counts match JSONL line counts. |
| `src/valkey_scale_lab/runtime/docker_runtime.py` | Extend | Permit P20 setup scenarios for 30/50/100 and route them through the existing docker-process scale runtime; preserve P12/P13 behavior. |
| `src/valkey_scale_lab/resource.py` | Extend or wrap | Emit P20 phase/resource-preflight artifacts for 30, 50, and 100 nodes, or allow the failover gate to call the existing checks and rewrite `phase_id`/`run_id` transparently. |
| `src/valkey_scale_lab/cli.py` | Possibly extend | If resource preflight needs explicit `--phase`/`--node-count` support, add backward-compatible CLI flags. |
| `schemas/artifact/failover_latency_sample.schema.json` | Possibly strengthen | Require core P20 evidence fields if assertion-only checks are insufficient. |
| `schemas/artifact/failover_latency_curve.schema.json` | Possibly strengthen | Require per-rung derived series shape and percentile method if assertion-only checks are insufficient. |
| `schemas/artifact/fault_matrix_report.schema.json` | Possibly strengthen | Require `primary_stop_failover` row content if assertion-only checks are insufficient. |
| `schemas/artifact/workload_impact_report.schema.json` | Possibly strengthen | Require canonical window row shape if assertion-only checks are insufficient. |
| `tests/unit/test_goal_loop_assertions.py` | Add tests | Cover P20 curve assertion acceptance/rejections: missing rung, duplicate sample ID, reused timings, missing cleanup, non-derived curve value, missing workload ref, and downshifted 100-node evidence. |
| `tests/failover/test_failover_contract.py` | Add tests | Cover P20 sample/curve artifact shape and failover gate helper behavior without running Docker. |
| `tests/ci/test_fault_failover_scale_gate.py` | Possibly update | Keep legacy L08 checks compatible while adding P20 no-P14/no-1000 and `--require-data-path` expectations if relevant. |
| `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/*` | Generate | Required stage evidence artifacts from real gate execution. |
| `artifacts/goal_loop/P20_FAILOVER_LATENCY_CURVE_30_50_100/WORKER_SUMMARY.md` | Generate later | Worker handoff, not part of design implementation. |

## Implementation plan

1. Add P20 setup support to the runtime using the existing scale process runtime for scenarios such as `failover_curve_30`, `failover_curve_50`, and `failover_curve_100`. Each scenario must enforce the exact configured node count and use deterministic run IDs, ports, labels, state paths, and cleanup.
2. Extend `fault_failover_gate.py` so `--phase P20_FAILOVER_LATENCY_CURVE_30_50_100 --scenario failover_curve_30_50_100` runs a controller loop over rungs `[30, 50, 100]` and samples `[1, 2, 3]`.
3. Before each rung, run resource preflight for the exact rung config and write `resource_preflight_30.json`, `resource_preflight_50.json`, and `resource_preflight_100.json` under the P20 artifact directory. If any preflight returns `can_run=false`, write enough failure/blocking evidence for diagnosis and return non-zero; do not write a PASS curve.
4. For each sample, create a fresh real cluster from the matching `scale_<rung>.yaml`, lower workload QPS only if resource preflight records a safe-degradation reason, select a live primary with a replica, and record replica candidates plus before topology from live `CLUSTER NODES`.
5. Apply `node_stop` through `python3 -m valkey_scale_lab.cli fault apply` or the same owned-runtime primitive. For process runtime this must kill only the target Valkey PID inside the owned nodehost container.
6. Poll live cluster views for primary unreachability, replica promotion, `cluster_state:ok`, full slot coverage, and first successful read/write to the affected slot range. Capture monotonic and Unix millisecond timestamps for all required sample fields.
7. Clear the fault, wait for the old primary to rejoin when it does rejoin, and encode `old_primary_rejoined_at_ms` as `MISSING` with reason if it is not observable. Cleanup must run after every sample regardless of success.
8. Emit one raw row per sample to `failover_latency_samples.jsonl`; derive `failover_latency_curve.json` only from those rows using a declared percentile method. With three samples, p50, p95, and max must be calculated from the three raw values, not copied or invented.
9. Emit canonical P20 `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `workload_impact_report.json`, `fault_matrix_report.json`, `quant_summary.json`, `phase_summary.json`, `valkey_e2e_evidence.json`, and aggregate `cleanup_report.json`.
10. Strengthen assertions and tests so P20 cannot pass with one gate run, one sample copied nine times, smaller node counts, fake Valkey evidence, missing workload refs, missing cleanup refs, or curve values inconsistent with raw samples.

## Harness, schema, and gate plan

- Keep P20 bounded to max 100 nodes. Do not touch P21 200-node gates except if a shared helper needs a backward-compatible path.
- Prefer updating the P20 manifest real gate to use all three rung configs explicitly, for example via new `fault_failover_gate.py` flags `--rungs 30,50,100 --samples-per-rung 3 --config-dir templates/configs`, or make the existing `failover_curve_30_50_100` scenario expand internally. The gate command must not imply that `scale_100.yaml --min-nodes 30` is enough.
- `assert_failover_latency_curve.py` should require for P20:
  - exactly rungs `{30, 50, 100}`;
  - at least three samples per rung;
  - every sample has `status=PASS`, `real_valkey=true`, exact `node_count`, unique `sample_id`, unique sample run/state refs, target primary/node/az/host fields, replica candidates, `fault_injection_method`, `promotion_detection_method`, `slot_coverage_detection_method`, `workload_impact_ref`, and `cleanup_ref`;
  - required timestamps are numeric, ordered, and produce the reported latency fields;
  - cleanup status per sample is PASS;
  - derived series for promotion and cluster recovery p50/p95/max match raw sample rows;
  - no sample has `node_count < 100` for the 100 rung or any `SKIPPED_WITH_REASON` pretending to be success.
- `assert_quant_artifacts.py` should verify P20 event/metric counts in `quant_summary.json` match JSONL files and that every failover sample has corresponding event and metric rows.
- `assert_workload_impact.py` should verify canonical window names and metrics and, for P20, that rows can be traced back to failover samples or aggregated sample refs.
- `fault_matrix_report.json` should contain a `primary_stop_failover` row for each rung or per sample, with `implementation_path` set to `owned_runtime_control` or `owned_container_control`, safety scope verified, target refs, observed impact, and cleanup verified.
- Existing `scripts/assert_cleanup.py` must remain authoritative for aggregate cleanup. The P20 cleanup artifact should include child cleanup reports or summaries for all nine sample runs and fail if any child cleanup fails.

## Test plan

- Run `python3 -m compileall -q scripts src`.
- Run focused unit tests for assertion changes: `python3 -m pytest -q tests/unit/test_goal_loop_assertions.py tests/failover/test_failover_contract.py`.
- Run required common tests: `python3 -m pytest -q tests/unit tests/integration`.
- Run `python3 scripts/safety_scan.py` and confirm no host firewall/routing/interface mutation is introduced.
- Run `python3 scripts/assert_goal_loop_stage.py --phase P20_FAILOVER_LATENCY_CURVE_30_50_100`.
- Run the real P20 wrapper gate from the manifest after updating it, producing all P20 artifacts. This is expected to be long-running and Docker-dependent.
- Run `python3 scripts/assert_quant_artifacts.py --phase P20_FAILOVER_LATENCY_CURVE_30_50_100`.
- Run `python3 scripts/assert_failover_latency_curve.py --phase P20_FAILOVER_LATENCY_CURVE_30_50_100`.
- Run `python3 scripts/assert_workload_impact.py --phase P20_FAILOVER_LATENCY_CURVE_30_50_100`.
- Run `python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/cleanup_report.json`.
- If any 30/50/100 resource preflight fails, write `artifacts/goal_loop/P20_FAILOVER_LATENCY_CURVE_30_50_100/BLOCKED.md` and do not run postcheck or mark-complete.

## Required artifacts

Under `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/`:

- `phase_summary.json`
- `valkey_e2e_evidence.json`
- `cleanup_report.json`
- `events.jsonl`
- `metrics_timeseries.jsonl`
- `workload_windows.json`
- `quant_summary.json`
- `failover_latency_samples.jsonl`
- `failover_latency_curve.json`
- `fault_matrix_report.json`
- `workload_impact_report.json`
- `resource_preflight_30.json`
- `resource_preflight_50.json`
- `resource_preflight_100.json`
- Per-sample state, setup logs, fault apply/clear logs, and cleanup reports under deterministic child directories or filenames, referenced by the summary artifacts.

Under `artifacts/goal_loop/P20_FAILOVER_LATENCY_CURVE_30_50_100/`:

- `DESIGN_BRIEF.md`
- later `WORKER_SUMMARY.md`, `REVIEW.md`, and either `COMPLETION.md` or `BLOCKED.md`.

## Safety considerations

- All faults must be scoped to owned Docker resources or owned Valkey PIDs inside owned nodehost containers. No host interface, route, firewall, PF, nftables, iptables, or OS network service mutation is allowed.
- The process-runtime primary stop must use PID/container identity from the P20 state file and refuse to act if the target is not in the owned state.
- Every sample must clean up in `finally`-style logic. Aggregate cleanup must fail if any child cleanup leaves owned containers, nodehosts, networks, Valkey processes, fault state files, or generated runtime bundles.
- Ports must remain deterministic and collision-checked. If three fresh samples per rung reuse the same config ports, cleanup must finish before the next sample begins; otherwise use deterministic per-sample port offsets.
- Do not run P14 or any 1000-node path. Do not add a default larger than 100 nodes.
- Do not mark P20 complete on fake-only tests, static generated sample rows, or resource-preflight failure.

## Resource considerations

- P20 requires 30, 50, and 100 node real Valkey clusters, three samples each. The design should assume sequential sample execution to cap peak resource use at one rung/sample cluster at a time.
- Resource preflight must record host OS/arch, Docker availability/version, CPU count, memory estimate, disk free, client and cluster-bus port availability, runtime/container limits where available, node count, estimated memory per node, and workload overhead.
- For 100 nodes, the existing process runtime is preferred because P13 already uses it for scale rungs and it avoids one-container-per-node pressure.
- Safe degradation may reduce workload QPS to a documented low non-zero probe workload, but it must not reduce node count, omit workload windows, omit cleanup, or convert real evidence to dry-run evidence.
- If Docker, ports, memory, disk, or runtime limits are insufficient for any rung, P20 is blocked. The correct outcome is non-zero gate plus `BLOCKED.md`, not a passing stage.

## `待验证`

- Whether the existing process runtime can run nine fresh 30/50/100 failover samples within the current P20 manifest timeout of 3600 seconds. If not, the timeout may need a transparent manifest increase with justification.
- Whether `valkey/valkey:9.1.0` is already present locally or Docker image pull/network availability will affect the real gate.
- Whether the process-runtime `node_stop` clear path reliably restarts the old primary and allows it to rejoin after promotion at 30/50/100. If not, encode old-primary rejoin as `MISSING` with reason only where allowed, while still requiring promotion/recovery/read/write timestamps.
- Whether using `CONFIG SET cluster-node-timeout` at scale is sufficient for stable bounded failover timing without making samples too slow.
- Whether canonical workload windows should be emitted per sample, per rung, or both. The assertions should accept only forms with traceable sample references.
- Whether schema strengthening is necessary or assertion-level semantic checks are enough for P20 without causing unrelated P21+ churn.
- Whether `resource.py` should gain an explicit `--phase` option or whether `fault_failover_gate.py` should own P20-specific preflight normalization.

## Worker instructions

- Implement only this stage.
- Do not commit.
- Do not weaken harness or safety rules.
- Do not implement P21 200-node samples, P22 replica/host/AZ faults, P23 network faults, P24 partitions, P25 consolidation, or P26 final reports.
- Do not pass P20 by reusing one sample, copying generated values, downshifting the 100-node rung, or treating resource insufficiency as success.
