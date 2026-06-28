# Audit — P13_SCALE_LADDER_50_100

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-06-28T16:26:43Z

Gate Result: artifacts/gates/P13_SCALE_LADDER_50_100/gate_result.json
Observed Gate Result SHA256: 12b755de65c8e845ccba3aae89d8a3851a1230a590696b2a1337620a02eb1a64

## Scope inspected

- `AGENTS.md`
- `CODEX_START_HERE.md`
- `docs/codex/04_AUDITOR.md`
- `templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md`
- `codex/phase_manifest.json`
- `docs/codex/02_PHASES.md`
- `templates/audit/AUDIT_TEMPLATE.md`
- `templates/audit/audit_decision.template.json`
- phase source changes in `src/valkey_scale_lab/runtime/docker_runtime.py`
- harness changes in `scripts/valkey_e2e_gate.py`, `scripts/valkey_probe_lib.py`, and `codex/gate_lock.json`
- harness exception `artifacts/harness_exception/P13_SCALE_LADDER_50_100.md`
- phase test changes in `tests/integration/test_docker_runtime_contract.py` and `tests/unit/test_valkey_probe_lib.py`
- gate result and stdout/stderr logs under `artifacts/gates/P13_SCALE_LADDER_50_100/`
- required artifacts under `artifacts/phases/P13_SCALE_LADDER_50_100/`
- schema validation output
- cleanup evidence
- real Valkey evidence

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| harness_precheck | PASS | PASS | `artifacts/gates/P13_SCALE_LADDER_50_100/stdout/harness_precheck.log` |
| safety_static_scan | PASS | PASS | `artifacts/gates/P13_SCALE_LADDER_50_100/stdout/safety_static_scan.log` |
| scale_tests | PASS | PASS | `artifacts/gates/P13_SCALE_LADDER_50_100/stdout/scale_tests.log` |
| resource_preflight_50 | PASS | PASS | `artifacts/phases/P13_SCALE_LADDER_50_100/resource_preflight_50.json` |
| scale_50_real_gate | PASS | PASS | `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_50.json` |
| resource_preflight_100 | PASS | PASS | `artifacts/phases/P13_SCALE_LADDER_50_100/resource_preflight_100.json` |
| scale_100_real_gate | PASS | PASS | `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json` |
| cleanup_report_check | PASS | PASS | `artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report.json` |

The command text in `gate_result.json` exactly matches the P13 manifest entry. All stdout/stderr files exist and their SHA256 values match `gate_result.json`. The recorded manifest SHA256 also matches `codex/phase_manifest.json`.

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P13_SCALE_LADDER_50_100/phase_summary.json` | `schemas/artifact/phase_summary.schema.json` | valid | Required artifact exists and validates. |
| `artifacts/phases/P13_SCALE_LADDER_50_100/resource_preflight_50.json` | `schemas/artifact/resource_preflight.schema.json` | valid | Required artifact exists and validates; status PASS, can_run true, node_count 50. |
| `artifacts/phases/P13_SCALE_LADDER_50_100/resource_preflight_100.json` | `schemas/artifact/resource_preflight.schema.json` | valid | Required artifact exists and validates; status PASS, can_run true, node_count 100. |
| `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_50.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | valid | Required artifact exists and validates; 50 passing probes, nodes_observed 50. |
| `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | valid | Required artifact exists and validates; 100 passing probes, nodes_observed 100. |
| `artifacts/phases/P13_SCALE_LADDER_50_100/scale_ladder_report.json` | `schemas/artifact/scale_ladder_report.schema.json` | valid | Required artifact exists and validates; rungs PASS for 50 and 100 with max_nodes_observed 100. |
| `artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report.json` | `schemas/artifact/cleanup_report.schema.json` | valid | Required artifact exists and validates; status PASS and resources_remaining is empty. |

Additional cleanup evidence `artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report_scale_50.json` and `artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report_scale_100.json` also validates against `schemas/artifact/cleanup_report.schema.json`.

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: verified
- Default node cap <= 100: verified
- P14 execution: absent; no P14 gate or phase artifact directory is present

`templates/configs/scale_50.yaml` and `templates/configs/scale_100.yaml` both set `default_max_nodes: 100`, `allow_1000_nodes: false`, `require_sandbox_network: true`, and `forbid_host_network_mutation: true`. The P13 manifest max_nodes is 100. P14 is non-automatic and gated by explicit 1000-node opt-in.

The harness exception was reviewed. It cites a membership-guard defect where fragmented smaller clusters could previously satisfy the scale proof. The patch strengthens the gate by requiring each counted endpoint to report full membership, connected cluster links, no fail/handshake/noaddr flags, and expected primary/replica counts; `codex/gate_lock.json` records SHA256 values that match the modified `scripts/valkey_e2e_gate.py` and `scripts/valkey_probe_lib.py`.

## Real Valkey findings

Required for this phase: YES
Evidence files: `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_50.json`, `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json`
Valkey version observed: 9.1.0
Independent live probe: PASS

The 50-node evidence reports `real_valkey: true`, `probe_result: PASS`, `data_path_result: PASS`, Valkey version `9.1.0`, 50 passing probes, `cluster_known_nodes` min/max 50/50, 50 `CLUSTER NODES` entries per probe, and role counts of 25 primaries and 25 replicas with no handshake/fail/pfail entries.

The 100-node evidence reports `real_valkey: true`, `probe_result: PASS`, `data_path_result: PASS`, Valkey version `9.1.0`, 100 passing probes, `cluster_known_nodes` min/max 100/100, 100 `CLUSTER NODES` entries per probe, and role counts of 50 primaries and 50 replicas with no handshake/fail/pfail entries.

Both runs record Docker-contained process runtime evidence with `sandbox_network: true`, three nodehost containers, and the expected logical process counts. Final cluster snapshots for both rungs show `cluster_state: ok`, full slot coverage, expected role counts, and no fail indicators.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| None identified from inspected evidence. | low | no | P13 completes the automatic phase ceiling; P14 remains explicit opt-in only. |

## Final rationale

All manifest gates ran and passed, the gate command text matches the manifest, stdout/stderr log files exist with matching SHA256 values, required artifacts exist, and required artifacts validate against their schemas. The real Valkey evidence proves live Valkey 9.1.0 clusters at 50 and 100 nodes with full cluster membership, data-path success, clean role counts, and Docker-sandboxed runtime metadata. Safety constraints and cleanup evidence are acceptable, including empty owned resource leftovers. Decision: PASS.
