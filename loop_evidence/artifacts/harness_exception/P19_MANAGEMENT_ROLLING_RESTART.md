# Harness Exception - P19_MANAGEMENT_ROLLING_RESTART

## Defect

The pre-existing P19 rolling restart harness was too weak for the stage contract. `scripts/assert_management_ops_coverage.py` named the P19 operation types but did not require the exact 6-node and 10-node rows, did not validate `rolling_restart_plan.json` or `rolling_restart_results.jsonl`, and could not reject all-at-once restart evidence or missing inter-node health gates. The rolling restart schemas also accepted very loose artifacts that did not require operation identity, sequence numbers, per-node health gate timing, command references, or role/order evidence.

## Patch

The P19 implementation strengthens the harness instead of bypassing it:

- `scripts/assert_management_ops_coverage.py` now requires exact P19 rows for `rolling_restart_replica_first` and `rolling_restart_primary_safe` at 6 and 10 nodes.
- The assertion validates `rolling_restart_plan.json`, `rolling_restart_results.jsonl`, and `management_command_log.jsonl` together.
- The assertion rejects missing rows, missing plan/result entries, overlapping restarts, a next restart before the previous health gate completed, non-PASS health gates, missing owned Docker restart command evidence, `max_concurrent_restarts` other than `1`, and replica-first rows that restart a primary before all replicas.
- `schemas/artifact/rolling_restart_plan.schema.json` and `schemas/artifact/rolling_restart_result.schema.json` now require the fields needed for those checks while preserving additional properties for forward-compatible evidence.

## Before Behavior

A P19 row could pass the generic management operation shape with only operation names and broad timing fields. The harness did not prove deterministic order, one-node-at-a-time execution, command-backed container restarts, or inter-node health gates.

## After Behavior

P19 cannot pass unless all required 6-node and 10-node rows are present, every node restart has a matching plan entry, every restart points to a passing owned-container restart command, every health gate passes before the next restart starts, cluster state and slot coverage recover after each node, and replica-first ordering is preserved.

## Lock Update

`codex/gate_lock.json` was updated transparently for the strengthened harness files:

- `schemas/artifact/rolling_restart_plan.schema.json`: `067dcebd2006e1ab5da0be691c106798ae1e220e3600417237d2a1b8031562b2`
- `schemas/artifact/rolling_restart_result.schema.json`: `0811ddf0a9e238db5f14786e097c109ebc477dba037e8e38e14c56ab0b3dd697`
- `scripts/assert_management_ops_coverage.py`: `6dae1c5de76702037915f4bc1e5672ec44f48dc1d2b9436ee733467dc357d463`
