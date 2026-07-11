role: design
agent_invocation: real_subagent
stage_id: H10_FINAL_HARDENING_ACCEPTANCE
source_commit_before: e9fc1d44a640b93ed777e400d447fc7d15018f31
source_commit_after: MISSING

# H10 Design Brief

Final acceptance should produce `runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/artifacts/milestone1_hardened_acceptance.json` and a passing `assert_final_milestone1_hardened` gate while keeping `milestone1_status: BLOCKED_WITH_REASON` unless every C04 exact-scale claim is truly promotable. Current evidence is blocked in multiple capabilities, so the expected honest result is hardening loop `PASS` plus milestone1 blocked with reasons.

## Exact Targets

- `scripts/m1h/assert_final_milestone1_hardened.py`: make H10 default to `milestone1_hardened_acceptance.json` and `artifact_type="milestone1_hardened_acceptance"`; keep H02 compatibility with `milestone1_acceptance_report`.
- `scripts/m1h/build_acceptance_reset.py`: derive C19 final lists from the existing claim ledger: `required_claims`, `passed_claims`, `blocked_claims`, `failed_claims`, `fixture_only_claims`, and `legacy_only_claims`.
- `scripts/m1h/assert_stage_exit.py`: add `H10_REQUIRED_GATE_RESULTS`, register `H10_FINAL_HARDENING_ACCEPTANCE`, require the hardened acceptance artifact, and validate it with `validate_acceptance_report(...)` plus C19 list/count checks.
- `tests/m1h/test_gate_framework.py`: add final-gate and stage-exit regressions for H10, including false-PASS cases with blocked claims, fixture paths, legacy-only evidence, skipped semantics, and rendered-only report backing.

## Required Gates

```text
python3 -m compileall -q scripts src tests
python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h
python3 scripts/m1h/build_evidence_manifest.py --stage H10_FINAL_HARDENING_ACCEPTANCE --out runs/m1-hardening/evidence_manifest.json
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H10_FINAL_HARDENING_ACCEPTANCE
python3 scripts/m1h/assert_final_milestone1_hardened.py --stage H10_FINAL_HARDENING_ACCEPTANCE
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H10_FINAL_HARDENING_ACCEPTANCE
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H10_FINAL_HARDENING_ACCEPTANCE
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H10_FINAL_HARDENING_ACCEPTANCE
python3 scripts/m1h/assert_stage_exit.py --stage H10_FINAL_HARDENING_ACCEPTANCE
```

Run stage exit before review only to confirm it blocks on missing review artifacts, then rerun after review for the final PASS.

## Handoff

H10 must write the normal agent/handoff files plus `FINAL_HANDOFF.md`, `COMPLETION.md`, `NEXT_STAGE_INPUT.md`, all gate JSONs, and the final hardened acceptance JSON. The handoff should point to machine artifacts and list blocked claims; it must not substitute prose for the gates.

## Main Risks

- H10 currently falls back to the H00 stage-exit gate set unless registered.
- The final gate currently writes the H02-style acceptance filename by default.
- The final artifact type must change without splitting the acceptance algorithm.
- A milestone PASS in the current repository is unlikely and should be treated as a red flag unless every exact-scale claim passes all semantic checks.
