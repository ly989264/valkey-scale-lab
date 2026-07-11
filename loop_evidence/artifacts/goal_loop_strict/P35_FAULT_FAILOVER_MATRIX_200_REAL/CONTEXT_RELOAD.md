# CONTEXT_RELOAD — P35_FAULT_FAILOVER_MATRIX_200_REAL

## Stage

- Stage ID: `P35_FAULT_FAILOVER_MATRIX_200_REAL`
- Stage title: Real 200-Node Fault/Failover Matrix
- Branch: `codex/valkey-scale-lab-loop`
- Current commit: `1dad23b`
- Date/time: `2026-07-04 13:32:52 +0800`

## Harness status

```text
python3 scripts/codex_gate.py next
P35_FAULT_FAILOVER_MATRIX_200_REAL
```

## Git status

```text
git status --short
```

No output; the worktree was clean at stage start.

## Documents Reread

- [x] `AGENTS.md` — `526ec292746dcc941bc4b7e119224d6f6a51b7588cc3aa05848199142b04bed4`
- [x] `CODEX_START_HERE.md` — `931d0a910568b1f60975a053040f5da9bd0d131ca10d0e71bfae9103729d81a2`
- [x] `CODEX_GOAL_LOOP_START.md` — `a7a5ebc31f91c286a023346582741ca4720441d142d040824de12eedf5c72a01`
- [x] `CODEX_STRICT_MATRIX_LOOP_START.md` — `9fecc694a159900e41ad4c1dd9c72782f25199effd9d1f3fdf17159c6de5d5ad`
- [x] `docs/codex/goal-loop/00_INDEX.md` — `95d554d92c5a27edeacf7adf414a936097f430203fc46fb5df0353d0b967fbc2`
- [x] `docs/codex/goal-loop/01_GOAL_CONTRACT.md` — `e531782d401244ed6109b6a0ca2b30a0a90e5387ccf8a0981c3fc529079c842d`
- [x] `docs/codex/goal-loop/02_STAGE_MANIFEST.md` — `ddcbe062a415476c999ac58ed5348c97df37a71b1d14c76274796e4211aef087`
- [x] `docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md` — `bec65c0606d91d965ab53617797d562b3128e65ee1c83071ea14db18fc233b54`
- [x] `docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md` — `b41b242bfe0fd55c41c0cc42d554ab9b9a17bb5b968ddca70989c81d652687c4`
- [x] `docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md` — `2eac8dadc43e2798a3e83c5b67d991bc7edf0ad63d5dad07f22486336c422d2e`
- [x] `docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md` — `76a09a0e22ae3009f99450c8af811e8fdb1bb9a8dd5db51d34eda6425e1e1e11`
- [x] `docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md` — `46cf74ab91d852b6a6b7035e0f2f564772f5a836da072cb87fa80ec5d703b227`
- [x] `docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md` — `9fb5f24d21ec778fc9c325a9c5651f1bc80a381d10fd554133ec8e4559193c0c`
- [x] `docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md` — `bde2525a37ae8b6e592b2caac2839771ec5d0717e48bbc684c17044d8d02fa87`
- [x] `docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md` — `9faac6019b514259823fdf1adef55f7821916541b813a57224b21c874834e219`
- [x] `docs/codex/goal-loop-strict/00_INDEX.md` — `3410a7322c06d1f54587b5a347e1f6fd1432b275e7ff7c5a1e198f584942d54a`
- [x] `docs/codex/goal-loop-strict/01_STRICT_GOAL_CONTRACT.md` — `de75e5d0299da66850c375a49411030f56dab1ff96df432d74a1484fff863a4a`
- [x] `docs/codex/goal-loop-strict/02_STRICT_STAGE_MANIFEST.md` — `94bc31e4f613c3594d861eab9b3644b1d23b874969048f5b6aba0ad6c75d7ae8`
- [x] `docs/codex/goal-loop-strict/03_MAIN_SUBAGENT_LOOP_PROTOCOL.md` — `a066649a84004191814030170c6a5e35f310383117d6279d06186bdca13c4a9a`
- [x] `docs/codex/goal-loop-strict/04_CONTEXT_LEDGER_PROTOCOL.md` — `a2b0d19323884fa69fcb0c29ee38a71202e584146ee3959484e35638084a22fa`
- [x] `docs/codex/goal-loop-strict/05_FAIL_CLOSED_HARNESS_CONTRACT.md` — `d6647319d58b00665068ba71ee0b59f9969d063b1d9a54ddd682122a054460d0`
- [x] `docs/codex/goal-loop-strict/06_COVERAGE_REGISTRY_SPEC.md` — `227ce06e844d70cd6c0ce96c53a08930043eb598c297c11a9478799376d0b62e`
- [x] `docs/codex/goal-loop-strict/07_QUANTIFICATION_DATA_CONTRACT.md` — `6f83b80b004c817bccebf6aad6d36b184b77192c1c60cea74ae2ca97f0419075`
- [x] `docs/codex/goal-loop-strict/08_MANAGEMENT_OPERATION_MATRIX_SPEC.md` — `e406bb76053cf41ccf3ab93a9439dff98b419d3c844b7bcf6956e38d23143452`
- [x] `docs/codex/goal-loop-strict/09_FAULT_FAILOVER_MATRIX_SPEC.md` — `575b3216fac2acde73e36549d49b2c3c437a9636fd22e4b56d979751c6da6cf7`
- [x] `docs/codex/goal-loop-strict/10_SCALE_EXECUTION_POLICY.md` — `88c43864f29392da36651893347b7ede49095cfb72de356608e85fc262c23695`
- [x] `docs/codex/goal-loop-strict/11_ANALYSIS_VISUAL_REPORT_SPEC.md` — `7be5dc14331f136572235060078cecc68a19a7f6b75d72e9f13ef1dc2e67bbc2`
- [x] `docs/codex/goal-loop-strict/12_AUDIT_COMMIT_NO_BYPASS_POLICY.md` — `34ffca6f0dc17e24951c601b5c731b136e2d033f6f8daff69e2b2674fe829092`
- [x] `docs/codex/goal-loop-strict/stages/P35_FAULT_FAILOVER_MATRIX_200_REAL.md` — `d54cd5ede623c5cd607c0cf15f6eae85b1d9838c4b8c542bf7b266c1ea82989f`
- [x] `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md` — `6d916f03927750e33bffbc27a793031d585bae4ccce86c806a8b3487156884a0`

