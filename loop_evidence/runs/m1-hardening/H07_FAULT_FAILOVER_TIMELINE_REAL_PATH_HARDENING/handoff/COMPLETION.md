# H07 Completion

stage_id: H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING
status: PASS
source_commit_before: 3c2579c123bf498b2a8d1ea16a6eb8e31647a720
source_commit_after: PENDING_COMMIT

## Summary

H07 hardens fault/failover timeline claims so 50/100/200-node fault timeline PASS requires a same-directory exact-scale C09 bundle with real Valkey 9.1.x evidence, required fault types, required lifecycle events, numeric timeline metrics, H06-strength workload impact references, cleanup proof, and no fake, fixture, partial, dry-run, or legacy promotion.

Current repository fault timeline claims remain `BLOCKED_WITH_REASON` because complete exact-scale C09 fault timeline bundles are absent. This is the expected fail-closed state: H07 passes by preventing unsafe promotion, not by inventing unavailable real evidence.

## Implemented Checks

- fault timeline claim promotion now depends on the H07 evaluator accepting the underlying C09 artifact bundle;
- required fault types include primary stop failover, replica stop, node-host stop, AZ stop, network delay, packet loss, flap, partition, minority partition, majority partition, split-brain-window detection, and fault-period workload impact;
- required lifecycle events must be observed for each accepted sample, from fault planning through cleanup verification;
- required timing and impact metrics must be numeric and non-negative; missing and skipped core metrics cannot promote PASS;
- report, event, latency sample, workload, metrics, cleanup, and Valkey evidence files must resolve in one same-directory bundle;
- fault workload impact must depend on H06-accepted workload benchmark evidence;
- cleanup evidence must be PASS with no remaining resources;
- fake, fixture, partial, dry-run, and legacy fault evidence remains blocked with explicit reasons;
- crafted manifest-only PASS claims without `diagnostics.fault_h07_acceptance.accepted: true` are rejected by `assert_fault_timeline_real.py`;
- H07 stage exit requires `assert_fault_timeline_real`.

## Gates

- `PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h07 python3 -m compileall -q scripts src tests` -> PASS
- `python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h` -> PASS, 308 passed
- `python3 -m pytest -q tests/m1h/test_gate_framework.py -k 'fault_timeline or h07'` -> PASS, 12 passed
- `python3 scripts/m1h/build_evidence_manifest.py --stage H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING --out runs/m1-hardening/evidence_manifest.json` -> PASS
- `python3 scripts/m1h/assert_evidence_taxonomy.py --stage H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING` -> PASS
- `python3 scripts/m1h/assert_fault_timeline_real.py --stage H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING` -> PASS
- `python3 scripts/m1h/assert_no_fixture_fallback.py --stage H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING` -> PASS
- `python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING` -> PASS
- `python3 scripts/m1h/assert_no_simulated_subagents.py --stage H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING` -> PASS
- `python3 scripts/m1h/assert_stage_exit.py --stage H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING` -> PASS

## Review

First real review subagent returned `Decision: FAIL` after finding a manifest-only false-PASS path. The finding was fixed by requiring `fault_h07_acceptance.accepted is True` for every PASS claim and adding regression coverage.

Fresh real review subagent returned `Decision: PASS` and verified the prior crafted manifest-only PASS now fails with `fault_pass_h07_not_accepted`.

## Commit And Push

commit: PENDING_COMMIT
push: PENDING_PUSH
