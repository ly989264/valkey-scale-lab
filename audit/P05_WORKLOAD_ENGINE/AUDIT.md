# Audit — P05_WORKLOAD_ENGINE

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-06-28T06:28:52Z

Gate Result: artifacts/gates/P05_WORKLOAD_ENGINE/gate_result.json
Observed Gate Result SHA256: 9fdf4f7df9cdd6cbd298140f9d63d55be8e2831e16c96088b55b6dbb5449ccd2

## Scope inspected

- `AGENTS.md`
- `CODEX_START_HERE.md`
- `codex/phase_manifest.json`
- `docs/codex/02_PHASES.md`
- `docs/codex/04_AUDITOR.md`
- `templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md`
- `templates/audit/AUDIT_TEMPLATE.md`
- `templates/audit/audit_decision.template.json`
- `docs/codex/CODE_REVIEW.md`
- phase source changes in `src/valkey_scale_lab/runtime/docker_runtime.py`
- phase test changes in `tests/integration/test_docker_runtime_contract.py`
- gate result and logs under `artifacts/gates/P05_WORKLOAD_ENGINE/`
- required artifacts under `artifacts/phases/P05_WORKLOAD_ENGINE/`
- schema files under `schemas/`
- cleanup evidence from artifact data and Docker label queries
- real Valkey evidence from `scripts/valkey_e2e_gate.py` output and recorded probes

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| harness_precheck | PASS | PASS | `artifacts/gates/P05_WORKLOAD_ENGINE/stdout/harness_precheck.log`; command exactly matched manifest |
| safety_static_scan | PASS | PASS | `artifacts/gates/P05_WORKLOAD_ENGINE/stdout/safety_static_scan.log`; command exactly matched manifest |
| unit_and_integration_tests | PASS | PASS | `artifacts/gates/P05_WORKLOAD_ENGINE/stdout/unit_and_integration_tests.log`; command exactly matched manifest |
| real_valkey_e2e | PASS | PASS | `artifacts/gates/P05_WORKLOAD_ENGINE/stdout/real_valkey_e2e.log`; command exactly matched manifest |
| cleanup_report_check | PASS | PASS | `artifacts/gates/P05_WORKLOAD_ENGINE/stdout/cleanup_report_check.log`; command exactly matched manifest |

All stdout and stderr log files listed in `artifacts/gates/P05_WORKLOAD_ENGINE/gate_result.json` exist. Recomputed SHA256 values matched every recorded `stdout_sha256` and `stderr_sha256`.

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P05_WORKLOAD_ENGINE/phase_summary.json` | `schemas/artifact/phase_summary.schema.json` | valid | Repository validator returned PASS |
| `artifacts/phases/P05_WORKLOAD_ENGINE/valkey_e2e_evidence.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | valid | Repository validator returned PASS |
| `artifacts/phases/P05_WORKLOAD_ENGINE/cleanup_report.json` | `schemas/artifact/cleanup_report.schema.json` | valid | Repository validator returned PASS |
| `artifacts/phases/P05_WORKLOAD_ENGINE/workload_report.json` | `schemas/artifact/workload_report.schema.json` | valid | Repository validator returned PASS |

Supporting P05 artifacts inspected: `artifacts/phases/P05_WORKLOAD_ENGINE/state_workload_smoke.json`, `artifacts/phases/P05_WORKLOAD_ENGINE/workload_smoke_setup.stdout.log`, `artifacts/phases/P05_WORKLOAD_ENGINE/workload_smoke_setup.stderr.log`, `artifacts/phases/P05_WORKLOAD_ENGINE/workload_smoke_cleanup.stdout.log`, and `artifacts/phases/P05_WORKLOAD_ENGINE/workload_smoke_cleanup.stderr.log`.

`workload_report.json` includes requested QPS 120.0, achieved QPS 15.650025, p50/p95/p99 latency, 80 reads, 20 writes, uniform and hotspot workload fields, pipeline 1, keyspace 20, all-run/before-fault/during-fault/after-recovery timing windows, error classification `none`, and timeout count 0. Skipped fault/recovery windows are explicitly `SKIPPED_WITH_REASON`.

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: verified
- Default node cap <= 100: verified

The P05 source diff uses Docker containers, an owned Docker network, localhost port bindings, deterministic names, and ownership labels. The safety scan gate passed. Docker daemon checks for P05 ownership labels returned no remaining containers and no remaining networks.

## Real Valkey findings

Required for this phase: YES
Evidence file: `artifacts/phases/P05_WORKLOAD_ENGINE/valkey_e2e_evidence.json`
Valkey version observed: 9.1.0
Independent live probe: PASS

The real Valkey wrapper command was the manifest command for `scripts/valkey_e2e_gate.py` with `--min-nodes 6 --require-data-path`. Evidence records `real_valkey: true`, `probe_result: PASS`, `nodes_observed: 6`, `cluster_state_observed: ok`, `data_path_result: PASS`, and `valkey_versions: ["9.1.0"]`. Six recorded probes passed with `PING`/version/cluster information from live endpoints.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| Workload smoke achieved QPS is lower than requested QPS | low | no | Artifact reports both requested and achieved QPS honestly; P05 pass criteria require recording both, not meeting target QPS. |

## Final rationale

Decision: PASS. Fresh Context: YES. Every P05 manifest gate ran and passed with exact command text, log files and hashes matched the gate result, all required artifacts existed and validated against their schemas, real Valkey 9.1.0 evidence proved a six-node live cluster and SET/GET data path, workload metrics were present without fabricated missing values, and cleanup evidence plus Docker label checks showed no owned P05 resources remaining.
