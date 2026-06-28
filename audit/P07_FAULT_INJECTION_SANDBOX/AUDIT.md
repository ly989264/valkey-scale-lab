# Audit - P07_FAULT_INJECTION_SANDBOX

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-06-28T06:52:07Z

Gate Result: artifacts/gates/P07_FAULT_INJECTION_SANDBOX/gate_result.json
Observed Gate Result SHA256: 035c5b0b35c2ed0ec19823861a6ba2dfadc4f49809586759b528748ad39e8e85

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
- `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/gate_result.json`
- `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stdout/harness_precheck.log`
- `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stderr/harness_precheck.log`
- `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stdout/safety_static_scan.log`
- `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stderr/safety_static_scan.log`
- `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stdout/fault_unit_tests.log`
- `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stderr/fault_unit_tests.log`
- `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stdout/fault_sandbox_real_gate.log`
- `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stderr/fault_sandbox_real_gate.log`
- `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stdout/cleanup_report_check.log`
- `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stderr/cleanup_report_check.log`
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/phase_summary.json`
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/valkey_e2e_evidence.json`
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_report.json`
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/cleanup_report.json`
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_apply.json`
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_clear.json`
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_sandbox_spec.json`
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/state_fault_safety.json`
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_apply.stdout.log`
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_apply.stderr.log`
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_clear.stdout.log`
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_clear.stderr.log`
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_sandbox_setup.stdout.log`
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_sandbox_setup.stderr.log`
- `src/valkey_scale_lab/fault/sandbox.py`
- `src/valkey_scale_lab/cli.py`
- `src/valkey_scale_lab/runtime/docker_runtime.py`
- `tests/fault/test_sandbox_fault.py`
- `tests/unit/test_cli_contract.py`
- `schemas/**/*`

## Gate findings

| Gate | Expected command | Observed | Evidence |
|---|---|---:|---|
| harness_precheck | `python3 scripts/codex_gate.py precheck --phase P07_FAULT_INJECTION_SANDBOX` | PASS, exit 0 | `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stdout/harness_precheck.log`; SHA256 matched `3591d68c686880196094ce9a19dac5431d5124dac1b48f3726d50831604ab1da`; stderr matched empty SHA |
| safety_static_scan | `python3 scripts/safety_scan.py` | PASS, exit 0 | `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stdout/safety_static_scan.log`; SHA256 matched `f8fde750db39ced3e3a16fbca2feb217f0ddd15b8a1fa2e9ac507ded2231ac1b`; stderr matched empty SHA |
| fault_unit_tests | `python3 -m pytest -q tests/unit tests/fault tests/integration` | PASS, exit 0 | `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stdout/fault_unit_tests.log`; SHA256 matched `ca996134af7c8ce7ed728b3fc5922c9e82c4add5cae159cc2a6da9397dc609b4`; stderr matched empty SHA |
| fault_sandbox_real_gate | `python3 scripts/fault_safety_gate.py --phase P07_FAULT_INJECTION_SANDBOX --config templates/configs/local_az_3x2.yaml --out artifacts/phases/P07_FAULT_INJECTION_SANDBOX/valkey_e2e_evidence.json --fault-report artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_report.json` | PASS, exit 0 | `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stdout/fault_sandbox_real_gate.log`; SHA256 matched `1b484d098bcbb2ef1cdb9eef1036a135a928eea6193cce07e47ffbdad3ffdaf0`; stderr matched empty SHA |
| cleanup_report_check | `python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P07_FAULT_INJECTION_SANDBOX/cleanup_report.json` | PASS, exit 0 | `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/stdout/cleanup_report_check.log`; SHA256 matched `462c086cb13ec5fdbaa52f1afea579274bacb60d133047d4d1e2199f03bf815b`; stderr matched empty SHA |

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/phase_summary.json` | `schemas/artifact/phase_summary.schema.json` | valid | `python3 scripts/validate_json_schema.py --schema schemas/artifact/phase_summary.schema.json --instance artifacts/phases/P07_FAULT_INJECTION_SANDBOX/phase_summary.json` returned PASS |
| `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/valkey_e2e_evidence.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | valid | `python3 scripts/validate_json_schema.py --schema schemas/artifact/valkey_e2e_evidence.schema.json --instance artifacts/phases/P07_FAULT_INJECTION_SANDBOX/valkey_e2e_evidence.json` returned PASS |
| `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_report.json` | `schemas/artifact/fault_report.schema.json` | valid | `python3 scripts/validate_json_schema.py --schema schemas/artifact/fault_report.schema.json --instance artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_report.json` returned PASS |
| `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/cleanup_report.json` | `schemas/artifact/cleanup_report.schema.json` | valid | `python3 scripts/validate_json_schema.py --schema schemas/artifact/cleanup_report.schema.json --instance artifacts/phases/P07_FAULT_INJECTION_SANDBOX/cleanup_report.json` returned PASS |
| `artifacts/gates/P07_FAULT_INJECTION_SANDBOX/gate_result.json` | `schemas/artifact/gate_result.schema.json` | valid | `python3 scripts/validate_json_schema.py --schema schemas/artifact/gate_result.schema.json --instance artifacts/gates/P07_FAULT_INJECTION_SANDBOX/gate_result.json` returned PASS |

