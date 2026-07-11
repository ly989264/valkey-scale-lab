# FIX_LOG - P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE

## Main-Agent Verification Issue

After the worker handoff, the main-agent rerun of:

```bash
PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 scripts/p43_cluster_timeout_artifacts.py
```

failed because the sandboxed process could not access the Docker socket for resource preflight, and the resulting preflight artifact reported Docker unavailable plus occupied P43 ports.

## Resolution

The command was rerun with approved project-scoped escalation so the resource preflight could inspect Docker consistently with the real Valkey gate environment:

```bash
PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 scripts/p43_cluster_timeout_artifacts.py
```

Result: `PASS P43 cluster timeout artifacts`.

## Code Changes

No code changes were needed for this issue. The failure was an execution-permission mismatch during main-agent verification, not a P43 implementation defect.

## Fresh Review Findings

The first fresh-context review returned `Decision: FAIL` with three findings:

1. `fault_failover_gate.py` still used a parser default instead of resolving the effective timeout from config, and legacy `--failover-node-timeout-ms` was not treated as CLI source.
2. `config_validation_report.schema.json` did not require the P43 timeout fields.
3. `codex/gate_lock.json` did not lock the newly added P43 harness-control files.

## Fixes Applied

- Updated `scripts/fault_failover_gate.py` to resolve timeout from `load_effective_config()` when no CLI timeout is supplied; `--timeout-config-ms` and legacy `--failover-node-timeout-ms` are now both CLI sources and are passed into setup so generated config and live `CONFIG SET` do not silently diverge.
- Added focused failover tests for global, scenario, and legacy CLI timeout resolution.
- Strengthened `schemas/artifact/config_validation_report.schema.json` so requested/effective/source timeout fields are required and source is constrained to `global`, `profile`, `scenario`, or `cli`.
- Added the new P43 stage document, assertion scripts, matrix runner, artifact builder, and schemas to `codex/gate_lock.json`, and refreshed hashes for strengthened locked files.

## Recheck

- `python3 scripts/codex_gate.py precheck --phase P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE`: PASS after lock update.
- The first full rerun exposed a scale-100 wrapper wait timeout even though the evidence file showed `nodes_observed=100` and `cluster_state_observed=ok`; the standalone rerun passed. The P43 manifest now gives the 100-node wrapper a 240-second cluster-observation window so the gate waits for the real condition instead of racing the larger local cluster startup.
- `python3 scripts/codex_gate.py run --phase P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE`: PASS after the manifest wait-window update, including 10/30/50/100/200 real Valkey gates, artifact builder, cluster timeout config assertion, hidden override assertion, and timeout matrix artifact assertion.

## Second Fresh Review Finding

The second fresh-context review returned `Decision: FAIL` with one finding:

1. P43 emitted `events.jsonl`, `metrics_timeseries.jsonl`, and `workload_windows.json`, but those telemetry artifacts were not valid against the repository schemas and were not covered by the P43 gate.

## Second Fix Applied

- Updated `scripts/p43_cluster_timeout_artifacts.py` to emit schema-valid event JSONL rows, metric sample JSONL rows, and a non-empty `all_run` workload window derived from P43 timeout evidence.
- Added explicit P43 schema gates for `events.jsonl`, `metrics_timeseries.jsonl`, and `workload_windows.json`.
- Added those telemetry artifacts to the P43 required-artifact manifest with their schemas.
- Refreshed `codex/gate_lock.json` for the strengthened builder and manifest.

## Second Recheck

- `python3 scripts/validate_json_schema.py --schema schemas/artifact/event.schema.json --instance artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/events.jsonl --jsonl`: PASS.
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/metric_sample.schema.json --instance artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/metrics_timeseries.jsonl --jsonl`: PASS.
- `python3 scripts/validate_json_schema.py --schema schemas/artifact/workload_windows.schema.json --instance artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/workload_windows.json`: PASS.
- `python3 scripts/codex_gate.py run --phase P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE`: PASS with the new telemetry schema gates included.