## Current Stage Contract Summary

P35 must execute the complete strict fault, failover, partition, split-brain, and workload-impact matrix on exactly 200 real Valkey 9.1.x nodes. It is a user-required bounded exception to the normal 100-node default cap. It must not downshift to 100 nodes, must not run above 200 nodes, and must not substitute generated artifacts or stale P33/P34 evidence. Resource preflight must record `can_run=true`, evidence must record `nodes_requested=200` and `nodes_observed=200`, and cleanup must pass with no owned resources left behind.

Required fault rows are:

```text
primary_stop_failover
replica_stop
node_host_stop
az_stop
network_delay
network_loss
network_flap
network_partition
minority_partition
majority_partition
split_brain_window_detection
fault_period_workload_impact
```

`primary_stop_failover` must include at least three independent real samples. Network faults must remain scoped to `container_netns_tc` or `sandbox_proxy`; host firewall, route, interface, PF, nftables, iptables, OS network service mutation, and `sudo` network changes are forbidden. Split-brain detectors must actually run, and required rows may not pass as skipped or missing.

Required P35 artifacts are:

```text
phase_summary.json
valkey_e2e_evidence.json
resource_preflight.json
cluster_plan.json
run_state.json
cleanup_report.json
events.jsonl
metrics_timeseries.jsonl
workload_windows.json
quant_summary.json
coverage_ledger.json
fault_matrix_report.json
fault_operation_results.jsonl
failover_samples.jsonl
failover_latency_curve.json
partition_report.json
split_brain_report.json
fault_workload_impact.json
fault_topology_snapshots.jsonl
fault_command_log.jsonl
```

Required assertions include exact-scale real evidence for 200 nodes, strict fault matrix coverage for all rows, failover latency curve with at least three samples, split-brain report validation, quant completeness for `fault` at scale 200, coverage registry update for `200.fault.*`, no-bypass, and cleanup.

## Prior-Stage Handoff Summary

P33 completed the exact 50-node real fault/failover matrix. P34 completed the exact 100-node real fault/failover matrix and was committed/pushed as `1dad23b`. P34's gate result was `artifacts/gates/P34_FAULT_FAILOVER_MATRIX_100_REAL/gate_result.json` with SHA `53bd4b27de759c598759a21218e10d467628ab0997112474ca9c20bcc8ef6503`; it produced 12 PASS `100.fault.*` rows, 3 failover samples, 28 events, 70 metric samples, 14 workload windows, 14 topology snapshots, 113 command-log rows, split-brain detector evidence, partition evidence, exact 100-node Valkey 9.1.0 evidence, and cleanup PASS.

The P35 handoff is to carry the same strict fault/failover proof to exactly 200 real nodes after resource preflight passes. P35 must not use P34 evidence as proof for `200.fault.*`.

## Known Blockers

No blocker is known at context reload time. P35 must become blocked, not passed, if resource preflight cannot support 200 nodes, if exactly 200 live Valkey nodes cannot be observed, if a required fault row is skipped or missing, if fewer than three primary-stop failover samples are collected, if split-brain evidence lacks detector proof, if any required workload window is missing, if safe network faulting requires host-level mutation, or if cleanup fails.

## Assumptions and 待验证 Items

- 待验证: whether P34's strict fault profile/controller can be extended to P35 exact 200 without weakening P33/P34 or allowing 200 by default outside this stage.
- 待验证: whether `templates/configs/scale_200.yaml` and runtime semantics already admit a P35 strict fault setup scenario.
- 待验证: whether `scripts/assert_quant_completeness.py` needs a P35 strict fault entry for `200.fault.*` analogous to P34.
- 待验证: whether this environment can pass Docker resource preflight and run exactly 200 real Valkey nodes for the fault matrix.
- Assumption: the current branch remains `codex/valkey-scale-lab-loop`, and P35 changes will be committed and pushed as a single stage only after design, worker, gates, fresh-context review, postcheck, mark-complete, subagent closure, completion update, and journal update.
