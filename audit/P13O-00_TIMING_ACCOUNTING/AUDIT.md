# Audit — P13O-00_TIMING_ACCOUNTING

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-06-29T10:10:16Z

Gate Result: artifacts/gates/P13O-00_TIMING_ACCOUNTING/gate_result.json
Observed Gate Result SHA256: 308fb4291637c367d353f2390655607efb7b042b26e793131d835f06dd11d3ce

## Scope inspected

- `AGENTS.md`
- `CODEX_START_HERE.md`
- `docs/codex/04_AUDITOR.md`
- `docs/codex/05_P13_OPTIMIZATION_LOOP.md`
- `templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md`
- `templates/audit/AUDIT_TEMPLATE.md`
- `templates/audit/audit_decision.template.json`
- `codex/p13_optimization_manifest.json`
- `codex/status/p13_optimization_state.json`
- gate result and stdout/stderr logs for `P13O-00_TIMING_ACCOUNTING`
- required P13O artifacts and P13O schemas
- P13 50/100 real Valkey evidence, state, timing, and cleanup artifacts
- relevant source/test diffs in `scripts/p13_optimization_gate.py`, `scripts/valkey_e2e_gate.py`, `src/valkey_scale_lab/runtime/docker_runtime.py`, `tests/unit/test_p13_timing_accounting.py`, and `tests/integration/test_docker_runtime_contract.py`
- protected-harness exception `artifacts/harness_exception/P13O-00_TIMING_ACCOUNTING.md`

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| p13o_timing_tests | PASS | PASS | command matched manifest; stdout/stderr SHA256 matched gate result; `2 passed in 0.01s` |
| resource_preflight_50 | PASS | PASS | command matched manifest; stdout/stderr SHA256 matched gate result |
| scale_50_real_gate | PASS | PASS | command matched manifest; stdout/stderr SHA256 matched gate result; `PASS real_valkey_e2e scenario=scale_50 nodes=50` |
| resource_preflight_100 | PASS | PASS | command matched manifest; stdout/stderr SHA256 matched gate result |
| scale_100_real_gate | PASS | PASS | command matched manifest; stdout/stderr SHA256 matched gate result; `PASS real_valkey_e2e scenario=scale_100 nodes=100` |
| cleanup_report_check | PASS | PASS | command matched manifest; stdout/stderr SHA256 matched gate result; cleanup assertion passed |
| p13o_timing_artifact_check | PASS | PASS | command matched manifest; stdout/stderr SHA256 matched gate result; P13O artifact check passed |

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| artifacts/gates/P13O-00_TIMING_ACCOUNTING/gate_result.json | schemas/artifact/p13_optimization_gate_result.schema.json | valid | repository schema validator passed |
| artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json | schemas/artifact/p13_timing_breakdown.schema.json | valid | repository schema validator passed; node_count=50; status=PASS |
| artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_100.json | schemas/artifact/p13_timing_breakdown.schema.json | valid | repository schema validator passed; node_count=100; status=PASS |
| artifacts/phases/P13O_TIMING_ACCOUNTING/phase_summary.json | schemas/artifact/p13_optimization_phase_summary.schema.json | valid | repository schema validator passed; status=PASS |
| artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_50.json | schemas/artifact/valkey_e2e_evidence.schema.json | valid | repository schema validator passed; real_valkey=true; version=9.1.0 |
| artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json | schemas/artifact/valkey_e2e_evidence.schema.json | valid | repository schema validator passed; real_valkey=true; version=9.1.0 |
| artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report.json | schemas/artifact/cleanup_report.schema.json | valid | repository schema validator passed; status=PASS |

Timing accounting fields are present and numeric for both scale artifacts: `total_gate_seconds`, `setup_command_wall_seconds`, `setup_stdout_write_seconds`, `setup_stderr_write_seconds`, `state_load_seconds`, `artifact_write_seconds`, `cleanup_command_wall_seconds`, and `unattributed_seconds`. `unattributed_seconds` is 0.000446 for scale_50 and 0.000661 for scale_100, both below the 10 second threshold. `runtime_final_full_probe` is `PASS` in both PASS artifacts; failed diagnostics are separated under `runtime_diagnostic_full_probe`.

The tightened `postcheck` path was verified against a hash baseline for `gate_result.json`, `phase_summary.json`, both timing artifacts, both Valkey evidence artifacts, and `cleanup_report.json`. `python3 scripts/p13_optimization_gate.py postcheck --phase P13O-00_TIMING_ACCOUNTING` passed, and all listed hashes were unchanged after postcheck, confirming postcheck validates artifacts read-only rather than rewriting them.

## Safety findings

- Host network mutation: absent in the relevant source/test diffs and P13O commands inspected.
- Global firewall mutation: absent in the relevant source/test diffs and P13O commands inspected.
- Sudo default path: absent in the relevant source/test diffs and P13O commands inspected.
- Cleanup logic: verified; `cleanup_report.json`, `cleanup_report_scale_50.json`, and `cleanup_report_scale_100.json` all report top-level `PASS`, and the manifest cleanup gate passed.
- Default node cap <= 100: verified; P13O manifest `default_max_nodes` is 100, P13O-00 `max_nodes` is 100, and scale configs keep `allow_1000_nodes: false`.
- P14 execution: not observed; no `P14` gate or phase artifacts exist, and base phase state stops at `P13_SCALE_LADDER_50_100`.

The protected harness exception for this phase documents the `scripts/valkey_e2e_gate.py` change as strengthening timing output and separating diagnostic probe failures from final proof timing. The source diff is consistent with that scope and does not change the recorded P13 startup strategy.

## Real Valkey findings

Required for this phase: YES
Evidence files: artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_50.json and artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json
Valkey version observed: 9.1.0
Independent live probe: PASS by wrapper evidence from `scripts/valkey_e2e_gate.py`; live endpoints were subsequently cleaned up as required.

The 50-node evidence reports `status=PASS`, `real_valkey=true`, `probe_result=PASS`, `nodes_observed=50`, `cluster_state_observed=ok`, `data_path_result=PASS`, and role counts of 25 primary / 25 replica with no handshake/fail/pfail. Every probe has `cluster_known_nodes=50`, and the final all-node snapshot has `sample_count=50`, `known_nodes=50`, 16,384 slots assigned, and zero failed slots.

The 100-node evidence reports `status=PASS`, `real_valkey=true`, `probe_result=PASS`, `nodes_observed=100`, `cluster_state_observed=ok`, `data_path_result=PASS`, and role counts of 50 primary / 50 replica with no handshake/fail/pfail. Every probe has `cluster_known_nodes=100`, and the final all-node snapshot has `sample_count=100`, `known_nodes=100`, 16,384 slots assigned, and zero failed slots.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| None | low | no | No blocking risks found in the inspected evidence. |

## Final rationale

All seven P13O manifest gates ran and passed, the gate commands match the P13O manifest, stdout/stderr hashes match the gate result, and the required artifacts exist and validate. The timing artifacts account for gate wall time and keep final full probes separate from diagnostic failures. Real Valkey evidence proves 9.1.0 clusters at 50 and 100 nodes with data-path PASS, full membership/role counts, and cleanup PASS. The tightened postcheck path validates read-only. Safety constraints and the P14 opt-in boundary remain preserved.
