# Audit - P11_STABILITY_SOAK

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-06-28T07:49:12Z

Gate Result: artifacts/gates/P11_STABILITY_SOAK/gate_result.json
Observed Gate Result SHA256: a218c55a5996bc8012bbaa4b4c3930aafc7c58fca7bbe2f7bbf4d1d378154ad5

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
- `src/valkey_scale_lab/runtime/docker_runtime.py`
- `tests/stability/test_stability_soak.py`
- `tests/integration/test_docker_runtime_contract.py`
- gate result and stdout/stderr logs under `artifacts/gates/P11_STABILITY_SOAK/`
- required and supporting artifacts under `artifacts/phases/P11_STABILITY_SOAK/`

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| harness_precheck | PASS | PASS | `artifacts/gates/P11_STABILITY_SOAK/stdout/harness_precheck.log`, SHA256 matched gate result |
| safety_static_scan | PASS | PASS | `artifacts/gates/P11_STABILITY_SOAK/stdout/safety_static_scan.log`, SHA256 matched gate result |
| stability_tests | PASS | PASS | `artifacts/gates/P11_STABILITY_SOAK/stdout/stability_tests.log`, SHA256 matched gate result |
| stability_real_gate | PASS | PASS | `artifacts/gates/P11_STABILITY_SOAK/stdout/stability_real_gate.log`, SHA256 matched gate result |
| cleanup_report_check | PASS | PASS | `artifacts/gates/P11_STABILITY_SOAK/stdout/cleanup_report_check.log`, SHA256 matched gate result |

All five command strings in `artifacts/gates/P11_STABILITY_SOAK/gate_result.json` exactly match the P11 manifest commands. Current `codex/phase_manifest.json` SHA256 is `87fa9952002f6f606dd10984fd6700d4eb577c7388cb755ece52e4688c2adad4`, matching the gate result.

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P11_STABILITY_SOAK/phase_summary.json` | `schemas/artifact/phase_summary.schema.json` | valid | schema validator PASS; status PASS |
| `artifacts/phases/P11_STABILITY_SOAK/valkey_e2e_evidence.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | valid | schema validator PASS; real Valkey evidence PASS |
| `artifacts/phases/P11_STABILITY_SOAK/stability_report.json` | `schemas/artifact/stability_report.schema.json` | valid | schema validator PASS; status PASS |
| `artifacts/phases/P11_STABILITY_SOAK/cleanup_report.json` | `schemas/artifact/cleanup_report.schema.json` | valid | schema validator PASS; cleanup assertion PASS |

Supporting artifacts inspected:

- `artifacts/phases/P11_STABILITY_SOAK/stability_metrics.jsonl` validates against `schemas/artifact/metric_sample.schema.json` and contains 18 `metric_sample` records.
- `artifacts/phases/P11_STABILITY_SOAK/stability_baseline_comparison.json` records first-run baseline status as `NO_BASELINE_YET`, with `baseline_source.status` set to `SKIPPED_WITH_REASON` and null baseline/delta values.
- `artifacts/phases/P11_STABILITY_SOAK/state_stability_soak_smoke.json` records six Docker-backed nodes on localhost ports 7000-7005 with `sandbox_network: true`.

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: verified
- Default node cap <= 100: verified

The P11 code path uses labeled Docker containers and a labeled Docker network. No host firewall, route, physical interface, or sudo default path was found in the inspected implementation. The P11 manifest max node count is 6, and non-1000 default configs remain capped at or below 100 nodes. The 1000-node profile remains opt-in dry-run only.

## Real Valkey findings

Required for this phase: YES
Evidence file: `artifacts/phases/P11_STABILITY_SOAK/valkey_e2e_evidence.json`
Valkey version observed: 9.1.0
Independent live probe: PASS, via `scripts/valkey_e2e_gate.py` evidence and gate PASS

The evidence has `real_valkey: true`, `probe_result: PASS`, `data_path_result: PASS`, `scenario: stability_soak_smoke`, `nodes_observed: 6`, `cluster_state_observed: ok`, and all observed Valkey versions start with `9.1.`.

## Stability findings

`artifacts/phases/P11_STABILITY_SOAK/stability_report.json` is PASS and records a bounded soak profile with 3 intervals, 12 operations per interval, 36 attempted operations, and 6 configured nodes. It includes periodic metrics collection, steady workload latency and error counts, restart summary with zero restart delta, leak summary by node, error classification, and a baseline comparison reference.

## Cleanup findings

`artifacts/phases/P11_STABILITY_SOAK/cleanup_report.json` is PASS with `resources_remaining: []`. An independent Docker check found no containers or networks labeled `org.valkey-scale-lab.phase=P11_STABILITY_SOAK`.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| Automatic soak duration is intentionally short for local CI bounds. | low | no | Longer soak windows should remain explicit opt-in profiles. |

## Final rationale

P11 satisfies the manifest and phase specification. The manifest gates all passed with exact command text and matching log hashes, required artifacts exist and validate, real Valkey evidence proves six Valkey 9.1.x nodes with a passing data path, stability artifacts encode bounded soak and first-run baseline semantics without fabricated baseline values, cleanup is verified both by artifact and Docker state, and the inspected implementation preserves the repository safety rules.
