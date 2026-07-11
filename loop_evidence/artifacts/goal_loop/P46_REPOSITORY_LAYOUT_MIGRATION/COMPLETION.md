# COMPLETION - P46_REPOSITORY_LAYOUT_MIGRATION

## Stage

- Stage ID: `P46_REPOSITORY_LAYOUT_MIGRATION`
- Review: `artifacts/goal_loop/P46_REPOSITORY_LAYOUT_MIGRATION/REVIEW.md` (`Decision: PASS`)
- Audit: `audit/P46_REPOSITORY_LAYOUT_MIGRATION/audit_decision.json` (`decision: PASS`)

## Verification

- P46 gate: PASS, 9/9 gates.
- Full non-real suite: 637 passed, 2 skipped.
- Historical evidence: 17,555 files, 678,927,090 bytes, zero missing/changed/unexpected files.
- Evidence tree SHA-256: `6f4232a19be65c1e0d5da0d0c8521e36e26e3facf4429d132f7dee1f7461b31f`.
- Historical schema compatibility: 56 exact artifact bindings; mutations and unregistered artifacts fail closed.
- Postcheck: PASS.
- Mark-complete: `MARKED_COMPLETE P46_REPOSITORY_LAYOUT_MIGRATION`.

## Commit

- Commit hash: recorded by the stage commit containing this file.
- Commit message: `P46_REPOSITORY_LAYOUT_MIGRATION: separate project and loop evidence`
- Push result: recorded in the main-agent completion response after `git push`.

## Layout

- Runnable project: `project/`
- Historical/current loop evidence: `loop_evidence/`
- Root discovery entries: `.github`, `.gitignore`, `AGENTS.md`, and `README.md`
