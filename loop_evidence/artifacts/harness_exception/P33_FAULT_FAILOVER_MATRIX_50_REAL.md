# Harness Exception — P33_FAULT_FAILOVER_MATRIX_50_REAL

## Trigger

`python3 scripts/codex_gate.py precheck --phase P33_FAULT_FAILOVER_MATRIX_50_REAL` failed because P33 intentionally strengthened locked harness scripts. The failure was a gate-lock hash mismatch, not a runtime evidence failure.

## Locked Files Strengthened

| Path | Reason |
|---|---|
| `scripts/fault_failover_gate.py` | Added the P33 exact-50 real Valkey fault/failover controller, strict artifact emission, cleanup handling, and sandbox-proxy network-fault path. |
| `scripts/assert_fault_matrix_strict.py` | Added exact-scale P33/P34/P35 fault matrix checks for 12 required rows, source evidence refs, cleanup proof, workload refs, partition refs, and split-brain refs. |
| `scripts/assert_failover_latency_curve.py` | Added exact-scale/min-sample validation for strict fault stages and derived latency curve consistency checks against raw samples. |
| `scripts/assert_split_brain_report.py` | Added strict exact-scale split-brain detector validation for P33/P34/P35 while preserving the P24 path. |
| `scripts/assert_quant_completeness.py` | Added P33 strict fault semantics checks across phase artifacts, telemetry dimensions, coverage ledger, topology snapshots, command logs, cleanup, and quant summaries. |

## Before Behavior

The older failover and split-brain assertions were centered on P20/P21/P24 artifact shapes and did not provide a fail-closed exact-50 stage path for the strict P33 fault matrix. The Docker runtime did not admit the `strict_fault_matrix_50` scenario as an exact 50-node real execution path.

## After Behavior

P33 now fails closed unless it proves an exact 50-node real Valkey stage with the strict fault matrix, failover samples, workload impact windows, partition/split-brain reports, schema-valid phase artifacts, and deterministic cleanup. The lock refresh records the strengthened harness baseline after compile, focused tests, and safety scan.

## Verification Before Lock Refresh

| Command | Result |
|---|---:|
| `PYTHONPYCACHEPREFIX=/tmp/vslab-p33-pycache python3 -m compileall -q scripts src` | PASS |
| `python3 -m pytest -q tests/fault tests/failover` | PASS: 17 passed, 2 skipped |
| `python3 -m pytest -q tests/unit/test_goal_loop_assertions.py tests/integration/test_docker_runtime_contract.py` | PASS: 118 passed |

## Integrity Decision

This exception preserves the original harness requirement and makes P33 stricter. No gate result, phase state, or audit decision was manually edited.
