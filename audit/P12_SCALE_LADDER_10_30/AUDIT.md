# Audit — P12_SCALE_LADDER_10_30

Decision: PASS
Fresh Context: YES
Auditor: capability-refresh-reviewer
Audit Time: 2026-07-02T04:05:38.531647Z

Gate Result: artifacts/gates/P12_SCALE_LADDER_10_30/gate_result.json
Observed Gate Result SHA256: 50e1e5f09d384c631b1fd534b54cbdcbd837fc757ad33358d3b9f82cdea8e3d0

## Scope inspected

- `AGENTS.md`
- `codex/phase_manifest.json`
- `docs/codex/02_PHASES.md`
- `artifacts/gates/P12_SCALE_LADDER_10_30/gate_result.json`
- gate stdout/stderr logs
- required artifacts declared for `P12_SCALE_LADDER_10_30`
- schema validation output
- cleanup evidence
- real Valkey evidence, if required

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| harness_precheck | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/harness_precheck.log`, `artifacts/gates/P12_SCALE_LADDER_10_30/stderr/harness_precheck.log` |
| safety_static_scan | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/safety_static_scan.log`, `artifacts/gates/P12_SCALE_LADDER_10_30/stderr/safety_static_scan.log` |
| scale_tests | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/scale_tests.log`, `artifacts/gates/P12_SCALE_LADDER_10_30/stderr/scale_tests.log` |
| resource_preflight_10 | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/resource_preflight_10.log`, `artifacts/gates/P12_SCALE_LADDER_10_30/stderr/resource_preflight_10.log` |
| scale_10_real_gate | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/scale_10_real_gate.log`, `artifacts/gates/P12_SCALE_LADDER_10_30/stderr/scale_10_real_gate.log` |
| resource_preflight_30 | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/resource_preflight_30.log`, `artifacts/gates/P12_SCALE_LADDER_10_30/stderr/resource_preflight_30.log` |
| scale_30_real_gate | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/scale_30_real_gate.log`, `artifacts/gates/P12_SCALE_LADDER_10_30/stderr/scale_30_real_gate.log` |
| cleanup_report_check | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/cleanup_report_check.log`, `artifacts/gates/P12_SCALE_LADDER_10_30/stderr/cleanup_report_check.log` |

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P12_SCALE_LADDER_10_30/phase_summary.json` | `schemas/artifact/phase_summary.schema.json` | validatable-present | required=True |
| `artifacts/phases/P12_SCALE_LADDER_10_30/resource_preflight_10.json` | `schemas/artifact/resource_preflight.schema.json` | validatable-present | required=True |
| `artifacts/phases/P12_SCALE_LADDER_10_30/resource_preflight_30.json` | `schemas/artifact/resource_preflight.schema.json` | validatable-present | required=True |
| `artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_10.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | validatable-present | required=True |
| `artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | validatable-present | required=True |
| `artifacts/phases/P12_SCALE_LADDER_10_30/scale_ladder_report.json` | `schemas/artifact/scale_ladder_report.schema.json` | validatable-present | required=True |
| `artifacts/phases/P12_SCALE_LADDER_10_30/cleanup_report.json` | `schemas/artifact/cleanup_report.schema.json` | validatable-present | required=True |

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: verified by required cleanup artifacts and postcheck
- Default node cap <= 100: verified

## Real Valkey findings

Required for this phase: YES
Evidence file: artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_10.json
Valkey version observed: 9.1.0
Independent live probe: PASS

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| CML follow-up requires supplemental capability closure | medium | no | Covered by CML00-CML13, not by legacy P00-P13 audit refresh. |

## Final rationale

Fresh audit refreshed after rerunning the phase gate with the current manifest. The gate result, logs, required artifacts, cleanup evidence, and real Valkey evidence are validated by `scripts/codex_gate.py postcheck --phase P12_SCALE_LADDER_10_30` against schemas and checksums.
