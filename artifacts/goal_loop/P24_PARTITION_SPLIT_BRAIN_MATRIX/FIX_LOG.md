# FIX_LOG - P24_PARTITION_SPLIT_BRAIN_MATRIX

## Review failure addressed

Fresh-context review initially returned `Decision: FAIL` because P24 workload artifacts underreported `CLUSTERDOWN` errors as `unknown_error_count` and because `all_run` windows had successful operations while latency percentiles were marked `MISSING` with a false no-success reason.

## Fixes

- Updated `scripts/fault_safety_gate.py` so `workload_metrics()` accepts explicit error taxonomy counts while preserving existing callers.
- Updated P24 workload collection to classify `CLUSTERDOWN`, `READONLY`, `TRYAGAIN`, connection, timeout, and unknown errors separately.
- Added a P24-specific `all_run` aggregate that derives latency percentiles from successful child-window operation samples.
- Strengthened `scripts/assert_workload_impact.py` so P24 fails when error taxonomy counts do not equal `error_ops`, `CLUSTERDOWN` samples are not counted, or `all_run` latency is missing despite successful operations.
- Updated `codex/gate_lock.json` for the intentionally strengthened locked harness files.

## Verification

- `PYTHONPYCACHEPREFIX=/tmp/valkey_scale_lab_pycache python3 -m py_compile scripts/fault_safety_gate.py scripts/assert_workload_impact.py` -> PASS
- `python3 -m pytest -q tests/unit/test_goal_loop_assertions.py -k P24` -> PASS
- `python3 scripts/codex_gate.py run --phase P24_PARTITION_SPLIT_BRAIN_MATRIX` -> PASS
- `python3 scripts/assert_workload_impact.py --phase P24_PARTITION_SPLIT_BRAIN_MATRIX` -> PASS

## Artifact evidence after regeneration

- Minority event windows now record `cluster_down_error_count=6` and `unknown_error_count=0` for the observed `CLUSTERDOWN` workload failures.
- All six `all_run` windows now include derived `latency_p50_ms`, `latency_p95_ms`, and `latency_p99_ms` when `ok_ops > 0`.
