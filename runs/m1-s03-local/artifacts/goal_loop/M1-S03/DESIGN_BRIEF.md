# M1-S03 DESIGN_BRIEF — Command-Level Audit Log

## Decision

Design status: READY_FOR_WORKER

M1-S03 must make command logging a common runtime facility, not a local patch for one phase. Every PASS cluster setup, management, fault, probe, and cleanup operation must be traceable to one or more command log entries, and failure/timeout/retry paths must be schema-valid and visible in analysis and the Chinese offline report.

## Goal Interpretation

The stage requirement is not just "write `command_log.jsonl`." It is the full propagation chain:

```text
schema -> writer -> fixture -> reader -> aggregator -> renderer -> gate -> docs
```

The command log must be nonempty for PASS operations and must cover these command families:

- cluster meet
- addslots
- replicate
- cluster info / cluster nodes / probes
- cleanup
- future reshard / setslot / migrate / rebalance / failover / forget / reset / shutdown / restart
- fault apply / clear

Real Valkey may remain blocked in the Codex sandbox, but the runtime path must be ready and blocked evidence must never be converted into fake command evidence.

## Current Code Paths To Inspect

Primary command execution currently passes through these paths:

- `src/valkey_scale_lab/runtime/docker_runtime.py`
  - `run_docker(...)`: generic Docker subprocess wrapper.
  - `run_container_cli(...)` / `run_container_cluster_cli(...)`: `docker exec ... valkey-cli` for one-container-per-node runtime.
  - `run_node_cli(...)` / `run_node_cluster_cli(...)`: node-aware CLI wrappers for process and container runtime.
  - `_node_command(...)`: common Valkey command path, with host command first and Docker fallback.
  - `_meet_node_pair(...)`, `_tree_fanout_meet_nodes(...)`: `CLUSTER MEET`.
  - `_add_slots_node(...)`: `CLUSTER ADDSLOTS`.
  - `_replicate_process_nodes_parallel(...)`, `_replicate_with_retry(...)`, `_ensure_replica_of(...)`: replication and retry loops.
  - `_create_primary_cluster(...)`: `valkey-cli --cluster create`.
  - `_assign_probe_slot_to_first_primary(...)`: `CLUSTER SETSLOT`.
  - `_wait_process_nodes_ready(...)`, `_wait_process_known(...)`, `_wait_process_cluster_ok(...)`, `_wait_process_slots_assigned(...)`: probe loops.
  - `_cleanup_resources_by_label(...)`, `_cleanup_process_scenario(...)`: cleanup commands.
  - `_run_management_ops(...)`: smoke management probes.
- `src/valkey_scale_lab/fault/sandbox.py`
  - `apply_fault(...)`: `node_stop` uses `run_docker`.
  - `clear_fault(...)`: restart and readiness probes use `run_docker`.
- `src/valkey_scale_lab/cli.py`
  - `_gate_scenario(...)`, `_gate_cleanup(...)`, `_fault_apply(...)`, `_fault_clear(...)`: CLI boundaries that should create/attach a recorder and finalize artifacts.
- `src/valkey_scale_lab/analysis/summary.py`
  - currently reads setup telemetry but not command logs.
- `src/valkey_scale_lab/report/render.py`
  - currently renders setup telemetry but not command audit sections.
- Existing loose schemas:
  - `schemas/artifact/command_log_entry.schema.json` is too permissive for M1-S03 and allows missing required fields.
  - `schemas/loop_engineering/command_log_entry.schema.json` is for Codex loop commands, not Valkey runtime commands.

## Proposed Implementation

### 1. Schema

Replace/strengthen `schemas/artifact/command_log_entry.schema.json` as the single runtime command-entry schema. Required fields:

```text
schema_version
artifact_type
phase_id
run_id
scenario
operation_id
step_id
command_id
command_kind
host_id
node_logical_id
client_port
argv
started_at_unix_ms
ended_at_unix_ms
duration_ms
exit_code
stdout_path or stdout_sha256
stderr_path or stderr_sha256
retry_index
timeout_ms
status
error_type
```

Recommended additional fields:

```text
attempt_count
target_logical_id
container_name
nodehost_id
command_scope
redaction
source_path
source_function
trace_refs
```

Rules:

- `argv` must be a nonempty array of strings.
- `status` enum: `PASS`, `FAIL`, `TIMEOUT`, `RETRY`, `SKIPPED_WITH_REASON`, `MISSING`.
- `duration_ms` must be numeric for executed commands; skipped/missing rows must use structured reasons.
- stdout/stderr must be recorded either as paths under the current run artifacts/logs or as sha256 hashes. Prefer paths for nonempty captured output and hashes for empty/short output.
- No host-network mutation flags may be hidden; future fault command rows should support `host_network_mutated: false`, `global_firewall_mutated: false`.

