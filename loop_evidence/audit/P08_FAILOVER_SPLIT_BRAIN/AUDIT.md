# Audit — P08_FAILOVER_SPLIT_BRAIN

Decision: PASS
Fresh Context: YES
Auditor: capability-refresh-reviewer
Audit Time: 2026-07-02T04:02:34.655705Z

Gate Result: artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/gate_result.json
Observed Gate Result SHA256: eaaa00b4dec6251627efe977acdc49e4c75bdcb4d1ea457530aadaa04a1224ff

## Scope inspected

- `AGENTS.md`
- `codex/phase_manifest.json`
- `docs/codex/02_PHASES.md`
- `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/gate_result.json`
- gate stdout/stderr logs
- required artifacts declared for `P08_FAILOVER_SPLIT_BRAIN`
- schema validation output
- cleanup evidence
- real Valkey evidence, if required

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| harness_precheck | PASS | PASS | `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/harness_precheck.log`, `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stderr/harness_precheck.log` |
| safety_static_scan | PASS | PASS | `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/safety_static_scan.log`, `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stderr/safety_static_scan.log` |
| failover_unit_tests | PASS | PASS | `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/failover_unit_tests.log`, `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stderr/failover_unit_tests.log` |
| primary_stop_failover_real_gate | PASS | PASS | `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/primary_stop_failover_real_gate.log`, `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stderr/primary_stop_failover_real_gate.log` |
| cleanup_report_check | PASS | PASS | `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/cleanup_report_check.log`, `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stderr/cleanup_report_check.log` |

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/phase_summary.json` | `schemas/artifact/phase_summary.schema.json` | validatable-present | required=True |
| `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/valkey_e2e_evidence.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | validatable-present | required=True |
| `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/failover_report.json` | `schemas/artifact/failover_report.schema.json` | validatable-present | required=True |
| `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/cleanup_report.json` | `schemas/artifact/cleanup_report.schema.json` | validatable-present | required=True |

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: verified by required cleanup artifacts and postcheck
- Default node cap <= 100: verified

## Real Valkey findings

Required for this phase: YES
Evidence file: artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/valkey_e2e_evidence.json
Valkey version observed: 9.1.0
Independent live probe: PASS

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| CML follow-up requires supplemental capability closure | medium | no | Covered by CML00-CML13, not by legacy P00-P13 audit refresh. |

## Final rationale

Fresh audit refreshed after rerunning the phase gate with the current manifest. The gate result, logs, required artifacts, cleanup evidence, and real Valkey evidence are validated by `scripts/codex_gate.py postcheck --phase P08_FAILOVER_SPLIT_BRAIN` against schemas and checksums.
