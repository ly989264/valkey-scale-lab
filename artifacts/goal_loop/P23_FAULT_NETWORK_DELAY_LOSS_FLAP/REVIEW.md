# REVIEW — P23_FAULT_NETWORK_DELAY_LOSS_FLAP

## Scope reviewed

- Fresh-context review of P23 only.
- Read controlling docs: `AGENTS.md`, `CODEX_START_HERE.md`, `CODEX_GOAL_LOOP_START.md`, `docs/codex/04_AUDITOR.md`, goal-loop docs `00_INDEX.md` through `10_AUDIT_AND_COMMIT_POLICY.md`, `docs/codex/goal-loop/stages/P23_FAULT_NETWORK_DELAY_LOSS_FLAP.md`, `templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md`, and audit/review templates.
- Inspected P23 git diff, manifest entry, gate result/logs, phase artifacts, schema validation, real Valkey evidence, safety surface, cleanup reports, and P24 scope boundary.

## Documents and artifacts read

- Handoff artifacts: `artifacts/goal_loop/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/CONTEXT_RELOAD.md`, `DESIGN_BRIEF.md`, and `WORKER_SUMMARY.md`.
- Gate result: `artifacts/gates/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/gate_result.json`.
- Gate result SHA256: `7e01fd2ef415e29e3ab3215b57ccec7d38b2381142c4a161c60ed1ad04067e2a`.
- Required artifacts cited and inspected:
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

## Diff review

P23 diff is limited to the sandbox proxy implementation, P23 controller/assertion hardening, bounded P23 configs, tests, and gate lock hash refreshes. The runtime admits `p23_fault_matrix_(6|10|30|50|100)` and rejects 200-node P23 scenarios. No implementation deliverable for P24 partition, minority/majority, or split-brain rows was added for P23.

## Gate review

| Gate/check | Evidence | Result |
|---|---|---:|
| Manifest command match | `gate_result.json` commands exactly match `codex/phase_manifest.json` P23 gates | PASS |
| Gate log SHA256 verification | All stdout/stderr hashes in `gate_result.json` matched files under `artifacts/gates/P23_FAULT_NETWORK_DELAY_LOSS_FLAP/` | PASS |
| Harness precheck | `stdout/harness_precheck.log` | PASS |
| Safety scan | `stdout/safety_static_scan.log` | PASS |
| Compile | `stdout/scripts_compile.log` | PASS |
| Unit/integration tests | `stdout/unit_integration_tests.log`, 119 passed | PASS |
| Goal-loop assertion | `stdout/goal_loop_stage_assertion.log` | PASS |
| Real fault safety gate | `stdout/real_fault_safety_gate.log` | PASS |
| Quant assertion | `stdout/quant_artifact_assertion.log`; rerun focused check passed | PASS |
| Fault matrix assertion | `stdout/fault_matrix_assertion.log`; rerun focused check passed | PASS |
| Workload impact assertion | `stdout/workload_impact_assertion.log`; rerun focused check passed | PASS |
| Cleanup assertion | `stdout/cleanup_report_check.log` | PASS |

## Artifact/schema review

All manifest-required P23 artifacts exist and passed focused validation with `scripts/validate_json_schema.py` against their declared schemas, including line-by-line JSONL validation. `quant_summary.json` reports 102 events, 156 metrics, 6 fault rows, 12 command log rows, and 6 samples; these counts match the inspected files.

## Real Valkey evidence review

`valkey_e2e_evidence.json` reports `status=PASS`, `real_valkey=true`, `nodes_observed=10`, `cluster_state_observed=ok`, `data_path_result=PASS`, and `valkey_versions=["9.1.0"]`. The fault rows cover exactly six PASS rows: `network_delay`, `network_loss`, and `network_flap` at 6 and 10 nodes.

## Safety review

Implementation path is `sandbox_proxy` for all P23 rows. Source and command-log review found no host `iptables`, `nft`, `pfctl`, global route mutation, host interface mutation, or sudo network manipulation in the P23 path. `network_fault_command_log.jsonl` contains apply/clear rows with `host_network_mutated=false`, and artifact rows also record `physical_host_mutated=false`, `safety_scope_verified=true`, and `cleanup_verified=true`.

## Quantitative coverage review

Each required row records fault parameters and observed effects: delay rows have delay/jitter/direction/duration and proxy delay counters; loss rows have loss/correlation/direction/duration and dropped connection counters; flap rows have up/down cadence/iterations/duration and flap rejection counters. Workload impact includes baseline, pre_event, event, recovery, post_recovery, and all_run windows for every sample, with comparisons for QPS ratio, p99 delta, error-rate delta, recovery duration, and post-recovery QPS ratio. Missing p999 values are encoded as `MISSING` with reasons.

## Cleanup review

Aggregate cleanup is `PASS` in `cleanup_report.json`, with `resources_remaining=[]`. Both subrun cleanup reports for 6 and 10 nodes are `PASS` with no resources remaining. A focused Docker label check for P23-owned containers returned no running or stopped containers.

## Blocking findings

| ID | Severity | Finding | Required fix |
|---|---|---|---|
| None | - | No blocking findings. | - |

## Non-blocking notes

- P23 uses the portable `sandbox_proxy` path and leaves `container_netns_tc` unimplemented/untested, which is acceptable for this stage because `sandbox_proxy` is an allowed safe implementation path.
- The proxy targets a selected slot owner rather than all cluster traffic; artifacts record this scope and assertions verify observed impairment for the target path.

## Decision

Decision: PASS
