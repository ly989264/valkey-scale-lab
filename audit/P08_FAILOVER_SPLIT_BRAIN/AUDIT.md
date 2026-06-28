# Audit - P08_FAILOVER_SPLIT_BRAIN

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-06-28T07:08:23Z

Gate Result: artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/gate_result.json
Observed Gate Result SHA256: 77822b533cd46c5296c7b93fd29b6a3aa315993efce9327f1504f84abb773654

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
- `schemas/artifact/phase_summary.schema.json`
- `schemas/artifact/valkey_e2e_evidence.schema.json`
- `schemas/artifact/failover_report.schema.json`
- `schemas/artifact/cleanup_report.schema.json`
- `schemas/artifact/gate_result.schema.json`
- `schemas/artifact/audit_decision.schema.json`
- `schemas/artifact/fault_report.schema.json`
- `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/gate_result.json`
- `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/harness_precheck.log`
- `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stderr/harness_precheck.log`
- `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/safety_static_scan.log`
- `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stderr/safety_static_scan.log`
- `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/failover_unit_tests.log`
- `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stderr/failover_unit_tests.log`
- `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/primary_stop_failover_real_gate.log`
- `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stderr/primary_stop_failover_real_gate.log`
- `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/cleanup_report_check.log`
- `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stderr/cleanup_report_check.log`
- `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/phase_summary.json`
- `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/valkey_e2e_evidence.json`
- `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/failover_report.json`
- `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/cleanup_report.json`
- `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/state_failover.json`
- `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/fault_primary_stop_spec.json`
- `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/fault_apply.json`
- `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/fault_report.json`
- `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/failover_setup.stdout.log`
- `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/failover_setup.stderr.log`
- `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/failover_fault_apply.stdout.log`
- `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/failover_fault_apply.stderr.log`
- `scripts/fault_failover_gate.py`
- `src/valkey_scale_lab/fault/sandbox.py`
- `src/valkey_scale_lab/runtime/docker_runtime.py`
- `tests/failover/test_failover_contract.py`
- `tests/fault/test_sandbox_fault.py`
- `tests/integration/test_docker_runtime_contract.py`

## Gate findings

| Gate | Expected command | Observed | Evidence |
|---|---|---:|---|
| harness_precheck | `python3 scripts/codex_gate.py precheck --phase P08_FAILOVER_SPLIT_BRAIN` | PASS | `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/harness_precheck.log`, stderr hash verified |
| safety_static_scan | `python3 scripts/safety_scan.py` | PASS | `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/safety_static_scan.log`, stderr hash verified |
| failover_unit_tests | `python3 -m pytest -q tests/unit tests/fault tests/failover tests/integration` | PASS | `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/failover_unit_tests.log`, stderr hash verified |
| primary_stop_failover_real_gate | `python3 scripts/fault_failover_gate.py --phase P08_FAILOVER_SPLIT_BRAIN --config templates/configs/single_mac_6node.yaml --out artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/valkey_e2e_evidence.json --failover-report artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/failover_report.json` | PASS | `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/primary_stop_failover_real_gate.log`, stderr hash verified |
| cleanup_report_check | `python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/cleanup_report.json` | PASS | `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/stdout/cleanup_report_check.log`, stderr hash verified |

All stdout and stderr files named in `gate_result.json` exist. Recomputed SHA256 values match the recorded values for all five gates.

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/phase_summary.json` | `schemas/artifact/phase_summary.schema.json` | valid | Required artifact exists and schema validation passed. |
| `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/valkey_e2e_evidence.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | valid | Required artifact exists and schema validation passed. |
| `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/failover_report.json` | `schemas/artifact/failover_report.schema.json` | valid | Required artifact exists and schema validation passed. |
| `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/cleanup_report.json` | `schemas/artifact/cleanup_report.schema.json` | valid | Required artifact exists and schema validation passed. |
| `artifacts/gates/P08_FAILOVER_SPLIT_BRAIN/gate_result.json` | `schemas/artifact/gate_result.schema.json` | valid | Gate result schema validation passed. |
| `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/fault_report.json` | `schemas/artifact/fault_report.schema.json` | valid | Supporting fault evidence validates against schema. |

