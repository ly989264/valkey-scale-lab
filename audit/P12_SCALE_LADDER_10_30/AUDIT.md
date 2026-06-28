# Audit - P12_SCALE_LADDER_10_30

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-06-28T08:08:57Z

Gate Result: artifacts/gates/P12_SCALE_LADDER_10_30/gate_result.json
Observed Gate Result SHA256: 843f65f17da7481357eb7fa683780d59c724a3f4c35141474bb82af8896f73dc

## Scope inspected

- `AGENTS.md`
- `CODEX_START_HERE.md`
- `codex/phase_manifest.json`
- `docs/codex/02_PHASES.md`
- `docs/codex/07_SCALE_POLICY.md`
- `docs/codex/04_AUDITOR.md`
- `templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md`
- `templates/audit/AUDIT_TEMPLATE.md`
- `templates/audit/audit_decision.template.json`
- `docs/codex/CODE_REVIEW.md`
- phase source changes in `src/valkey_scale_lab/resource.py`, `src/valkey_scale_lab/cli.py`, `src/valkey_scale_lab/runtime/docker_runtime.py`
- phase tests in `tests/scale/test_scale_ladder.py`, `tests/integration/test_docker_runtime_contract.py`, `tests/unit/test_cli_contract.py`
- gate result and stdout/stderr logs under `artifacts/gates/P12_SCALE_LADDER_10_30/`
- required and supporting artifacts under `artifacts/phases/P12_SCALE_LADDER_10_30/`
- artifact schemas under `schemas/artifact/`

## Gate findings

All eight manifest gates are present in gate-result order, have status PASS, exit code 0, exact command text matching `codex/phase_manifest.json`, and matching stdout/stderr SHA256 values. The gate result manifest hash also matches the current `codex/phase_manifest.json` SHA256 `87fa9952002f6f606dd10984fd6700d4eb577c7388cb755ece52e4688c2adad4`.

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| harness_precheck | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/harness_precheck.log` |
| safety_static_scan | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/safety_static_scan.log` |
| scale_tests | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/scale_tests.log` |
| resource_preflight_10 | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/resource_preflight_10.log` |
| scale_10_real_gate | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/scale_10_real_gate.log` |
| resource_preflight_30 | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/resource_preflight_30.log` |
| scale_30_real_gate | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/scale_30_real_gate.log` |
| cleanup_report_check | PASS | PASS | `artifacts/gates/P12_SCALE_LADDER_10_30/stdout/cleanup_report_check.log` |

## Artifact findings

Each required artifact exists and validates with `scripts/validate_json_schema.py --schema <schema> --instance <artifact>`.

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P12_SCALE_LADDER_10_30/phase_summary.json` | `schemas/artifact/phase_summary.schema.json` | valid | status PASS |
| `artifacts/phases/P12_SCALE_LADDER_10_30/resource_preflight_10.json` | `schemas/artifact/resource_preflight.schema.json` | valid | status PASS, can_run true, 10 nodes |
| `artifacts/phases/P12_SCALE_LADDER_10_30/resource_preflight_30.json` | `schemas/artifact/resource_preflight.schema.json` | valid | status PASS, can_run true, 30 nodes |
| `artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_10.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | valid | real Valkey PASS, 10 probes |
| `artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | valid | real Valkey PASS, 30 probes |
| `artifacts/phases/P12_SCALE_LADDER_10_30/scale_ladder_report.json` | `schemas/artifact/scale_ladder_report.schema.json` | valid | status PASS, rungs 10 and 30 |
| `artifacts/phases/P12_SCALE_LADDER_10_30/cleanup_report.json` | `schemas/artifact/cleanup_report.schema.json` | valid | status PASS, resources_remaining empty |

Supporting artifacts inspected: `scale_rung_10.json`, `scale_rung_30.json`, `state_scale_10.json`, and `state_scale_30.json`. The scale report contains both rung summaries, per-rung metrics, per-rung management summaries, and a PASS comparison from 10 to 30 nodes.

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: verified
- Default node cap <= 100: verified
- P14/1000-node default execution: absent

`scripts/safety_scan.py` passed. Source inspection found Docker-only network creation/removal scoped by `org.valkey-scale-lab.*` labels, no host route/firewall/interface mutation, and no sudo path. P12 configs define 10 and 30 nodes with `allow_1000_nodes: false`; the 1000-node profile remains opt-in dry-run guarded by `VSLAB_ALLOW_1000_DRYRUN`.

## Real Valkey findings

Required for this phase: YES
Evidence files:

- `artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_10.json`
- `artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json`

Valkey version observed: 9.1.0
Independent live probe: PASS

The e2e wrapper uses `scripts/valkey_e2e_gate.py`, starts the CLI scenario, reads `state_scale_10.json` and `state_scale_30.json`, probes live `127.0.0.1` endpoints with RESP, verifies cluster state, checks the `9.1.` version prefix, runs required SET/GET data-path proof, and invokes cleanup. Observed evidence has `real_valkey: true`, `probe_result: PASS`, `data_path_result: PASS`, `cluster_state_observed: ok`, `nodes_observed` 10 and 30 respectively, and all probe versions `9.1.0`.

## Cleanup findings

`cleanup_report.json` is PASS with `resources_remaining: []`. The 30-node cleanup report records 61 cleanup actions for 30 containers plus the owned Docker network. External Docker checks for P12-owned resources returned no containers and no networks:

- `docker ps -a --filter label=org.valkey-scale-lab.project=valkey-scale-lab --filter label=org.valkey-scale-lab.phase=P12_SCALE_LADDER_10_30`
- `docker network ls --filter label=org.valkey-scale-lab.project=valkey-scale-lab --filter label=org.valkey-scale-lab.phase=P12_SCALE_LADDER_10_30`

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| Single-host Docker resource limits may vary by machine. | low | no | Resource preflight is present and fails closed for P12/P13 scale rungs. |

## Final rationale

PASS. The current P12 implementation and artifacts satisfy the manifest and phase text: real 10-node and 30-node Valkey gates passed with independent evidence, resource preflight reports are PASS/can_run true and fail closed, the ladder report compares both rungs with metrics and management summaries, cleanup is verified by artifact and Docker label checks, and safety policy constraints are preserved.
