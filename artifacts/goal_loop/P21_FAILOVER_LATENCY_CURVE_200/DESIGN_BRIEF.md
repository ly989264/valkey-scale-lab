# DESIGN_BRIEF - P21_FAILOVER_LATENCY_CURVE_200

## Objective

Implement the bounded 200-node primary-stop failover curve stage. P21 must either run exactly three real Valkey 9.1.x 200-node samples with workload, failover timing, combined curve, and cleanup artifacts, or block cleanly on strict resource preflight. It must not downshift to 100 nodes, use dry-run output, fake Valkey evidence, or change the normal 100-node default cap.

## Repository findings

- `python3 scripts/codex_gate.py next` returns `P21_FAILOVER_LATENCY_CURVE_200`; `codex/status/phase_state.json` shows P20 complete.
- `artifacts/goal_loop/P21_FAILOVER_LATENCY_CURVE_200/CONTEXT_RELOAD.md` already exists; this design brief is the only file this subagent should write.
- `codex/phase_manifest.json` already defines P21 with a real gate command using `templates/configs/scale_200.yaml`, `--scenario failover_curve_200`, `--min-nodes 200`, and required artifacts including `resource_preflight_200.json`, `failover_latency_samples_200.jsonl`, `failover_latency_curve_200.json`, and `failover_latency_curve_combined_30_50_100_200.json`.
- `templates/configs/scale_200.yaml` is missing. The manifest currently points at a non-existent config.
- `scripts/fault_failover_gate.py` has a working P20 controller for 30/50/100, but its controller, filenames, artifact refs, phase IDs, workload rows, events, metrics, summaries, and sample paths are P20-specific.
- `scripts/assert_failover_latency_curve.py` knows P21 filenames and rejects non-200 samples, but its strong semantic checks are P20-only. P21 currently lacks duplicate run/state detection, real-valkey field checks, cleanup checks, timestamp arithmetic checks, derived-series checks, and combined-curve validation.
- `scripts/assert_quant_artifacts.py` has P16 and P20 semantic checks, but no P21-specific checks for exactly three samples, phase IDs in events/metrics, count agreement, or real fault runtime claims.
- `scripts/assert_workload_impact.py` validates generic workload windows and has P20-specific sample/rung checks, but no P21-specific requirement for exactly three 200-node samples and comparisons.
- `src/valkey_scale_lab/runtime/docker_runtime.py` only recognizes P20 scale sample scenarios for large failover samples. `_uses_docker_process_runtime()` and `_scenario_node_count_allowed()` do not allow P21 200-node sample setup.
- `src/valkey_scale_lab/resource.py` currently fails `node_count_limit` for any non-dry-run config over 100 nodes and maps 200 nodes to a non-P21 phase. P21 needs a narrow 200-node exception without changing the default cap.
- P20 artifacts under `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/` contain the curve shape P21 should extend: nine raw samples, per-rung resource preflights, top-level workload impact, events, metrics, cleanup, and real evidence.
- Editing `scripts/*.py`, `codex/phase_manifest.json`, or `codex/gate_lock.json` touches harness-control files. If scripts or manifest must change, the worker should write a transparent `artifacts/harness_exception/P21_FAILOVER_LATENCY_CURVE_200.md` explaining the defect and the strengthening behavior, then update `codex/gate_lock.json` only to reflect the intentional strengthened controls.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `templates/configs/scale_200.yaml` | add | Provide the explicit 200-node config required by the P21 manifest. Use 100 shards, 1 replica per shard, distinct ports, Valkey 9.1.0, sandbox networking, and low non-zero workload settings. |
| `src/valkey_scale_lab/resource.py` | modify | Add a narrow non-dry-run P21 200-node resource-preflight exception, strict 200-node metadata, Docker/version/runtime-limit recording, host resource estimates, port checks, and no dry-run pass path. |
| `src/valkey_scale_lab/runtime/docker_runtime.py` | modify | Recognize only P21 sample scenarios such as `scale_200_sample_01`, use docker-process runtime, and allow exactly 200 nodes for those scenarios without widening other phases. |
| `scripts/fault_failover_gate.py` | modify | Generalize the P20 controller into a P20/P21 curve controller or add a P21 controller that runs exactly three 200-node samples, writes P21 filenames, creates the combined curve, writes `BLOCKED.md` on preflight failure, and never writes fake PASS artifacts. |
| `scripts/assert_failover_latency_curve.py` | modify | Add P21 semantic checks equivalent to or stricter than P20 and validate the combined 30/50/100/200 curve. |
| `scripts/assert_quant_artifacts.py` | modify | Add P21 count/phase/runtime semantic checks for events, metrics, samples, and quant summary. |
| `scripts/assert_workload_impact.py` | modify | Add P21 checks for exactly three 200-node sample IDs, rung/node_count 200, and comparisons for each sample. |
| `tests/integration/test_docker_runtime_contract.py` | modify | Cover P21 sample scenario allowance, process runtime selection, exact 200 node specs, and rejection of non-P21 200-node scenarios. |
| `tests/scale/test_scale_ladder.py` or new resource test | modify/add | Cover P21 preflight exception, `dry_run=false`, exact node_count 200, recorded resource fields, and continued rejection of unrelated >100 real configs. |
| `tests/failover/test_failover_contract.py` | modify | Cover P21 scenario aliasing and P21 controller/path helpers where practical. |
| `tests/unit/test_goal_loop_assertions.py` | modify | Add focused P21 assertion tests for accepting valid 200 samples, rejecting downshifted/duplicate/fake samples, and rejecting bad combined-curve values. |
| `artifacts/harness_exception/P21_FAILOVER_LATENCY_CURVE_200.md` | add if harness scripts/manifest change | Required by harness-integrity rules when strengthening controlled scripts or manifest behavior. |
| `codex/gate_lock.json` | modify if controlled files change | Update locked hashes only after documented strengthening; do not weaken or bypass lock checks. |
| `codex/phase_manifest.json` | modify only if necessary | Prefer avoiding manifest churn. If the 3600s P21 real-gate timeout proves insufficient for real 200-node evidence, increase it with a harness exception and lock update. |

