# FIX_LOG - P21_FAILOVER_LATENCY_CURVE_200

## Review Failure

The first fresh-context audit returned `Decision: FAIL`.

Findings:

- `P21-AUDIT-001`: stale `BLOCKED.md` contradicted the later successful resource preflight and gate result.
- `P21-AUDIT-002`: review/audit artifacts were missing before the failed audit began.
- `P21-AUDIT-003`: nested sample stderr logs contained cleanup failures that were later salvaged by controller cleanup, making cleanup provenance ambiguous.

## Fixes

- Removed stale `artifacts/goal_loop/P21_FAILOVER_LATENCY_CURVE_200/BLOCKED.md`; P21 is no longer blocked because the latest `resource_preflight_200.json` and full gate result report `PASS`.
- Kept the failed review/audit artifacts as historical evidence until a fresh review overwrites them with a new decision.
- Strengthened `scripts/fault_failover_gate.py` cleanup retry behavior so sample-level cleanup waits between retry attempts and can close transient Docker/process stop timing races before child evidence is published.
- Preserved explicit cleanup retry provenance in cleanup reports when a retry is used.

## Required Re-Verification

- Recompute `codex/gate_lock.json` for `scripts/fault_failover_gate.py`.
- Rerun `python3 scripts/codex_gate.py precheck --phase P21_FAILOVER_LATENCY_CURVE_200`.
- Rerun `python3 scripts/codex_gate.py run --phase P21_FAILOVER_LATENCY_CURVE_200`.
- Launch a fresh review subagent after the new gate result.
- Proceed to postcheck only if the fresh review writes exact `Decision: PASS`.
