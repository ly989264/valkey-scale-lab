# H01 Design Brief

role: design
agent_invocation: real_subagent
stage_id: H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET
source_commit_before: c6e5fcdb18b1d4960c613f84a53b8c90109cc019

## Summary

H01 should create a current hardening acceptance reset from `runs/m1-hardening/evidence_manifest.json`. The reset must be C03-shaped, set `milestone1_status: BLOCKED_WITH_REASON`, set `false_pass_prevented: true`, include all 29 required claims, and record the old M1-S09 PASS report as superseded suspect input. Do not use fixture or legacy evidence for PASS.

## Key Findings

- The hardening manifest has all 29 C04 claim ids and no PASS claims: 29 are `BLOCKED_WITH_REASON`.
- The old M1-S09 acceptance report still says `milestone1_status: PASS` while listing fixture sources and PASS rows with `SKIPPED_WITH_REASON` metric/report fields.
- `scripts/assert_milestone1_acceptance.py` still contains fixture fallbacks and shallow non-empty checks at lines 80-86, 94-106, 144-161, and 247-260.
- H01 should not soften `assert_no_legacy_m1_pass.py`; it should make that gate pass by producing a valid current blocked reset artifact.

## Exact Recommendations

1. Add `scripts/m1h/build_acceptance_reset.py` or equivalent, reading the generated manifest and writing:
   `runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/artifacts/milestone1_acceptance_reset.json`.

2. The reset should contain `hardening_loop_status: PASS`, `milestone1_status: BLOCKED_WITH_REASON`, `false_pass_prevented: true`, `required_claim_count: 29`, `passed_claim_count: 0`, `blocked_claim_count: 29`, `failed_claim_count: 0`, and all claim reasons.

3. Update `assert_no_legacy_m1_pass.py` so H01 validates the reset as the current acceptance output and treats the old M1-S09 PASS report only as a superseded historical input.

4. Make `assert_stage_exit.py` stage-aware so H01 requires H01 gate artifacts, including the reset gate result, instead of only the H00 gate list.

5. Harden or quarantine `scripts/assert_milestone1_acceptance.py`; fixture fallback and fixture scale coverage must not remain in any PASS-capable hardening acceptance path.

6. Add tests proving blocked reset generation, old-report supersession, fixture/legacy PASS rejection, missing-reason rejection, and H01 stage-exit requirements.

## Gate Sequence

```text
python3 scripts/m1h/build_evidence_manifest.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET --out runs/m1-hardening/evidence_manifest.json
python3 scripts/m1h/build_acceptance_reset.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET --manifest runs/m1-hardening/evidence_manifest.json --out runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/artifacts/milestone1_acceptance_reset.json
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET --acceptance-report runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/artifacts/milestone1_acceptance_reset.json --historical-acceptance-report runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET
python3 scripts/m1h/assert_stage_exit.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET
```

## Acceptance Criteria

H01 passes only when the current hardening output is blocked with reasons and the old PASS is visibly superseded. A milestone PASS from fixture, legacy, skipped, shallow-count, invalid, or blocked evidence must remain impossible.