Supporting P08 artifacts inspected: `state_failover.json`, `fault_primary_stop_spec.json`, `fault_apply.json`, `failover_setup.stdout.log`, `failover_setup.stderr.log`, `failover_fault_apply.stdout.log`, and `failover_fault_apply.stderr.log`.

## Real Valkey findings

Required for this phase: YES
Evidence file: `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/valkey_e2e_evidence.json`
Valkey version observed: `9.1.0`
Independent live probe: PASS

The real gate was `scripts/fault_failover_gate.py`, as required by AGENTS.md for failover scenarios. Evidence records `real_valkey: true`, `probe_result: PASS`, `valkey_version_prefix_required: 9.1.`, `valkey_versions: ["9.1.0"]`, `nodes_observed: 5`, and `cluster_state_observed: ok`. The probe list shows five successful live endpoint probes with `PING` responses and Valkey 9.1.0 after the selected primary endpoint refused connection, which is consistent with a stopped primary.

## Failover and split-brain findings

- Selected primary stopped: `shard-0000-primary`.
- Old primary node ID: `e2126f4f1543a8f06b6f429a5647ce7b344bef4e`.
- Promoted node ID: `e9ab2ea9eefb4276749c1f44ed32fc65dc3fe622`.
- Failover latency: `408.125` ms.
- Split-brain duration: encoded as `{ "value": null, "status": "MISSING", "reason": "not_measured_by_primary_stop_gate" }`; no fabricated split-brain duration was found.

`failover_report.json` and `valkey_e2e_evidence.json` agree on old primary ID, promoted node ID, selected primary logical ID, and failover latency.

## Fault and cleanup findings

- `fault_primary_stop_spec.json` requested `node_stop` with `scope: owned_container_or_process` and `forbid_host_network_mutation: true`.
- `fault_apply.json` records `status: PASS`, `fault_type: node_stop`, `scope: owned_container_or_process`, and state path `artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/fault_state_fault-primary-stop.json`.
- `fault_report.json` records observed impact `action: container_stop` for container `vslab-p08-failover-split-brain-failover-setup-20260628-shard-0000-primary`, matching the selected node in `state_failover.json`.
- The fault state file is absent after cleanup, and `cleanup_report.json` records removal of `fault_state_fault-primary-stop.json`.
- `cleanup_report.json` is `PASS` with `resources_remaining: []`.
- Docker was available during audit; label-filtered `docker ps -a` and `docker network ls` checks for P08 owned resources returned no containers and no networks.

## Safety findings

- Host network mutation: absent.
- Global firewall mutation: absent.
- Sudo default path: absent.
- Cleanup logic: verified.
- Default node cap <= 100: verified. Manifest has `default_max_nodes: 100`; P08 has `max_nodes: 6`; P14 1000-node behavior remains non-automatic opt-in dry-run only.

The inspected P08 diff uses Docker container stop through `valkey_scale_lab.cli fault apply` and cleanup by deterministic project labels. No default `sudo`, host route, host firewall, host interface, or global network mutation path was found in the P08 implementation evidence.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| Minority/majority partition duration is not measured by the primary-stop gate. | low | no | The metric is explicitly encoded as `MISSING` with reason, satisfying P08 artifact discipline and avoiding fabricated split-brain duration. |

## Final rationale

Decision: PASS. The current P08 gate result is PASS, every manifest gate ran with exact command text, all stdout/stderr hashes match, required artifacts exist and validate, real Valkey 9.1.0 evidence proves post-fault cluster health, failover facts agree across evidence artifacts, the selected primary was stopped through the project fault API, cleanup cleared fault state and left no owned resources, and no safety rule violation was found.
