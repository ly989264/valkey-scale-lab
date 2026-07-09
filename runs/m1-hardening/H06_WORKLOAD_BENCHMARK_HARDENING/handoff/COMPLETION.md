# H06 Completion

stage_id: H06_WORKLOAD_BENCHMARK_HARDENING
status: PASS
source_commit_before: 038bf1cf50aa04b1c575352e4f326eeb91886e74
source_commit_after: PENDING_COMMIT

## Summary

H06 hardens workload benchmark claims so 30/50/100/200-node workload PASS requires same-directory exact-scale M1-format real Valkey 9.1.x benchmark evidence satisfying the full C08 profile, window, metric, operation, connection, pipeline, and slot-coverage contract.

Current repository workload benchmark claims remain `BLOCKED_WITH_REASON` because available evidence is fixture-only at 30 nodes or legacy/incomplete at 50/100/200 nodes. Existing real phase workload artifacts do not prove the required C08 benchmark profile/window matrix, required metric depth, observed connection/pipeline evidence, and full-slot non-smoke coverage.

## Implemented Checks

- exact-scale real Valkey 9.1.x proof is required for workload benchmark claim promotion;
- workload candidate artifacts are evaluated as one same-directory bundle, preventing cross-phase splicing;
- `workload_windows.json` is schema-validated and must have `status: PASS`;
- required profiles are enforced: `smoke`, `uniform`, `hotspot`, `mixed_rw`, `write_heavy`, and `read_heavy`;
- required windows are enforced for every profile: `baseline`, `pre_event`, `event`, `recovery`, `post_recovery`, and `all_run`;
- required C08 metrics must be present and numeric in every profile/window;
- `metrics_timeseries.jsonl` must contain at least 648 core workload metric rows and cover every profile/window/metric tuple;
- skipped, missing, string, boolean, null, and structured placeholder core metrics cannot promote a real workload PASS;
- minimum operations per window, observed connection evidence, observed pipeline evidence, and full-slot coverage for non-smoke profiles are enforced;
- fixture-only, legacy-only, fake, partial, shallow, and weak non-empty workload evidence stays blocked with reasons;
- `assert_workload_benchmark_strength.py` now fails unsafe workload PASS but passes honest blocked evidence with H06 diagnostics;
- H06 stage exit requires `assert_workload_benchmark_strength`.

## Gates

- `PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h06 python3 -m compileall -q scripts src tests` -> PASS
- `python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h` -> PASS, 296 passed
- `python3 scripts/m1h/build_evidence_manifest.py --stage H06_WORKLOAD_BENCHMARK_HARDENING --out runs/m1-hardening/evidence_manifest.json` -> PASS
- `python3 scripts/m1h/assert_evidence_taxonomy.py --stage H06_WORKLOAD_BENCHMARK_HARDENING` -> PASS
- `python3 scripts/m1h/assert_workload_benchmark_strength.py --stage H06_WORKLOAD_BENCHMARK_HARDENING` -> PASS
- `python3 scripts/m1h/assert_no_fixture_fallback.py --stage H06_WORKLOAD_BENCHMARK_HARDENING` -> PASS
- `python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H06_WORKLOAD_BENCHMARK_HARDENING` -> PASS
- `python3 scripts/m1h/assert_no_simulated_subagents.py --stage H06_WORKLOAD_BENCHMARK_HARDENING` -> PASS
- `python3 scripts/m1h/assert_stage_exit.py --stage H06_WORKLOAD_BENCHMARK_HARDENING` -> PASS

## Review

Real review subagent returned `Decision: PASS`.

## Commit And Push

commit: PENDING_COMMIT
push: PENDING_PUSH
