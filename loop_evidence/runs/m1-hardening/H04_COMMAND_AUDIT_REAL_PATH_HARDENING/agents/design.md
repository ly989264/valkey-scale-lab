# H04 Design Brief

role: design
agent_invocation: real_subagent
stage_id: H04_COMMAND_AUDIT_REAL_PATH_HARDENING
source_commit_before: d5969a67ace6af2b0d085839db3e8b318c956973
source_commit_after: d5969a67ace6af2b0d085839db3e8b318c956973

## Summary

H04 should harden command audit acceptance so command audit claims for 50, 100, and 200 nodes can pass only when real exact-scale Valkey 9.1.x evidence is paired with C07-complete command logs and summaries. The expected success shape for this hardening stage is not to invent missing command evidence. It is to make unsafe command audit PASS impossible: C07-complete exact-scale claims may pass, while empty legacy command logs, incomplete rows, placeholders, fixture paths, and summary mismatches must remain `BLOCKED_WITH_REASON` or become hard gate failures if any code tries to promote them.

## Sources Read

- `codex_goal_loop_m1_hardening_v2/prompts/DESIGN_SUBAGENT_PROMPT.md`
- `codex_goal_loop_m1_hardening_v2/AGENTS_M1H_V2.md`
- `codex_goal_loop_m1_hardening_v2/START_HERE.md`
- Core docs under `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md`, including evidence taxonomy, hard gate architecture, stage protocol, no-shortcut rules, acceptance matrix, blocked policy, review rubric, commands and gates, and stage exit contract.
- `codex_goal_loop_m1_hardening_v2/stages/H04_COMMAND_AUDIT_REAL_PATH_HARDENING.md`
- `codex_goal_loop_m1_hardening_v2/contracts/C04_EXACT_SCALE_REQUIREMENTS.md`
- `codex_goal_loop_m1_hardening_v2/contracts/C05_STATIC_FORBIDDEN_PATTERNS.md`
- `codex_goal_loop_m1_hardening_v2/contracts/C07_COMMAND_AUDIT_CONTRACT.md`
- `codex_goal_loop_m1_hardening_v2/contracts/C12_NO_SIMULATED_SUBAGENT_CONTRACT.md`
- `codex_goal_loop_m1_hardening_v2/docs/17_COMMANDS_AND_GATES.md`
- `codex_goal_loop_m1_hardening_v2/docs/18_STAGE_EXIT_CONTRACT.md`
- `runs/m1-hardening/H04_COMMAND_AUDIT_REAL_PATH_HARDENING/handoff/CONTEXT_RELOAD.md`
- `scripts/m1h/manifest.py`
- `scripts/m1h/capability_gate.py`
- `scripts/m1h/assert_command_audit_real.py`
- `scripts/m1h/assert_stage_exit.py`
- `schemas/artifact/command_log_entry.schema.json`
- `schemas/artifact/command_audit_summary.schema.json`
- `tests/m1h/test_gate_framework.py`

## Current Gap

`scripts/m1h/manifest.py` currently treats command audit as present when any command JSONL has any row. That is weaker than C07. It does not validate every row against `command_log_entry.schema.json`, does not reject placeholder command invocations, does not require the C07 command kinds, does not verify output refs or hashes, does not connect summary operation traceability to command ids, and does not require retry/failure/timeout summaries. `scripts/m1h/assert_command_audit_real.py` is only a generic capability wrapper, so it reports blocked command claims but does not prove the fail-closed C07 rules.

## Exact C07 Checks

Add a command-audit evaluator used by both manifest generation and the H04 gate. For each required command claim `command_audit.real_exact.50`, `command_audit.real_exact.100`, and `command_audit.real_exact.200`, evaluate only non-fixture candidate artifacts from the exact-scale phase paths.

Real exact-scale preconditions for PASS:

