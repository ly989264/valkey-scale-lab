# WORKER_SUMMARY - P21_FAILOVER_LATENCY_CURVE_200

## Scope implemented

- Added `templates/configs/scale_200.yaml` with 100 shards, one replica per shard, Valkey 9.1.0, sandbox networking, low non-zero workload, `default_max_nodes: 100`, and explicit P21 bounded-exception metadata.
- Added a narrow P21 resource-preflight exception in `src/valkey_scale_lab/resource.py`; all other real configs above 100 nodes remain rejected, and P21 records host facts, Docker details, runtime limits, port ranges, resource estimates, and non-dry-run status.
- Added P21 runtime admission in `src/valkey_scale_lab/runtime/docker_runtime.py` only for `P21_FAILOVER_LATENCY_CURVE_200/scale_200_sample_<n>` with exactly 200 nodes.
- Added a P21 controller to `scripts/fault_failover_gate.py`:
  - runs `resource_preflight_200.json` before samples;
  - writes `artifacts/goal_loop/P21_FAILOVER_LATENCY_CURVE_200/BLOCKED.md` and exits nonzero if preflight fails;
  - runs exactly three real 200-node sample scenarios on preflight PASS;
  - aggregates P21 events, metrics, workload impact, cleanup, failover/fault reports, 200-only curve, and combined 30/50/100/200 curve;
  - does not downshift, dry-run, or synthesize PASS evidence.
- Strengthened P21 assertions in `scripts/assert_failover_latency_curve.py`, `scripts/assert_quant_artifacts.py`, and `scripts/assert_workload_impact.py` so downshifted, fake, duplicate, missing-cleanup, bad timestamp, bad count, and bad combined-curve artifacts fail.
- Updated `scripts/safety_scan.py` with the same exact `scale_200.yaml` P21 exception while preserving the normal `>100` default-config rejection.
- Added focused tests for resource, runtime, curve assertion, quant assertion, and workload-impact assertion behavior.

## Harness controls

- Wrote `artifacts/harness_exception/P21_FAILOVER_LATENCY_CURVE_200.md` for the intentional locked harness changes.
- Updated `codex/gate_lock.json` hashes for changed locked scripts and the new `templates/configs/scale_200.yaml`.
- Did not edit `codex/phase_manifest.json`.

## Verification run

- `python3 -m compileall -q scripts src` passed with escalation because Python cache writes target `~/Library/Caches` outside the workspace sandbox.
- `python3 -m pytest -q tests/unit tests/integration` passed: 106 passed.
- `python3 -m pytest -q tests/scale/test_scale_ladder.py` passed: 6 passed.
- `python3 scripts/safety_scan.py` passed.
- `python3 scripts/codex_gate.py precheck --phase P21_FAILOVER_LATENCY_CURVE_200` passed.
- `python3 scripts/assert_goal_loop_stage.py --phase P21_FAILOVER_LATENCY_CURVE_200` passed.

## Not run

- Did not run the full P21 Docker gate. Main should run `python3 scripts/codex_gate.py run --phase P21_FAILOVER_LATENCY_CURVE_200`; if local resources are insufficient, the implemented controller should leave `resource_preflight_200.json`, write `BLOCKED.md`, and exit nonzero without fake PASS artifacts.
