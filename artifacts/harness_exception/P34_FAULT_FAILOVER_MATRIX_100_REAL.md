# Harness Exception — P34_FAULT_FAILOVER_MATRIX_100_REAL

## Trigger

`python3 scripts/codex_gate.py precheck --phase P34_FAULT_FAILOVER_MATRIX_100_REAL` failed because P34 intentionally strengthened locked harness scripts. The failure was a gate-lock hash mismatch, not a runtime evidence failure.

## Locked Files Strengthened

| Path | Reason |
|---|---|
| `scripts/fault_failover_gate.py` | Generalized the strict fault/failover controller so P34 routes to an exact 100-node real Valkey matrix instead of the legacy primary-stop path. |
| `scripts/assert_quant_completeness.py` | Added strict P34 fault telemetry semantics for `100.fault.*` rows, exact scale 100, all required rows, workload windows, and minimum failover sample count. |

## Before Behavior

The P34 manifest already called `strict_fault_matrix_100_fault_failover`, but the strict fault controller and quant assertion were P33 exact-50 only. P34 would not produce the required strict artifact family or enforce strict fault quant completeness at scale 100.

## After Behavior

P34 now fails closed unless it uses `templates/configs/scale_100.yaml`, `--min-nodes 100`, exact 100-node runtime setup, `100.fault.*` coverage IDs, three primary-stop failover samples, strict fault artifacts, sandbox-scoped network faults, and deterministic cleanup. P33 remains supported through the exact-50 profile, and P35 remains unavailable until its own stage.

## Verification Before Lock Refresh

| Command | Result |
|---|---:|
| `PYTHONPYCACHEPREFIX=/tmp/vslab-p34-pycache python3 -m compileall -q scripts/fault_failover_gate.py scripts/assert_quant_completeness.py src/valkey_scale_lab/runtime/docker_runtime.py tests/unit/test_goal_loop_assertions.py tests/integration/test_docker_runtime_contract.py` | PASS |
| `PYTHONPYCACHEPREFIX=/tmp/vslab-p34-pycache python3 -m pytest -q -p no:cacheprovider tests/unit/test_goal_loop_assertions.py tests/integration/test_docker_runtime_contract.py tests/failover/test_failover_contract.py` | PASS: 124 passed |
| `python3 scripts/safety_scan.py` | PASS |

## Integrity Decision

This exception preserves the original harness requirement and makes P34 stricter. No gate result, phase state, audit decision, or coverage registry row was manually edited.
