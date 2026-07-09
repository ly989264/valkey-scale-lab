# H04 Design Brief

role: design
agent_invocation: real_subagent
stage_id: H04_COMMAND_AUDIT_REAL_PATH_HARDENING
source_commit_before: d5969a67ace6af2b0d085839db3e8b318c956973
source_commit_after: d5969a67ace6af2b0d085839db3e8b318c956973

## Design Decision

H04 must make command audit claims fail closed. A command audit exact-scale claim for 50, 100, or 200 nodes can pass only if real exact-scale Valkey 9.1.x evidence and C07-complete command artifacts are present. If the repository only has legacy rows, empty `management_command_log.jsonl`, fixtures, placeholders, or incomplete summaries, the claim must remain `BLOCKED_WITH_REASON`; if any such claim is promoted to PASS, `assert_command_audit_real.py` must fail.

## Exact C07 Checks To Implement

For each required claim `command_audit.real_exact.50`, `command_audit.real_exact.100`, and `command_audit.real_exact.200`, require:

1. Same-scale `valkey_e2e_evidence.json` with `status: PASS`, `real_valkey: true`, `nodes_observed == scale`, and `valkey_versions` containing `9.1.x`.
2. Non-fixture, non-dry-run command artifacts from the exact-scale candidate phase paths.
3. Schema-valid `command_audit_summary.json` with `status: PASS` and a `command_log_ref` resolving to an accepted command log.
4. A non-empty accepted command log from `command_log.jsonl`, `management_command_log.jsonl`, or `fault_command_log.jsonl`.
5. No empty or whitespace-only `management_command_log.jsonl` for the corresponding management scale.
6. Every JSONL row parses, is an object, validates against `schemas/artifact/command_log_entry.schema.json`, has unique `command_id`, has safe mutation flags set to false, and has consistent timing.
7. No required row field is encoded as `MISSING` or `SKIPPED_WITH_REASON` for real PASS.
8. No placeholder command, including `["valkey-cli", "cluster", "create_cluster"]`, fake/fixture/dry-run argv, or misleading command kind labels.
9. Required command kinds all present in rows and summary coverage: `cluster_meet`, `cluster_addslots`, `cluster_replicate`, `cluster_probe`, and `cleanup`.
10. Command kind labels agree with argv shape: meet/addslots/addslotsrange/replicate/cluster probe/cleanup must be plausible from the recorded argv.
11. `stdout_path`, `stdout_sha256`, `stderr_path`, and `stderr_sha256` are present on every row; hashes match the schema pattern; paths resolve safely; existing output files hash-match the recorded values.
12. Summary counts match rows: `total_commands`, `pass_count`, `failure_count`, `timeout_count`, and `retry_count`.
13. `failed_commands`, `timeout_commands`, `retry_commands`, and `slowest_commands_topN` only reference command ids present in the log and cover the corresponding rows.
14. `operation_traceability` is non-empty, every referenced command id exists, every non-cleanup row operation id is traceable, and management operation artifacts in the same phase reference real command ids when present.
15. `missing_or_skipped` is empty for PASS; non-empty is allowed only when the claim remains blocked.

Add semantic checks for command audit: `real_valkey_verified`, `exact_scale_observed`, `valkey_9_1_verified`, `command_audit_summary_present`, `command_audit_summary_schema_valid`, `command_log_present`, `command_log_non_empty`, `command_rows_schema_valid`, `no_placeholder_commands`, `required_command_kinds_present`, `output_refs_or_hashes_present`, `output_hashes_verified`, `operation_traceability_complete`, `retry_failure_timeout_summary_present`, `empty_legacy_management_log_absent`, `m1_format_fields_complete`, and `hardening_stage_accepted`.

## Worker Scope

Update `scripts/m1h/manifest.py` or a small helper used by it to evaluate C07. Update `scripts/m1h/assert_command_audit_real.py` so H04 passes when the hardening check proves no unsafe command-audit PASS exists, while honestly blocked claims remain blocked in the manifest. Update `scripts/m1h/assert_stage_exit.py` with an H04 gate list. Add regression tests in `tests/m1h/test_gate_framework.py` for valid C07 PASS, empty command logs, empty management logs, placeholders, missing command kinds, fixtures, incomplete legacy rows, summary mismatches, operation command refs, and H04 stage exit gate requirements.

## Required Gates

```text
PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h04 python3 -m compileall -q scripts src tests
PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h04 python3 -m pytest -q tests/unit tests/integration tests/m1h tests/ci/test_milestone1_acceptance_gate.py
python3 scripts/m1h/build_evidence_manifest.py --stage H04_COMMAND_AUDIT_REAL_PATH_HARDENING --out runs/m1-hardening/evidence_manifest.json
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H04_COMMAND_AUDIT_REAL_PATH_HARDENING
python3 scripts/m1h/assert_command_audit_real.py --stage H04_COMMAND_AUDIT_REAL_PATH_HARDENING
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H04_COMMAND_AUDIT_REAL_PATH_HARDENING
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H04_COMMAND_AUDIT_REAL_PATH_HARDENING
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H04_COMMAND_AUDIT_REAL_PATH_HARDENING
python3 scripts/m1h/assert_stage_exit.py --stage H04_COMMAND_AUDIT_REAL_PATH_HARDENING
```

Stage exit must require gate result JSON for `build_evidence_manifest`, `assert_evidence_taxonomy`, `assert_command_audit_real`, `assert_no_fixture_fallback`, `assert_no_legacy_m1_pass`, and `assert_no_simulated_subagents`.

## Acceptance Criteria

H04 is acceptable only when executable gates enforce C07 and prevent command audit false PASS. Real exact-scale command audit PASS requires the full C07 check set. Otherwise the manifest must preserve precise blocked reasons and the gate artifacts must show the hardening decision.