Also add an aggregate schema:

- `schemas/artifact/command_audit_summary.schema.json`

Required summary fields:

```text
artifact_type=command_audit_summary
phase_id
run_id
status
command_log_ref
total_commands
pass_count
failure_count
timeout_count
retry_count
slowest_commands_topN
failed_commands
retry_commands
operation_traceability
coverage
missing_or_skipped
```

### 2. Writer / Recorder

Add a new module:

```text
src/valkey_scale_lab/runtime/command_recorder.py
```

Suggested API:

```python
class CommandRecorder:
    def __init__(self, *, phase_id, run_id, scenario, artifacts_dir, log_dir=None): ...
    def record_subprocess(self, *, operation_id, step_id, command_kind, argv, timeout_ms, node=None, host_id="local", retry_index=0, check=True): ...
    def record_result(self, *, operation_id, step_id, command_kind, argv, started, ended, exit_code, stdout, stderr, timeout_ms, node=None, retry_index=0, error_type=""): ...
    def record_skipped(self, *, operation_id, step_id, command_kind, reason, node=None): ...
    def close(self) -> dict: ...
```

Artifact outputs:

```text
runs/<run_id>/artifacts/command_log.jsonl
runs/<run_id>/artifacts/command_audit_summary.json
runs/<run_id>/logs/commands/<command_id>.stdout.log
runs/<run_id>/logs/commands/<command_id>.stderr.log
```

The recorder must be thread-safe because cluster setup uses `_bounded_parallel`. It should preserve deterministic ordering by assigning monotonically increasing sequence numbers under a lock, then writing JSONL either immediately with a lock or buffering and sorting at `close()`.

### 3. Runtime Attachment

Thread the recorder through CLI/runtime boundaries:

- In `cli._gate_scenario`, instantiate recorder before `create_scenario(...)`.
- Extend `create_scenario(..., command_recorder=None)` and pass it through process/container setup.
- In `cli._gate_cleanup`, instantiate or reopen a recorder from the state/runtime path so cleanup commands append to the same `command_log.jsonl`.
- In fault CLI commands, pass a recorder into `apply_fault(...)` / `clear_fault(...)`.
- Store `command_log_ref` and `command_audit_summary_ref` in runtime state when available.

Convert central wrappers instead of sprinkling ad hoc writes:

- Change `run_docker(...)` to accept optional `recorder`, `operation_id`, `step_id`, `command_kind`, `node`, `retry_index`.
- Change `run_node_cli(...)`, `run_node_cluster_cli(...)`, and `_node_command(...)` to accept/pass recorder metadata.
- Add targeted metadata at semantic call sites: `cluster_meet`, `cluster_addslots`, `cluster_replicate`, `cluster_probe`, `cluster_create`, `cleanup_stop`, `cleanup_remove`, `fault_apply`, `fault_clear`.

This gives future M1-S04 and M1-S06 a single API instead of a stage-specific patch.

### 4. PASS Operation Traceability

Every operation artifact row with `status: PASS` should include command refs:

- setup operation dictionaries from `_configure_cluster(...)` and `_configure_process_cluster(...)`
- management operation rows
- cleanup report actions
- fault apply/clear reports

Minimum shape:

```json
"command_log_refs": ["command_log.jsonl#cmd-000001", "command_log.jsonl#cmd-000002"]
```

The gate should require:

- Any PASS operation in management/setup/fault/cleanup has at least one command ref unless it is an explicitly non-command operation with `SKIPPED_WITH_REASON`.
- Referenced `command_id` exists in `command_log.jsonl`.
- Referenced commands have matching `operation_id` or `step_id`.

### 5. Fixtures

Add runtime command fixtures under:

```text
tests/fixtures/command_log/success/command_log.jsonl
tests/fixtures/command_log/failure/command_log.jsonl
tests/fixtures/command_log/timeout/command_log.jsonl
tests/fixtures/command_log/retry/command_log.jsonl
tests/fixtures/command_log/cleanup_residual/command_log.jsonl
tests/fixtures/command_log/empty/command_log.jsonl
tests/fixtures/command_log/success/command_audit_summary.json
```

Required samples:

- success: `CLUSTER MEET`, `CLUSTER ADDSLOTS`, `CLUSTER REPLICATE`, `CLUSTER INFO`, `CLUSTER NODES`, cleanup remove.
- failure: nonzero exit with stderr and `status: FAIL`.
- timeout: `status: TIMEOUT`, `error_type: timeout`, `exit_code` structured `MISSING` or conventional nonzero with reason.
- retry: same operation with `retry_index: 0` failure and `retry_index: 1` pass; summary counts retry.
- cleanup residual: cleanup command rows exist but cleanup summary fails due residual scan.
- empty: intentionally invalid fixture for the gate to reject.