## Implementation plan

1. Add `scale_200.yaml` with `shards: 100`, `replicas_per_shard: 1`, unique client and bus port ranges, `valkey/valkey:9.1.0`, `default_max_nodes: 100`, `allow_1000_nodes: false`, and a documented low non-zero workload profile such as low QPS and pipeline 1. Keep the 200-node exception stage-scoped; do not change normal defaults.
2. Strengthen `run_resource_preflight()` so node_count 200 maps to `P21_FAILOVER_LATENCY_CURVE_200`, is allowed only as the bounded P21 exception, records host OS/arch, Docker availability/version, CPU, memory, disk, port ranges, runtime-limit facts, per-host node estimates, estimated memory/disk per node, and workload overhead. It must fail when required checks cannot pass and must report `dry_run: false` for P21 gate usage.
3. Add a P21 scenario parser in runtime, separate from P20, for `P21_FAILOVER_LATENCY_CURVE_200` plus `scale_200_sample_\d+`. Use it in `_uses_docker_process_runtime()` and `_scenario_node_count_allowed()` so only exact 200-node P21 sample setup is admitted.
4. In `fault_failover_gate.py`, extract reusable curve-controller helpers or add P21-specific wrappers around the P20 flow. P21 controller should:
   - run `resource_preflight_200.json` first;
   - on preflight failure, write `artifacts/goal_loop/P21_FAILOVER_LATENCY_CURVE_200/BLOCKED.md`, print failures, return non-zero, and avoid fake PASS artifacts;
   - run exactly samples 1, 2, and 3 using scenarios `scale_200_sample_01_fault_failover` through `scale_200_sample_03_fault_failover`;
   - pass `--min-nodes 200`, `--require-data-path`, and a 200-safe low workload operation count if a new CLI option is added;
   - write P21 top-level artifacts with phase ID `P21_FAILOVER_LATENCY_CURVE_200` and no hard-coded P20 refs.