1. A `valkey_e2e_evidence.json` source in the same candidate set has `status: PASS`, `real_valkey: true`, `nodes_observed == scale`, and at least one `valkey_versions[]` entry starting with `9.1.`.
2. Source artifacts are not under `tests/fixtures`, are not dry-run paths, and are not legacy-only evidence unless an explicit M1 reconstruction proves every C07 field without invention.
3. `command_audit_summary.json` is present, schema-valid, has `artifact_type: command_audit_summary`, `status: PASS`, and its `command_log_ref` resolves to one of the accepted command log files.

Command log file checks:

1. At least one command log file exists among `command_log.jsonl`, `management_command_log.jsonl`, or `fault_command_log.jsonl`, and the accepted log has at least one parsed row.
2. Any `management_command_log.jsonl` under the corresponding exact-scale management phase that is empty or whitespace-only invalidates the claim with code `empty_management_command_log`, even if another log contains rows.
3. Every nonblank JSONL line parses to an object. Invalid JSON, non-object rows, or skipped lines must block the claim.
4. Every row validates against `schemas/artifact/command_log_entry.schema.json`.
5. Every row has `host_network_mutated: false` and `global_firewall_mutated: false`.
6. `command_id` values are unique within the accepted log and match the schema pattern.
7. Timing is internally consistent: `ended_at_unix_ms >= started_at_unix_ms`, `duration_ms >= 0`, and `duration_ms` is close enough to `ended_at_unix_ms - started_at_unix_ms` to catch obvious fabrication or zeroed timestamps.
8. Row `status` may be `PASS`, `FAIL`, `TIMEOUT`, or `RETRY` for real logs. `MISSING` or `SKIPPED_WITH_REASON` in a required row field blocks exact-scale PASS.

Placeholder rejection:

1. Reject `argv == ["valkey-cli", "cluster", "create_cluster"]`.
2. Reject command kinds or argv tokens containing obvious placeholders such as `placeholder`, `fake`, `fixture`, `dry_run`, or `create_cluster` for real command audit PASS.
3. Reject rows whose command kind claims a C07 kind but whose argv cannot plausibly match that kind:
   `cluster_meet` must include `cluster meet`;
   `cluster_addslots` must include `cluster addslots` or `cluster addslotsrange`;
   `cluster_replicate` must include `cluster replicate`;
   `cluster_probe` must include a cluster read/probe command such as `cluster info`, `cluster nodes`, `cluster slots`, or `cluster shards`;
   `cleanup` must be a cleanup or owned-resource teardown command.

Required command kinds for PASS:

1. For exact-scale command audit claims, the accepted rows must include all five C07 kinds: `cluster_meet`, `cluster_addslots`, `cluster_replicate`, `cluster_probe`, and `cleanup`.
2. `command_audit_summary.by_command_kind` or `summary.coverage` must agree with row-derived counts for those five kinds.
3. Missing kinds must block with one reason per missing kind, for example `missing C07 command kind cluster_replicate`.

Output ref and hash checks:

1. Each row must include non-empty `stdout_path`, `stdout_sha256`, `stderr_path`, and `stderr_sha256`.
2. Hash values must match the 64-character lowercase hex pattern from the row schema.
3. Paths must resolve under the repository root or the log directory, must not escape via `..`, and should exist for a PASS. If historical artifacts retained hashes but not files, treat the claim as blocked unless the summary explicitly records retained-hash-only provenance accepted by C07.
4. When the referenced output file exists, recompute SHA-256 and require it to match the recorded hash.

Summary consistency checks:

1. `total_commands == len(rows)`.
2. `pass_count`, `failure_count`, `timeout_count`, and `retry_count` match row-derived counts.
3. `failed_commands`, `timeout_commands`, and `retry_commands` contain only command ids present in the log and cover every row with the corresponding status or retry index.
4. `retry_count` must equal the count of rows with `retry_index > 0` or `status: RETRY`, using one deterministic rule in the evaluator and tests.
5. `slowest_commands_topN` entries must reference existing command ids and must not exceed the row count.
6. `missing_or_skipped` must be empty for a real exact-scale PASS. Non-empty entries are allowed only when the claim remains blocked.

Operation traceability:

1. `operation_traceability` must be a non-empty list for real exact-scale command audit PASS.
2. Each trace item must include an `operation_id` and command references, preferably `command_ids`.
3. Every referenced command id must exist in the accepted rows.
4. Every non-cleanup `operation_id` from the rows must appear in the summary traceability list.
5. Management operation artifacts that reference command ids, including `management_ops_matrix.json` and `management_operation_results.jsonl` when present in the same phase, must reference ids found in the accepted command log.

Manifest semantics to add for command audit:

- `real_valkey_verified`
- `exact_scale_observed`
- `valkey_9_1_verified`
- `command_audit_summary_present`
- `command_audit_summary_schema_valid`
- `command_log_present`
- `command_log_non_empty`
- `command_rows_schema_valid`
- `no_placeholder_commands`
- `required_command_kinds_present`
- `output_refs_or_hashes_present`
- `output_hashes_verified`
- `operation_traceability_complete`
- `retry_failure_timeout_summary_present`
- `empty_legacy_management_log_absent`
- `m1_format_fields_complete`
- `hardening_stage_accepted`

`m1_format_fields_complete` and `hardening_stage_accepted` for command audit should be true only when every C07 semantic check above is true. Otherwise the claim status must be `BLOCKED_WITH_REASON` with concrete missing fields. If a manifest ever contains `status: PASS` for command audit while any C07 check is false, the H04 gate must return `FAIL`.

## Implementation Plan For Worker

1. Add command-audit evaluation helpers in `scripts/m1h/manifest.py` or a small imported helper. Reuse `read_json`, `read_jsonl`, `relpath`, and `violation`; use `jsonschema` if available in the project test environment, otherwise implement the required schema checks explicitly from the two schema files.
2. Replace the generic command-audit handling in `_semantic_checks` with the C07 evaluator. Keep existing required claim ids from C04: command audit 50, 100, and 200. If setup-30 command auditing is surfaced, make it a non-required diagnostic claim or document why C04 does not include a required command-audit 30 claim.
3. Update `_evidence_kind` so command audit can become `REAL_EXACT_SCALE` only when the C07 evaluator accepts the claim. Real Valkey evidence plus incomplete command logs must remain `LEGACY_EVIDENCE_ONLY`, `INVALID`, or `BLOCKED_WITH_REASON`, never PASS.
4. Replace `scripts/m1h/assert_command_audit_real.py` with a stage-aware hardening gate. It should write `runs/m1-hardening/H04_COMMAND_AUDIT_REAL_PATH_HARDENING/artifacts/gates/assert_command_audit_real.json` with `status: PASS` when all command-audit claims are either C07-complete PASS or honestly blocked, and `status: FAIL` when any unsafe command-audit PASS exists.
5. Extend `scripts/m1h/assert_stage_exit.py` with `H04_REQUIRED_GATE_RESULTS` and add it to `STAGE_REQUIRED_GATE_RESULTS`.
6. Add or extend tests in `tests/m1h/test_gate_framework.py` for a valid C07 exact-scale PASS, empty command log blocking, empty `management_command_log.jsonl` blocking, placeholder argv blocking, missing required kind blocking, fixture path blocking, incomplete legacy row blocking, summary count mismatch blocking, management operation command refs requiring real ids, and H04 stage exit requiring `assert_command_audit_real`.

## Required Gates

The worker and main agent should run these gates, and each script gate must write JSON under `runs/m1-hardening/H04_COMMAND_AUDIT_REAL_PATH_HARDENING/artifacts/gates/`:

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

`assert_stage_exit.py` should require at least these H04 gate result files: `build_evidence_manifest.json`, `assert_evidence_taxonomy.json`, `assert_command_audit_real.json`, `assert_no_fixture_fallback.json`, `assert_no_legacy_m1_pass.json`, and `assert_no_simulated_subagents.json`.

## Acceptance Criteria

H04 passes when executable gates prove command audit false PASS is impossible. Exact-scale command audit claims may pass only with real Valkey 9.1.x exact-scale evidence and C07-complete logs and summaries. Existing historical or empty command logs should stay blocked with precise reasons; they must not be hidden behind fixtures, row-count-only checks, legacy evidence, or generated report output.
