# Harness Exception — P20_FAILOVER_LATENCY_CURVE_30_50_100

## Defect

The locked failover harness only executed one primary-stop failover sample for a single setup scenario. P20 requires real failover latency curves for exactly 30, 50, and 100 node rungs with at least three fresh real Valkey samples per rung. The previous harness shape could not produce the required `failover_latency_samples.jsonl`, `failover_latency_curve.json`, canonical quant artifacts, workload impact report, or per-rung resource preflight evidence.

The locked assertions also validated only minimal sample counts and schema shape. They did not reject reused sample IDs/state references, downshifted 100-node evidence, missing cleanup references, missing workload references, or curve statistics that were not derived from raw samples.

## Patch

The patch strengthens the existing harness:

- `scripts/fault_failover_gate.py` now expands P20 `failover_curve_30_50_100` into 30, 50, and 100 node rungs with three fresh single-sample real failover runs per rung.
- The P20 controller writes normalized resource preflight artifacts and blocks with a nonzero exit plus `BLOCKED.md` if any rung cannot run.
- The controller aggregates child real gate outputs into P20 required artifacts, including raw samples, derived curve, quant events/metrics, workload impact, fault matrix, aggregate cleanup, and phase summary.
- `scripts/assert_failover_latency_curve.py` now requires exact P20 rung coverage, unique sample/run/state refs, real-Valkey status, cleanup refs, workload refs, ordered timestamps, timestamp-derived latency values, and curve statistics derived from raw samples.
- `scripts/assert_quant_artifacts.py` and `scripts/assert_workload_impact.py` now add P20-specific traceability checks while preserving previous phase behavior.
- `src/valkey_scale_lab/runtime/docker_runtime.py` only permits P20 `scale_30_sample_NN`, `scale_50_sample_NN`, and `scale_100_sample_NN` aliases through the existing process runtime.

## Before / After

Before: P20 could not be satisfied by the locked gate because it produced one failover sample and no required curve/quant/workload aggregate artifact set. The assertions could not prove that samples were fresh, exact-rung, cleaned up, or statistically derived.

After: P20 requires nine real child runs, exact 30/50/100 rung preflight, raw sample provenance, aggregate cleanup, workload impact traceability, and derived curve validation. Resource insufficiency is encoded as a blocking failure rather than a pass.

## Verification

- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_scale_lab_pycache python3 -m compileall -q scripts src tests/unit/test_goal_loop_assertions.py tests/failover/test_failover_contract.py`
- `python3 -m pytest -q tests/unit/test_goal_loop_assertions.py tests/failover/test_failover_contract.py`
- `python3 -m pytest -q tests/ci/test_fault_failover_scale_gate.py`
- `python3 scripts/safety_scan.py`
