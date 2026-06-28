# Audit — P01_CONFIG_SCHEMA

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-06-28T05:30:54Z

Gate Result: artifacts/gates/P01_CONFIG_SCHEMA/gate_result.json
Observed Gate Result SHA256: 4920c0f8ec397484714a41a3e04e4137c65ea9606e0e2896b9db0b6557402825

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
- `artifacts/gates/P01_CONFIG_SCHEMA/gate_result.json`
- `artifacts/gates/P01_CONFIG_SCHEMA/stdout/*.log`
- `artifacts/gates/P01_CONFIG_SCHEMA/stderr/*.log`
- `artifacts/phases/P01_CONFIG_SCHEMA/phase_summary.json`
- `artifacts/phases/P01_CONFIG_SCHEMA/config_validation_report.json`
- `artifacts/phases/P01_CONFIG_SCHEMA/config_validation_multi_az_report.json`
- `artifacts/phases/P01_CONFIG_SCHEMA/config_schema_report.json`
- `artifacts/phases/P01_CONFIG_SCHEMA/config_validation_report.normalized.json`
- `artifacts/phases/P01_CONFIG_SCHEMA/config_validation_multi_az_report.normalized.json`
- `schemas/**/*`
- `src/valkey_scale_lab/config/*`
- `src/valkey_scale_lab/cli.py`
- `tests/config/*`
- `tests/unit/test_cli_contract.py`
- `templates/configs/single_mac_6node.yaml`
- `templates/configs/local_az_3x2.yaml`
- `templates/configs/scale_1000_dryrun_optin.yaml`

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| harness_precheck | PASS | PASS | `artifacts/gates/P01_CONFIG_SCHEMA/stdout/harness_precheck.log` = `PASS precheck`; command matches manifest |
| safety_static_scan | PASS | PASS | `artifacts/gates/P01_CONFIG_SCHEMA/stdout/safety_static_scan.log` = `PASS safety_scan`; command matches manifest |
| config_unit_tests | PASS | PASS | `artifacts/gates/P01_CONFIG_SCHEMA/stdout/config_unit_tests.log` reports `16 passed in 0.04s`; command matches manifest |
| validate_single_mac_config | PASS | PASS | `artifacts/gates/P01_CONFIG_SCHEMA/stdout/validate_single_mac_config.log`; command matches manifest |
| validate_multi_az_config | PASS | PASS | `artifacts/gates/P01_CONFIG_SCHEMA/stdout/validate_multi_az_config.log`; command matches manifest |
| emit_config_schema_report | PASS | PASS | `artifacts/gates/P01_CONFIG_SCHEMA/stdout/emit_config_schema_report.log`; command matches manifest |

All six manifest gates are present in `gate_result.json`, all have `status: PASS` and `exit_code: 0`, and the recorded command strings exactly match `codex/phase_manifest.json`.

All stdout/stderr files cited by `gate_result.json` exist. Recomputed SHA256 values matched every recorded `stdout_sha256` and `stderr_sha256`.

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P01_CONFIG_SCHEMA/phase_summary.json` | `schemas/artifact/phase_summary.schema.json` | valid | `python3 scripts/validate_json_schema.py --schema schemas/artifact/phase_summary.schema.json --instance artifacts/phases/P01_CONFIG_SCHEMA/phase_summary.json` passed |
| `artifacts/phases/P01_CONFIG_SCHEMA/config_validation_report.json` | `schemas/artifact/config_validation_report.schema.json` | valid | Report status PASS, `valid: true`, `total_nodes: 6`, normalized path present |
| `artifacts/phases/P01_CONFIG_SCHEMA/config_validation_multi_az_report.json` | `schemas/artifact/config_validation_report.schema.json` | valid | Report status PASS, `valid: true`, `total_nodes: 6`, normalized path present |
| `artifacts/phases/P01_CONFIG_SCHEMA/config_schema_report.json` | `schemas/artifact/config_schema_report.schema.json` | valid | Report status PASS and cites `schemas/config/run_config.schema.json` |
| `artifacts/phases/P01_CONFIG_SCHEMA/config_validation_report.normalized.json` | `schemas/config/run_config.schema.json` | valid | Normalized single-AZ config includes host, safety, runtime, cluster, workload, and faults fields |
| `artifacts/phases/P01_CONFIG_SCHEMA/config_validation_multi_az_report.normalized.json` | `schemas/config/run_config.schema.json` | valid | Normalized multi-AZ config includes virtual AZ fault and workload fields |

## Config validation findings

P01 covers the required config surface. `schemas/config/run_config.schema.json`, `src/valkey_scale_lab/config/validation.py`, templates, unit tests, generated reports, and independent probes show coverage for:

- physical host config: host ID, OS, architecture, memory, disk, IP, Docker endpoint, and labels;
- virtual AZ config: single-AZ and multi-AZ modes plus AZ count validation;
- Valkey cluster config: shards, replicas per shard, 9.1.x image tag, ports, and resource limits;
- workload config: read/write ratio, uniform and hotspot QPS, pipeline, keyspace-related hotspot fraction, and fault-relative timing values;
- fault config: node or virtual-AZ targets with network delay/loss/partition/flap and process stop/restart types;
- safety config: default max nodes exactly 100, sandbox required, host network mutation forbidden, cleanup-on-error present;
- normalization output: both validation reports cite normalized config artifacts that validate against `schemas/config/run_config.schema.json`;
- 1000-node opt-in dry-run constraints: accepted only with `allow_1000_nodes`, `require_1000_env`, `scale_profile.opt_in_1000`, `scale_profile.dry_run_only`, and `runtime.dry_run`.

Independent spot checks produced the expected rejection codes: `HOST_FIELD_REQUIRED`, `MULTI_AZ_COUNT`, `VALKEY_VERSION`, `WORKLOAD_RATIO_SUM`, `FAULT_TYPE`, `SANDBOX_REQUIRED`, `HOST_NETWORK_FORBIDDEN`, `NODE_CAP_EXCEEDED`, and `MISSING_1000_DRY_RUN`.

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: verified for this phase as no runtime resources are started; `cleanup_on_error` is required in config and P01 makes no runtime cluster claim
- Default node cap <= 100: verified

The P01 gate ran `python3 scripts/safety_scan.py` successfully. A direct search found safety-sensitive command names only in policy/audit documentation or safety tooling, not in the P01 implementation path. The implementation does not introduce host route, firewall, interface, OS network service, sudo, or broad process-kill behavior.

## Real Valkey findings

Required for this phase: NO
Evidence file: N/A
Valkey version observed: N/A
Independent live probe: N/A

`codex/phase_manifest.json` marks `P01_CONFIG_SCHEMA` with `fake_only_allowed: true` and `real_valkey_required: false`. `docs/codex/02_PHASES.md` also says P01 allows fake-only validation. The phase summary records real Valkey evidence as `SKIPPED_WITH_REASON` and does not claim live Valkey operation.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| YAML parser is intentionally limited to repository template style | low | no | Recorded in `artifacts/phases/P01_CONFIG_SCHEMA/phase_summary.json`; acceptable for P01 because templates and generated normalized artifacts validate |

## Final rationale

Decision: PASS. The P01 gate result is present, schema-valid, and has SHA256 `4920c0f8ec397484714a41a3e04e4137c65ea9606e0e2896b9db0b6557402825`. Every manifest gate ran and passed, command text matches the manifest, all gate log SHA256 values match, all required artifacts exist and validate, normalized config artifacts validate against the run config schema, P01 is fake-only and does not require real Valkey evidence, and the inspected implementation preserves the safety constraints and default 100-node cap.
