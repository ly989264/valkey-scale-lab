# Next Stage Input

next_stage_id: H03_SETUP_TELEMETRY_REAL_PATH_HARDENING
previous_stage_status: PASS
previous_review_decision: PASS
previous_stage_commit: PENDING_COMMIT
previous_stage_pushed: PENDING_PUSH

## Inputs To Reload

- `runs/m1-hardening/evidence_manifest.json`
- `runs/m1-hardening/H02_ACCEPTANCE_GATE_FAIL_CLOSED/artifacts/milestone1_acceptance_report.json`
- `runs/m1-hardening/H02_ACCEPTANCE_GATE_FAIL_CLOSED/handoff/CONTEXT_RELOAD.md`
- `runs/m1-hardening/H02_ACCEPTANCE_GATE_FAIL_CLOSED/handoff/DESIGN_BRIEF.md`
- `runs/m1-hardening/H02_ACCEPTANCE_GATE_FAIL_CLOSED/handoff/WORKER_SUMMARY.md`
- `runs/m1-hardening/H02_ACCEPTANCE_GATE_FAIL_CLOSED/handoff/REVIEW.md`
- `runs/m1-hardening/H02_ACCEPTANCE_GATE_FAIL_CLOSED/handoff/COMPLETION.md`
- `runs/m1-hardening/H02_ACCEPTANCE_GATE_FAIL_CLOSED/artifacts/gates/*.json`

## Required H03 Focus

Setup telemetry exact-scale claims are currently blocked. H03 must enforce numeric core metrics for setup telemetry PASS and keep skipped or legacy-only setup fields blocked with reasons.
