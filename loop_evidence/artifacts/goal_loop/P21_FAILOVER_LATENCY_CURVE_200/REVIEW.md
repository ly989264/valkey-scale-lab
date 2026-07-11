# REVIEW - P21_FAILOVER_LATENCY_CURVE_200

## Scope reviewed

Fresh-context review of P21 only. I inspected the controlling goal-loop docs, stage doc, context reload, design brief, worker summary, fix log, git diff, manifest gates, gate logs, schemas, required artifacts, real Valkey evidence, cleanup reports, and safety boundaries. I did not rely on the worker summary as proof.

## Documents and artifacts read

- `AGENTS.md`, `CODEX_START_HERE.md`, `CODEX_GOAL_LOOP_START.md`, `docs/codex/02_PHASES.md`, `docs/codex/04_AUDITOR.md`
- `docs/codex/goal-loop/00_INDEX.md` through `docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md`
- `docs/codex/goal-loop/stages/P21_FAILOVER_LATENCY_CURVE_200.md`
- `artifacts/goal_loop/P21_FAILOVER_LATENCY_CURVE_200/CONTEXT_RELOAD.md`
- `artifacts/goal_loop/P21_FAILOVER_LATENCY_CURVE_200/DESIGN_BRIEF.md`
- `artifacts/goal_loop/P21_FAILOVER_LATENCY_CURVE_200/WORKER_SUMMARY.md`
- `artifacts/goal_loop/P21_FAILOVER_LATENCY_CURVE_200/FIX_LOG.md`
- `codex/phase_manifest.json`
- `artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/gate_result.json`
- `artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/stdout/*.log`
- `artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/stderr/*.log`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/*`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/_p21_samples/*/single_sample.stderr.log`
- `artifacts/phases/P21_FAILOVER_LATENCY_CURVE_200/_p21_samples/*/cleanup_report.json`

`artifacts/goal_loop/P21_FAILOVER_LATENCY_CURVE_200/BLOCKED.md` is absent.

## Diff review

The P21 diff is scoped to the bounded 200-node failover stage: `scale_200.yaml`, P21 resource-preflight/runtime admission, the P21 failover controller, P21 assertions, safety scan exception, tests, gate lock update, and stage artifacts. The normal default max remains 100; P14 remains `automatic: false`; the 200-node allowance is tied to `P21_FAILOVER_LATENCY_CURVE_200`, `scale_200`, exact node count 200, `dry_run: false`, and `allow_1000_nodes: false`.

## Gate review

Gate result path: `artifacts/gates/P21_FAILOVER_LATENCY_CURVE_200/gate_result.json`

Observed gate result SHA256: `1166763b682bed67750d2b147259d3c7ed24bcdf32f082e64450bf481f4d4dca`

The gate result status is `PASS`. Manifest command text matches the gate result exactly for all 10 gates. All stdout/stderr files exist and SHA256 values match the gate result.

| Gate/check | Evidence | Result |
|---|---|---:|
| harness_precheck | `stdout/harness_precheck.log`, hash verified | PASS |
| safety_static_scan | `stdout/safety_static_scan.log`, hash verified | PASS |
| scripts_compile | `stdout/scripts_compile.log`, `stderr/scripts_compile.log`, hashes verified | PASS |
| unit_integration_tests | `stdout/unit_integration_tests.log` reports 109 passed, hash verified | PASS |
| goal_loop_stage_assertion | `stdout/goal_loop_stage_assertion.log`, hash verified | PASS |
| real_failover_gate | `stdout/real_failover_gate.log`, empty stderr hash verified | PASS |
| quant_artifact_assertion | `stdout/quant_artifact_assertion.log`, hash verified | PASS |
| failover_curve_assertion | `stdout/failover_curve_assertion.log`, hash verified | PASS |
| workload_impact_assertion | `stdout/workload_impact_assertion.log`, hash verified | PASS |
| cleanup_report_check | `stdout/cleanup_report_check.log`, hash verified | PASS |

## Artifact/schema review

All P21 manifest-required artifacts exist and validate against their schemas:

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

Additional P21 evidence files are present for `failover_report.json`, `fault_matrix_report.json`, and per-sample evidence/cleanup under `_p21_samples/`.

## Real Valkey evidence review

`valkey_e2e_evidence.json` records `status: PASS`, `real_valkey: true`, `nodes_observed: 200`, `cluster_state_observed: ok`, `data_path_result: PASS`, and `valkey_versions: ["9.1.0"]`. The raw sample rows in `failover_latency_samples_200.jsonl` contain exactly three samples: `rung-200-sample-01`, `rung-200-sample-02`, and `rung-200-sample-03`; each row records `node_count: 200`, `rung: 200`, `status: PASS`, unique run/state refs, real Valkey, promotion timing, slot coverage timing, read/write recovery timing, workload impact ref, and cleanup PASS.

The combined curve artifact records rungs `[30, 50, 100, 200]` and appends the P21 200-node derived series to the P20 source series. The 200-node curve has three samples and records p50/p95/max for promotion and cluster recovery latency.

## Safety review

No host firewall, routing, PF, nftables, iptables, interface, `networksetup`, or sudo network path was introduced. The process stop path remains scoped to owned Docker/container state. `templates/configs/scale_200.yaml` keeps `default_max_nodes: 100`, `allow_1000_nodes: false`, `forbid_host_network_mutation: true`, and `dry_run: false` only for the P21 bounded exception. P14 remains non-automatic in `codex/phase_manifest.json`.

## Quantitative coverage review

`resource_preflight_200.json` records `status: PASS`, `can_run: true`, `node_count: 200`, `dry_run: false`, Docker availability, CPU, memory, disk, port checks, runtime fd limits, and previous cleanup-state checks. `events.jsonl` has 51 P21 rows and `metrics_timeseries.jsonl` has 66 P21 rows covering all three sample IDs. `quant_summary.json` count fields match the line counts and records `sample_count: 3`, `node_count: 200`, `real_valkey_claimed: true`, and `fault_runtime_claimed: true`.

`workload_impact_report.json` contains baseline, pre_event, event, recovery, post_recovery, and all_run windows for all three 200-node samples. The workload is low/nonzero at the P21 config level and nonzero in requested QPS for the fault windows; observed zero achieved QPS during one fault window is measured fault impact, not fabricated data.

## Cleanup review

Top-level `cleanup_report.json` records `status: PASS` and `resources_remaining: []`. The three nested `single_sample.stderr.log` files are empty. Each nested sample `cleanup_report.json` records `status: PASS`, `resources_remaining: []`, and explicit `cleanup_retry` provenance with the transient timeout reason where retry was used. No current stderr log contains cleanup failure output.

## Blocking findings

| ID | Severity | Finding | Required fix |
|---|---|---|---|
| None | - | No blocking findings. | - |

## Non-blocking notes

- Per-sample cleanup required retries because transient Docker process termination timed out; provenance is explicit and final residual scans are clean.
- Per-sample failover evidence includes one failed probe for the deliberately stopped primary while still proving 200 configured/probed endpoints and post-failover cluster/data-path recovery.

## Decision

Decision: PASS