### 6. Reader / Aggregator

Update `src/valkey_scale_lab/analysis/summary.py`:

- Load optional `command_log.jsonl`.
- Reject malformed JSONL in strict paths; for legacy inputs use structured `SKIPPED_WITH_REASON`.
- Aggregate:
  - `command_audit.total_commands`
  - `command_audit.slowest_commands_topN`
  - `command_audit.failed_commands`
  - `command_audit.timeout_commands`
  - `command_audit.retry_commands`
  - `command_audit.by_command_kind`
  - `command_audit.operation_traceability`
- Add missing metrics when command log is absent for a PASS source operation:
  - `command_log.total_commands`
  - `command_log.traceability`

Do not make the report the data source. Analysis must derive from JSONL and summary artifacts.

### 7. Renderer

Update `src/valkey_scale_lab/report/render.py`:

Generated files:

```text
reports/command_slowest.csv
reports/command_failures.csv
reports/command_retries.csv
reports/command_latency.svg
```

Markdown and HTML Chinese sections:

```text
## 慢命令 TopN
## 失败命令
## 重试命令
## 命令审计覆盖
```

Report index additions:

```json
"command_audit_report_inputs": {
  "command_log": "...",
  "command_audit_summary": "...",
  "csv": ["command_slowest.csv", "command_failures.csv", "command_retries.csv"],
  "svg": "command_latency.svg"
}
```

### 8. Stage-Specific Gate

Add:

```text
scripts/assert_command_log_nonempty_and_schema.py
```

Checks:

- `command_log.jsonl` exists and is nonempty for PASS operations.
- Each row validates against `schemas/artifact/command_log_entry.schema.json`.
- Required command kinds are present for success fixture and M1-S03 stage run:
  - `cluster_meet`
  - `cluster_addslots`
  - `cluster_replicate`
  - `cluster_probe`
  - `cleanup`
- failure, timeout, retry fixtures are recognized.
- empty command log fixture fails.
- PASS operation traceability has valid command ids.
- analysis includes `command_audit`.
- report index includes command audit outputs.
- Markdown/HTML contain Chinese command audit headings.
- blocked real run uses `BLOCKED_WITH_REASON` and does not invent command rows.

### 9. Tests

Add/update:

- `tests/artifacts/test_command_log.py`
  - schema validation for success/failure/timeout/retry fixtures.
  - recorder writes nonempty log and summary.
  - empty fixture rejected by gate.
- `tests/integration/test_docker_runtime_contract.py`
  - monkeypatch `run_docker` / host commands and assert setup operations have `command_log_refs`.
  - assert cleanup actions have command refs.
- `tests/unit/test_fault_sandbox.py`
  - fault apply/clear pass recorder through node stop/restart paths.
- `tests/analysis/test_analysis_summary.py`
  - command audit aggregation appears and missing command log is reported.
- `tests/report/test_report_rendering.py`
  - generated command CSV/SVG and Chinese headings exist.

### 10. Documentation / Handoff

Update M1-S03 artifacts only:

- `runs/m1-s03-local/artifacts/goal_loop/M1-S03/coverage_matrix.md`
- `WORKER_SUMMARY.md`
- `REVIEW.md`
- `COMPLETION.md`
- `CONTEXT_RELOAD.md`

Do not create a soak stage and do not alter milestone stage ordering.

## Coverage Matrix Plan

| field_or_behavior | execution_shape | scale_rung | functional_path | data_path | outcome_class | required_evidence |
|---|---|---|---|---|---|---|
| command_log core schema | fake/unit | small_cluster, 30, 50, 100, 200, 200+ dry-run | cluster_setup, management_ops, fault, cleanup | schema, fixture, gate | success/failure/timeout/retry | schema validation + fixture tests |
| recorder nonempty on PASS | integration/smoke | small_cluster | cluster_setup, cleanup | writer, regression_check | success | integration test + stage gate |
| blocked real path no fake rows | blocked_run | small_cluster | real_local_run | writer, gate | blocked_run | `real_heavy_gate_blocked.json` + gate |
| command traceability refs | unit/integration | small_cluster, 30, 50, 100, 200 | setup, management_ops, fault, cleanup | writer, artifact_reader, gate | success | operation rows reference existing command ids |
| failure command visibility | fake/unit | small_cluster | cluster_setup, fault, cleanup | fixture, reader, aggregator, renderer | command_failure | failed commands aggregate and report |
| timeout command visibility | fake/unit | small_cluster | cluster_setup, fault, cleanup | fixture, reader, aggregator, renderer | timeout | timeout fixture and report row |
| retry command visibility | fake/unit | small_cluster | replicate/failover/fault clear | fixture, reader, aggregator, renderer | retry | retry fixture and TopN/retry report |
| cleanup command coverage | integration/smoke | small_cluster | cleanup | writer, gate | cleanup_residual/success | cleanup report action refs |
| report command sections | unit/report | all supported via same schema | analysis/report | renderer | success/report_input_missing | Chinese headings, CSV/SVG, report index |

