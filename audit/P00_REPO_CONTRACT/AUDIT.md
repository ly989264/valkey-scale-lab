# Audit — P00_REPO_CONTRACT

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-06-28T05:19:05Z

Gate Result: artifacts/gates/P00_REPO_CONTRACT/gate_result.json
Observed Gate Result SHA256: bad91144b28fab59b6e58a2903ad71f6b5f0cf0b4248bc103eba625ec7a55e45

## Scope inspected

- `AGENTS.md`
- `CODEX_START_HERE.md`
- `codex/phase_manifest.json`
- `codex/gate_lock.json`
- `docs/codex/02_PHASES.md`
- `docs/codex/04_AUDITOR.md`
- `templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md`
- `templates/audit/AUDIT_TEMPLATE.md`
- `templates/audit/audit_decision.template.json`
- `docs/codex/CODE_REVIEW.md`
- phase source changes under `src/valkey_scale_lab/`, `tests/unit/`, `pyproject.toml`, `.github/workflows/codex-gates.yml`, `README.md`, and `docs/run_state_and_cleanup.md`
- gate result and logs under `artifacts/gates/P00_REPO_CONTRACT/`
- required artifacts `artifacts/phases/P00_REPO_CONTRACT/phase_summary.json` and `artifacts/phases/P00_REPO_CONTRACT/env_info.json`
- schemas under `schemas/**/*`, with required artifact schema validation rerun
- cleanup evidence in `docs/run_state_and_cleanup.md`
- real Valkey evidence requirement in `codex/phase_manifest.json`

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| harness_precheck | PASS | PASS | `artifacts/gates/P00_REPO_CONTRACT/stdout/harness_precheck.log`; stdout SHA256 `3591d68c686880196094ce9a19dac5431d5124dac1b48f3726d50831604ab1da`; stderr SHA256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| safety_static_scan | PASS | PASS | `artifacts/gates/P00_REPO_CONTRACT/stdout/safety_static_scan.log`; stdout SHA256 `f8fde750db39ced3e3a16fbca2feb217f0ddd15b8a1fa2e9ac507ded2231ac1b`; stderr SHA256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| schema_template_validation | PASS | PASS | `artifacts/gates/P00_REPO_CONTRACT/stdout/schema_template_validation.log`; stdout SHA256 `252d95c62ae8da2ce51898e517dafc914c942f8224e939c735e823f36ff0f1ea`; stderr SHA256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| scripts_compile | PASS | PASS | `artifacts/gates/P00_REPO_CONTRACT/stdout/scripts_compile.log`; stdout SHA256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`; stderr SHA256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| unit_tests | PASS | PASS | `artifacts/gates/P00_REPO_CONTRACT/stdout/unit_tests.log`; stdout SHA256 `a4ba6a0b833ef7026d4d291578c1a66aa7b84a732bb259d96dc88bdb89ae3418`; stderr SHA256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| cli_help | PASS | PASS | `artifacts/gates/P00_REPO_CONTRACT/stdout/cli_help.log`; stdout SHA256 `1a08b723a18016a4bda754a4f86634b01559366f249d788cbf4fd8ed5f879d69`; stderr SHA256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

The six observed gate commands in `artifacts/gates/P00_REPO_CONTRACT/gate_result.json` exactly match the six manifest commands for `P00_REPO_CONTRACT`. The gate result `manifest_sha256` matches the current `codex/phase_manifest.json` SHA256 `87fa9952002f6f606dd10984fd6700d4eb577c7388cb755ece52e4688c2adad4`.

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P00_REPO_CONTRACT/phase_summary.json` | `schemas/artifact/phase_summary.schema.json` | valid | `python3 scripts/validate_json_schema.py --schema schemas/artifact/phase_summary.schema.json --instance artifacts/phases/P00_REPO_CONTRACT/phase_summary.json` returned PASS |
| `artifacts/phases/P00_REPO_CONTRACT/env_info.json` | `schemas/artifact/env_info.schema.json` | valid | `python3 scripts/validate_json_schema.py --schema schemas/artifact/env_info.schema.json --instance artifacts/phases/P00_REPO_CONTRACT/env_info.json` returned PASS |
| `artifacts/gates/P00_REPO_CONTRACT/gate_result.json` | `schemas/artifact/gate_result.schema.json` | valid | `python3 scripts/validate_json_schema.py --schema schemas/artifact/gate_result.schema.json --instance artifacts/gates/P00_REPO_CONTRACT/gate_result.json` returned PASS |

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: verified for P00 design scope in `docs/run_state_and_cleanup.md`; P00 starts no processes, containers, workload, Valkey nodes, or fault injectors
- Default node cap <= 100: verified in `codex/phase_manifest.json` and `artifacts/phases/P00_REPO_CONTRACT/env_info.json`

## Real Valkey findings

Required for this phase: NO
Evidence file: N/A
Valkey version observed: N/A
Independent live probe: N/A

P00 is marked `fake_only_allowed: true`, `real_valkey_required: false`, and `max_nodes: 0` in `codex/phase_manifest.json`. `artifacts/phases/P00_REPO_CONTRACT/phase_summary.json` records real Valkey evidence as `SKIPPED_WITH_REASON`, and `artifacts/phases/P00_REPO_CONTRACT/env_info.json` states that P00 does not start or probe Valkey. No runtime success claim was found in the P00 source, tests, README, cleanup document, or artifacts.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| Direct `python3 -m valkey_scale_lab.cli --help` from an uninstalled src-layout checkout requires the gate runner's `PYTHONPATH=src` environment or package installation. | low | no | The manifest gate passed under `scripts/codex_gate.py`, and CI installs the project before tests. This is not a P00 gate failure but should remain visible for developer ergonomics. |

## Final rationale

The manifest gates for `P00_REPO_CONTRACT` all ran and passed, the gate result validates and has SHA256 `bad91144b28fab59b6e58a2903ad71f6b5f0cf0b4248bc103eba625ec7a55e45`, every stdout and stderr log exists with the SHA256 recorded in the gate result, and the required artifacts `artifacts/phases/P00_REPO_CONTRACT/phase_summary.json` and `artifacts/phases/P00_REPO_CONTRACT/env_info.json` exist and validate against their schemas. P00 does not require real Valkey evidence and does not claim operational runtime behavior. Safety review found no host network mutation, global firewall mutation, default sudo path, or default execution above the 100-node cap.
