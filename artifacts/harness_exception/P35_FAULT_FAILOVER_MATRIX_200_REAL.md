# Harness Exception - P35_FAULT_FAILOVER_MATRIX_200_REAL

## Reason

P35 required additive changes to protected harness scripts under `scripts/*.py` so the existing strict fault/failover gate and quant completeness assertion recognize the real exact-200 stage instead of failing dispatch or omitting P35 strict fault semantics.

A fresh review then found an additional strict artifact defect: primary-stop failover samples in `failover_samples.jsonl` omitted the `coverage_id` field required by `docs/codex/goal-loop-strict/09_FAULT_FAILOVER_MATRIX_SPEC.md`. The harness was strengthened again so generated samples include `coverage_id` and `scripts/assert_quant_completeness.py` rejects missing or wrong primary-stop sample coverage IDs.

## Files Strengthened

- `scripts/fault_failover_gate.py`
- `scripts/assert_quant_completeness.py`

## Before

- `scripts/fault_failover_gate.py` had strict fault profiles only for P33/P34.
- `P35_FAULT_FAILOVER_MATRIX_200_REAL` with scenario `strict_fault_matrix_200_fault_failover` failed closed because no profile existed.
- `scripts/assert_quant_completeness.py` validated strict fault quant semantics only for P33/P34.

## After

- P35 has an explicit strict fault profile using `templates/configs/scale_200.yaml`, setup scenario `strict_fault_matrix_200`, wrapper scenario `strict_fault_matrix_200_fault_failover`, work dir `_p35_fault_matrix_work`, and state file `state_fault_matrix_200.json`.
- P35 setup and convergence timeouts are bounded profile values for exact 200 nodes, including a P35-only 1800s node-host/AZ convergence budget after restoring 100 stopped node processes.
- P35 resource preflight is invoked with explicit `--phase P35_FAULT_FAILOVER_MATRIX_200_REAL --scenario strict_fault_matrix_200`.
- P35 quant completeness requires scale `200`, prefix `200.fault.`, all 12 strict fault rows, and at least 3 failover samples.
- Primary-stop failover sample records now include `coverage_id=200.fault.primary_stop_failover`.
- Quant completeness now verifies each strict failover sample records the expected primary-stop coverage ID.
- The strict fault matrix wrapper removes the P35 work directory before setup so reruns cannot carry stale per-fault JSON/log artifacts into fresh evidence.
- P35 process restarts get one bounded retry, a short sustained-readiness window, and a longer clear subprocess timeout; each retry still requires a numeric pid file and live `PING` before recording PASS.

## Safety

No harness requirement was weakened. Phase state, gate result, manifest, schema, and audit decision files were not edited to force a pass. `codex/gate_lock.json` was updated only to record the strengthened `scripts/fault_failover_gate.py` and `scripts/assert_quant_completeness.py` hashes after precheck failed closed. The 200-node allowance remains exact-stage and exact-scenario only, and fault clears remain fail-closed unless the restarted process answers live Valkey probes.
