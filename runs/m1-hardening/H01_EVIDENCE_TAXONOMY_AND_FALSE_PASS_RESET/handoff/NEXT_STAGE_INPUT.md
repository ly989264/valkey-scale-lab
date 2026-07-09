# Next Stage Input

next_stage_id: H02_ACCEPTANCE_GATE_FAIL_CLOSED
previous_stage_status: PASS
previous_review_decision: PASS
previous_stage_commit: PENDING_COMMIT
previous_stage_pushed: PENDING_PUSH

## Inputs To Reload

- `runs/m1-hardening/evidence_manifest.json`
- `runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/artifacts/milestone1_acceptance_reset.json`
- `runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/handoff/CONTEXT_RELOAD.md`
- `runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/handoff/DESIGN_BRIEF.md`
- `runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/handoff/WORKER_SUMMARY.md`
- `runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/handoff/REVIEW.md`
- `runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/handoff/COMPLETION.md`
- `runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/artifacts/gates/*.json`

## Required H02 Focus

Make acceptance fail closed as a reusable gate, not just a reset artifact: required exact-scale M1-format claims must be the only path to milestone PASS, and blocked claims must remain blocked with reasons.
