# H02 Design Brief

role: design
agent_invocation: real_subagent
stage_id: H02_ACCEPTANCE_GATE_FAIL_CLOSED
source_commit_before: 577b37d3aaadc5bc87f81090b02014133d318b1f

## Summary

H02 should turn the H01 blocked reset into reusable final acceptance logic. The gate should pass the hardening loop when it honestly prevents a false milestone PASS, while reporting `milestone1_status: BLOCKED_WITH_REASON` until every required exact-scale C04 claim is promotable.

## Key Findings

- Current hardening manifest: 29 required C04 claims, 0 PASS, 29 blocked with reasons.
- H01 reset: C03-shaped, `hardening_loop_status: PASS`, `milestone1_status: BLOCKED_WITH_REASON`, `false_pass_prevented: true`.
- Historical M1-S09 report still says PASS and contains fixture sources plus skipped metric/report fields in PASS rows; it must remain superseded historical input only.
- `assert_final_milestone1_hardened.py` does not yet enforce the exact C04 id set, full C03 claim ledger, PASS semantic checks, fixture exclusion, blocked reasons, or count consistency.
- `assert_stage_exit.py` does not yet know H02 and would not require the final acceptance gate result or an H02 acceptance artifact.

## Exact Recommendations

1. Reuse/generalize the H01 acceptance builder so H02 writes:
   `runs/m1-hardening/H02_ACCEPTANCE_GATE_FAIL_CLOSED/artifacts/milestone1_acceptance_report.json`.

2. Make PASS promotion require:
   promotable evidence kind, complete M1 fields, hardening-stage acceptance, exact-scale observation, all capability-required semantic checks, and no fixture source paths.

3. Make `assert_final_milestone1_hardened.py` validate the C03/C04 ledger and write gate status `PASS` when the hardening logic is correct, even if `milestone1_status` remains `BLOCKED_WITH_REASON`.

4. Make malformed ledgers, missing required claims, non-promotable PASS, legacy-only PASS, fixture-backed PASS, skipped-core-metric PASS, or count mismatch produce gate `FAIL`.

5. Route `scripts/assert_milestone1_acceptance.py` through the same shared builder/validator so there is only one acceptance implementation.

6. Add H02 defaults to `assert_no_legacy_m1_pass.py`, using the H02 acceptance artifact as current acceptance and the old M1-S09 report only as superseded historical input.

7. Extend `assert_stage_exit.py` so H02 requires `build_evidence_manifest`, `assert_evidence_taxonomy`, `assert_final_milestone1_hardened`, `assert_no_fixture_fallback`, `assert_no_legacy_m1_pass`, `assert_no_simulated_subagents`, and the H02 C03 acceptance artifact.

8. Add regression tests for empty/missing-claim manifests, honest blocked acceptance, fixture-backed PASS rejection, legacy/non-promotable PASS rejection, semantic-check failures, and H02 stage-exit requirements.

## Gate Sequence

```text
PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache python3 -m compileall -q scripts src tests
PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h
python3 scripts/m1h/build_evidence_manifest.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED --out runs/m1-hardening/evidence_manifest.json
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED
python3 scripts/m1h/assert_final_milestone1_hardened.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED
python3 scripts/m1h/assert_stage_exit.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED
```

## Acceptance Criteria

H02 passes only when the current H02 acceptance ledger is machine-validated, all 29 C04 claims are represented, the final hardening gate exits 0 with milestone status blocked for the current evidence, and no fixture, legacy-only, skipped metric, non-empty, invalid, or blocked evidence can promote a required claim to milestone PASS.
