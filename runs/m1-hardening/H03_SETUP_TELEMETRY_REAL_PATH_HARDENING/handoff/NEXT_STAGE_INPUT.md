# Next Stage Input

next_stage_id: H04_COMMAND_AUDIT_REAL_PATH_HARDENING
previous_stage_status: PASS
previous_review_decision: PASS
previous_stage_commit: PENDING_COMMIT
previous_stage_pushed: PENDING_PUSH

## Inputs To Reload

- `runs/m1-hardening/evidence_manifest.json`
- `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/handoff/CONTEXT_RELOAD.md`
- `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/handoff/DESIGN_BRIEF.md`
- `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/handoff/WORKER_SUMMARY.md`
- `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/handoff/REVIEW.md`
- `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/handoff/COMPLETION.md`
- `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/artifacts/gates/*.json`

## Required H04 Focus

H04 must harden command audit exact-scale claims so setup/management command evidence requires real non-empty command logs, required command kinds, stdout/stderr refs or hashes, retry/failure/timeout summaries, and operation traceability.
