# Audit - P45_CLEAN_GATE_LAYERED_DIAGNOSTICS

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-07-07T08:00:13Z

Gate Result: artifacts/gates/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/gate_result.json
Observed Gate Result SHA256: f78faa1fcd4aa7a66bb303a974a0e035b9dfc3af6b697d147a100cfdf3a2c840

## Scope inspected

- P45 stage document, context reload, design brief, worker summary, fix log, and review scope.
- P45 source, runtime, resource, schema, assertion, manifest, gate-lock, test, and artifact diffs.
- P45 gate result/logs and real Valkey artifacts for smoke plus 30/50/100/200.

## Gate findings

| Gate | Observed | Evidence |
|---|---:|---|
| safety_static_scan | PASS | `artifacts/gates/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/gate_result.json` |
| scripts_compile | PASS | `artifacts/gates/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/gate_result.json` |
| clean_gate_layered_tests | PASS | `artifacts/gates/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/stdout/clean_gate_layered_tests.log` |
| clean_gate_layered_real | PASS | `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/failover_timeline_samples.jsonl` |
| schema and semantic assertions | PASS | Clean diagnostics, layered recovery, partial coverage, no RTO conflation, and cleanup gates all passed |

## Artifact findings

P45 required artifacts are present and schema/assertion validated. The required artifact set inspected was:

| Artifact | Observed |
|---|---:|
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/phase_summary.json` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/valkey_e2e_evidence.json` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/cleanup_report.json` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/events.jsonl` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/metrics_timeseries.jsonl` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/workload_windows.json` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/quant_summary.json` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/analysis_summary.json` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/report_index.json` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/failover_timeline_samples.jsonl` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/layered_recovery_summary.json` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/client_recovery_samples.jsonl` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/observer_samples.jsonl` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/dry_run_gt_200_projection.json` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/clean_gate_diagnostics.json` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/clean_gate_probe_rounds.jsonl` | present |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/recovery_endpoint_summary.json` | present |

## Real Valkey findings

Required for this phase: YES
Evidence file: `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/valkey_e2e_evidence.json`
Valkey version observed: `9.1.0`
Observed real scales: 10, 30, 50, 100, 200

The required real 30/50/100/200 samples are PASS, `real_valkey=true`, and `execution_mode=real_valkey`. No fake/schema rows are presented as real evidence. Greater-than-200 is represented only by `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/dry_run_gt_200_projection.json`, which declares dry-run projection and no runtime resources.

## Layered recovery findings

`artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/layered_recovery_summary.json` and `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/recovery_endpoint_summary.json` preserve the source split required by P45:

- Level 1: `observer`, from `first_pfail_seen_at_ms` to `first_cluster_ok_at_ms`.
- Level 2: `client_probe`, from fault apply to first successful client SET/GET.
- Level 3: `clean_gate`, from cluster OK to final clean snapshot with clean-gate probe rounds.

`pfail_to_cluster_ok_ms` is not conflated with `kill_to_clean_snapshot_ms`; every raw sample has distinct values and source fields.

## Safety findings

No host-level network mutation or unrelated process control was found in the P45 diff. The safety scan passed. Fault/recovery behavior remains scoped to owned Docker/process resources, and cleanup remains a required gate.

## Cleanup findings

`artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/cleanup_report.json` reports PASS with no remaining resources. The cleanup assertion passed, and a Docker label scan showed no running containers for the P45 phase.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| P45 real gate captures one sample per scale | low | no | The stage requires layered endpoint coverage and semantic protection; broader repeated sampling can be added later. |
| `valkey_e2e_evidence.json` uses a compatibility scenario label from P44 | low | no | The phase ID, sample refs, assertions, and required artifacts are P45, so this is cosmetic. |

## Final rationale

All manifest gates passed, required artifacts are present and validated, real Valkey 9.1.x evidence covers 30/50/100/200, source separation matches the P45 contract, clean-gate timing is not used as Level 1 RTO, greater-than-200 remains dry-run only, cleanup passes, and no blocking safety issue was found.
