# H10 Input

previous_stage: H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING
previous_status: PASS
previous_commit: PENDING_COMMIT

## Carry Forward

Report input-quality claims now fail closed. H10 can rely on H09 semantics when running final hardening acceptance: milestone1 must remain `BLOCKED_WITH_REASON` unless all exact-scale source capability claims and report source-quality claims are promotable real M1H evidence.

For H10 final hardening acceptance, pay special attention to:

- milestone1 PASS must require exact-scale real evidence for every required capability;
- current blocked claims are acceptable only when encoded as `BLOCKED_WITH_REASON` with concrete reasons;
- legacy-only, fixture-only, skipped core metrics, rendered-only report inputs, fake/partial fault timelines, and weak non-empty checks must not promote;
- final gates should verify both the evidence manifest and the milestone acceptance surface;
- H10 should not rerun milestone1 from scratch or invent unavailable exact-scale evidence.

Required H09 artifacts:

- `runs/m1-hardening/H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING/artifacts/gates/assert_report_input_quality.json`
- `runs/m1-hardening/H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING/handoff/REVIEW.md`
- `runs/m1-hardening/evidence_manifest.json`