5. Generate `failover_latency_samples_200.jsonl` from the three real sample evidence files. Each row must have `node_count: 200`, `rung: 200`, `status: PASS`, `real_valkey: true`, unique `run_id` and `state_ref`, cleanup PASS, target primary metadata, replica candidates, live detection methods, required timestamps, latency arithmetic, read/write unavailability, and workload-impact refs.
6. Generate `failover_latency_curve_200.json` from only the three 200-node raw sample rows. Derived series must include `promotion_latency_ms` and `cluster_recovery_latency_ms` with `p50_ms`, `p95_ms`, `max_ms`, `sample_count: 3`, and recorded percentile method.
7. Generate `failover_latency_curve_combined_30_50_100_200.json` by loading P20 `failover_latency_curve.json` and the new P21 200 curve. Preserve P20 derived series exactly, append the P21 200 derived series, set rungs to `[30, 50, 100, 200]`, and record both source artifact paths.
8. Emit P21 `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `workload_impact_report.json`, `fault_matrix_report.json`, `failover_report.json`, `cleanup_report.json`, `valkey_e2e_evidence.json`, `quant_summary.json`, and `phase_summary.json` using the P20 artifact pattern but P21 filenames and phase IDs.
9. Strengthen assertion scripts for P21 so a false pass is impossible: fail on missing preflight, dry-run preflight, non-200 sample, fewer or more than three samples, fake evidence flags, reused state/run refs, missing cleanup, missing workload comparisons, missing events/metrics sample IDs, incorrect quant counts, bad latency arithmetic, or combined-curve mismatch.

## Harness, schema, and gate plan

- Keep the manifest command shape unless real runs prove the timeout insufficient.
- Run P21 through `python3 scripts/codex_gate.py run --phase P21_FAILOVER_LATENCY_CURVE_200`; do not run a manual alternate command as the sole evidence.
- Required P21 assertions:
  - `scripts/assert_goal_loop_stage.py --phase P21_FAILOVER_LATENCY_CURVE_200`
  - `scripts/assert_quant_artifacts.py --phase P21_FAILOVER_LATENCY_CURVE_200`
  - `scripts/assert_failover_latency_curve.py --phase P21_FAILOVER_LATENCY_CURVE_200`
  - `scripts/assert_workload_impact.py --phase P21_FAILOVER_LATENCY_CURVE_200`
  - `scripts/assert_cleanup.py --cleanup-report artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/cleanup_report.json`
- Existing schemas appear permissive enough for the required P21 artifacts; prefer strengthening assertion semantics over schema churn unless a schema blocks required fields.
- If scripts or manifest are changed, update `codex/gate_lock.json` after writing the harness exception and after confirming `python3 scripts/codex_gate.py precheck --phase P21_FAILOVER_LATENCY_CURVE_200` still detects unauthorized drift.

## Test plan

- `python3 -m compileall -q scripts src`
- `python3 -m pytest -q tests/unit tests/integration`
- Focused tests:
  - runtime accepts `P21_FAILOVER_LATENCY_CURVE_200/scale_200_sample_01` at exactly 200 nodes and rejects 100/201/unrelated 200-node scenarios;
  - resource preflight allows only the P21 bounded 200-node exception and keeps `default_max_nodes` at 100;
  - P21 curve assertion accepts a synthetic valid three-sample 200 bundle and rejects downshifted, duplicate, fake, missing-cleanup, bad-timestamp, and bad-derived-curve bundles;
  - P21 workload assertion requires three sample IDs, node_count/rung 200, all canonical windows, and comparisons;
  - P21 quant assertion requires event/metric sample coverage and exact counts.
- Real gate:
  - `python3 scripts/codex_gate.py run --phase P21_FAILOVER_LATENCY_CURVE_200`
  - If it passes, follow with post-worker assertion reruns and cleanup assertion.
  - If preflight or Docker startup fails, verify `BLOCKED.md` exists and the stage remains incomplete.

## Required artifacts

- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/phase_summary.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/valkey_e2e_evidence.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/cleanup_report.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/events.jsonl`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/metrics_timeseries.jsonl`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/workload_windows.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/quant_summary.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/resource_preflight_200.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/failover_latency_samples_200.jsonl`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/failover_latency_curve_200.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/failover_latency_curve_combined_30_50_100_200.json`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/workload_impact_report.json`
- Expected additional generated evidence views: `failover_report.json`, `fault_matrix_report.json`, per-sample evidence/cleanup/state/logs under a P21 sample subdirectory, and `artifacts/goal_loop/P21_FAILOVER_LATENCY_CURVE_200/BLOCKED.md` only if blocked.

## Safety considerations

- Do not use sudo, host firewall/routing/interface changes, PF, nftables, iptables, or host network mutation.
- Fault application must remain scoped to owned Docker process/container state via `valkey_scale_lab.cli fault apply`.
- Cleanup must run after every sample and aggregate all per-sample cleanup reports; any remaining owned resource must fail the stage.
- Keep P14 non-automatic and do not introduce any 1000-node execution path.
- Keep the repository default max at 100 nodes. The only 200-node allowance should be P21 exact sample scenarios and P21 resource preflight.
- Do not generate P21 PASS artifacts from P20 data. The combined curve may reuse P20 curve data only for the 30/50/100 series; the 200 series must come from fresh P21 samples.

## Resource considerations

- P21 is allowed to block. If `resource_preflight_200.json` reports `status != PASS`, `can_run != true`, insufficient ports, insufficient memory/disk/CPU, Docker unavailable, runtime limits too low, or stale owned resources, write `BLOCKED.md`, return non-zero, and stop.
- A 200-node config should use a low but non-zero workload to reduce host load while still proving data-path recovery.
- The current resource estimator requires at least `node_count * 32 MB`; a 200-node profile therefore needs at least about 6400 MB estimated capacity and should not declare a higher per-node memory limit unless the host can support it.
- Use unique deterministic port ranges for 200 nodes and preflight both client and cluster bus ports before starting Docker resources.
- If the 200-node process runtime starts but one sample fails, run cleanup, preserve failure evidence, and fail the stage rather than filling missing values with invented metrics.

## `待验证`

- `scale_200.yaml` exact port bases need confirmation against local port use; proposed ranges should not overlap existing scale configs.
- The local Docker host may not have enough memory, port capacity, or runtime limits for 200 Valkey processes; this can only be known by running preflight and, if it passes, the real gate.
- The existing 3600-second P21 real-gate timeout may or may not be sufficient for three 200-node samples on the current host.
- Valkey 9.1.0 process memory may exceed the conservative 32 MB per-node estimate under 200-node clustering; real startup is authoritative.
- The P20 combined-curve source artifacts are present now, but the worker should fail clearly if they are absent or invalid when P21 runs.

## Worker instructions

- Implement only P21.
- Do not commit.
- Do not weaken harness or safety rules.
- If P21 blocks on resources, write `BLOCKED.md`, preserve preflight evidence, and stop without mark-complete.
- If changing locked harness files, document the strengthening in `artifacts/harness_exception/P21_FAILOVER_LATENCY_CURVE_200.md` and update the gate lock transparently.
