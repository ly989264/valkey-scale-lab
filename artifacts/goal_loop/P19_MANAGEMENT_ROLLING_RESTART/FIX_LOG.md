# FIX_LOG - P19_MANAGEMENT_ROLLING_RESTART

## Fix 1 - Harness Lock Drift After Strengthening

- Failing command: `python3 scripts/codex_gate.py precheck --phase P19_MANAGEMENT_ROLLING_RESTART`
- Failure: `codex/gate_lock.json` detected intentional changes to `scripts/assert_management_ops_coverage.py`, `schemas/artifact/rolling_restart_plan.schema.json`, and `schemas/artifact/rolling_restart_result.schema.json`.
- Cause: P19 needed stronger fail-closed checks for exact 6/10 rolling restart rows, one-node-at-a-time execution, inter-node health gates, replica-first ordering, owned-container restart command evidence, and plan/result schema fields.
- Fix: wrote `artifacts/harness_exception/P19_MANAGEMENT_ROLLING_RESTART.md` and updated only the three corresponding lock hashes.
- Verification: `python3 scripts/codex_gate.py precheck --phase P19_MANAGEMENT_ROLLING_RESTART` passed.

## Fix 2 - Sandbox Port Probe

- Failing command: `python3 scripts/codex_gate.py run --phase P19_MANAGEMENT_ROLLING_RESTART`
- Failure: real Valkey setup failed with `port 127.0.0.1:7100 is not available: [Errno 1] Operation not permitted`.
- Cause: sandboxed execution could not perform the local port bind/probe required by the real Docker gate.
- Fix: reran the same gate command outside the sandbox with escalation for owned Docker containers and local ports.
- Verification: real Valkey e2e gate reached PASS.

## Fix 3 - Phase Summary Missing-Metric Shape

- Failing command: `python3 scripts/codex_gate.py run --phase P19_MANAGEMENT_ROLLING_RESTART`
- Failure: `scripts/assert_quant_artifacts.py` rejected `phase_summary.missing_metrics[*]` because entries used `field` rather than the schema-required `metric` key.
- Cause: P19 reused per-node `missing_fields` entries directly in `phase_summary.missing_metrics`.
- Fix: added `_p19_phase_missing_metrics()` so per-node result artifacts keep `field`, while phase summary emits schema-valid `{metric, status, reason, impact}` entries.
- Verification: `PYTHONPYCACHEPREFIX=/tmp/vslab-p19-pycache python3 -m compileall -q src scripts`, `python3 -m pytest -q tests/unit tests/integration`, and the full P19 gate all passed.

## Final Gate

- Command: `python3 scripts/codex_gate.py run --phase P19_MANAGEMENT_ROLLING_RESTART`
- Result: PASS
- Gate result: `artifacts/gates/P19_MANAGEMENT_ROLLING_RESTART/gate_result.json`
- Gate result SHA256: `5476e8c136cae4a8465add35fed40320827c5fd74869ecad42a8db092e5dfbf1`
