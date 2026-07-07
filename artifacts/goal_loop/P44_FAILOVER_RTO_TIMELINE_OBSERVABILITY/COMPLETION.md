# COMPLETION - P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY

## Stage

- Stage ID: P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY
- Review decision path: `artifacts/goal_loop/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/REVIEW.md`
- Audit decision path: `audit/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/audit_decision.json`

## Verification

- Gate command: `python3 scripts/codex_gate.py run --phase P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY`
- Gate result: PASS
- Gate result path: `artifacts/gates/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/gate_result.json`
- Gate result SHA256: `a7dd9770c88bfccc3eb0f9eb018960004c8bed1c444ed3c4468be86117a31f67`
- Real evidence: single-primary failover timeline samples for 10, 30, 50, 100, and 200 nodes.
- Valkey evidence: live Valkey version `9.1.0` recorded in `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/valkey_e2e_evidence.json`.
- Cleanup evidence: aggregate cleanup PASS with no remaining owned resources.

## Completion

- Postcheck command: `python3 scripts/codex_gate.py postcheck --phase P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY`
- Postcheck result: PASS
- Mark-complete command: `python3 scripts/codex_gate.py mark-complete --phase P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY`
- Mark-complete result: `MARKED_COMPLETE P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY`
- Commit hash: pending stage commit.
- Push result: pending stage push.

## Notes

P44 separates `kill_to_client_recovered_ms` from `pfail_to_cluster_ok_ms`, preserves clean-snapshot tail as its own metric, derives workload-window metrics from continuous client probes, and keeps greater-than-200 coverage as dry-run projection only.