## Fault Lifecycle Findings

- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_sandbox_spec.json` defines fault `fault-sandbox-smoke`, type `network_delay`, scope `container_namespace_or_sandbox_proxy`, AZ target selector `az-a`, delay 50 ms, duration 3 seconds, and `forbid_host_network_mutation: true`.
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_apply.json` records status PASS, target `shard-0000-primary`, scope `container_namespace_or_sandbox_proxy`, and safety checks with host network and global firewall mutation false.
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_clear.json` records status PASS, `cleared: true`, and safety checks with host network and global firewall mutation false.
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_report.json` records fault scope, target logical id, start/end timestamps, expected impact, observed impact as `SKIPPED_WITH_REASON`, apply status PASS, clear status PASS, and safety checks.
- `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_state_fault-sandbox-smoke.json` was absent during audit after clear, matching the cleared lifecycle.

## Safety findings

- Host network mutation: absent in P07 source inspection and `python3 scripts/safety_scan.py` returned PASS.
- Global firewall mutation: absent in P07 source inspection and `python3 scripts/safety_scan.py` returned PASS.
- Sudo default path: absent in P07 source inspection and safety scan returned PASS.
- Banned host network commands in P07 source without sandbox marker: absent.
- Cleanup logic: verified by `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/cleanup_report.json`, `scripts/assert_cleanup.py`, absent fault state file, and Docker daemon check showing no `vslab-p07` containers or networks.
- Default node cap <= 100: verified; manifest `max_nodes` is 6 for P07 and the state/evidence show 6 nodes.

## Real Valkey findings

Required for this phase: YES
Evidence file: `artifacts/phases/P07_FAULT_INJECTION_SANDBOX/valkey_e2e_evidence.json`
Valkey version observed: `9.1.0`
Independent live probe: PASS

The real-gate wrapper `scripts/fault_safety_gate.py` starts the scenario through the project CLI, independently loads endpoints from `state_fault_safety.json`, waits for cluster OK before the fault, applies and clears the fault through the CLI, then waits for cluster OK after clear. The evidence file records `real_valkey: true`, `probe_result: PASS`, `nodes_observed: 6`, `cluster_state_observed: ok`, six PASS probes, PING responses, cluster known nodes of 6, and all probe versions as `9.1.0`.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| P07 uses the explicit sandbox proxy fallback path for the network-delay lifecycle proof; the observed fault impact is recorded as `SKIPPED_WITH_REASON` rather than a measured latency/loss effect. | low | no | This is acceptable for P07 because the manifest permits a sandbox proxy fallback, the fault lifecycle is recorded, and the real wrapper verifies post-clear Valkey cluster health. Later phases should add platform-specific impairment measurements if required. |

## Final rationale

All five manifest gates ran with exact command text and passed. All referenced stdout/stderr files exist and their SHA256 values match `gate_result.json`. Required P07 artifacts exist and validate against their schemas using the repository validator. Real Valkey evidence was produced by the pre-authored fault safety wrapper and proves live Valkey `9.1.0` endpoints with post-clear cluster state `ok`. Fault apply/clear state was cleared, cleanup is PASS with `resources_remaining: []`, and a Docker daemon check found no matching P07 owned containers or networks. No host-level network or firewall mutation path was found.