All matrix rows must have explicit `PASS`, `SKIPPED_WITH_REASON`, `UNSUPPORTED_WITH_REASON`, or `BLOCKED_WITH_REASON`; no empty reason fields on skipped/blocked rows.

## Required Gates

Worker/main should run at minimum:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m compileall -q scripts src
PYTHONPATH=src python3 -m pytest -q tests/unit tests/integration
PYTHONPATH=src python3 -m pytest -q tests/artifacts/test_command_log.py tests/analysis/test_analysis_summary.py tests/report/test_report_rendering.py
PYTHONPATH=src python3 scripts/assert_command_log_nonempty_and_schema.py --artifacts-dir runs/m1-s03-local/artifacts --analysis runs/m1-s03-local/artifacts/analysis_summary.json --report-index runs/m1-s03-local/reports/report_index.json
PYTHONPATH=src python3 scripts/assert_command_log_nonempty_and_schema.py --fixtures tests/fixtures/command_log
python3 scripts/validate_json_schema.py --schema schemas/artifact/command_log_entry.schema.json --instance tests/fixtures/command_log/success/command_log.jsonl
```

If `validate_json_schema.py` cannot validate JSONL directly, the worker should either extend it safely for JSONL or validate through the new gate. Do not mark JSONL schema validation as done by checking file existence only.

Real local Valkey gate should be attempted with the existing wrapper. If the sandbox still rejects port binding, write:

```text
runs/m1-s03-local/artifacts/goal_loop/M1-S03/real_heavy_gate_blocked.json
```

with `status: BLOCKED_WITH_REASON`, command, stderr, and reason. Do not synthesize command rows for the blocked attempt unless commands actually executed inside the harness recorder.

## Review-Fail Checkpoints

Review must FAIL if any of these are true:

- `command_log.jsonl` is absent or empty while a source operation is `PASS`.
- Schema allows missing `operation_id`, `step_id`, `argv`, timing, exit status, stdout/stderr evidence, retry index, timeout, status, or error type.
- Commands are only recorded in one path, e.g. cluster setup but not cleanup/fault.
- Recorder is stage-specific rather than reusable by M1-S04 management and M1-S06 fault/failover paths.
- Analysis does not read JSONL.
- Report does not show Chinese slow/failure/retry sections.
- Retry/timeout fixtures are absent.
- Empty command log fixture is accepted.
- PASS operation rows do not trace back to command ids.
- A blocked real run is labeled PASS or has invented command evidence.
- stdout/stderr paths point outside run artifacts/logs without a sha256 fallback.

## Risks And Mitigations

- Risk: `_node_command(...)` first tries host socket commands via `_host_command`, so command coverage could miss probes. Mitigation: either wrap `_host_command` calls in the recorder as `valkey_protocol` commands or force all audited node commands through `run_node_cli` when a recorder is active.
- Risk: parallel setup can interleave writes. Mitigation: lock-protected sequence ids and buffered close.
- Risk: command output may be large. Mitigation: write stdout/stderr sidecar logs with sha256 and store only refs/hashes in JSONL.
- Risk: existing schema is permissive and older tests may rely on it. Mitigation: update fixtures/tests together and preserve legacy skipped behavior only where no runtime command log exists.
- Risk: cleanup runs in a second CLI process. Mitigation: state should carry `command_log_ref`; cleanup opens the same recorder in append mode.
- Risk: fault sandbox imports `run_docker` directly. Mitigation: add optional recorder parameters to `apply_fault`/`clear_fault`, not global monkeypatching.

## Worker Execution Plan

1. Add `command_recorder.py` and strict schemas.
2. Wire recorder through CLI `gate scenario`, `gate cleanup`, `fault apply`, and `fault clear`.
3. Record command rows in central wrappers and semantic call sites.
4. Add command refs to operation rows, cleanup actions, and fault reports.
5. Add fixtures for success/failure/timeout/retry/cleanup_residual/empty.
6. Add analysis aggregation and missing-metric handling.
7. Add Chinese report CSV/SVG/Markdown/HTML sections and report index inputs.
8. Add command-log gate and tests.
9. Generate M1-S03 run artifacts, attempt real gate, record blocked reason if needed.
10. Update coverage matrix and worker summary.
