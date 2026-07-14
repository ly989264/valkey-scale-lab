# 12_AUDIT_COMMIT_NO_BYPASS_POLICY.md — Audit, Commit, Push, and No-Bypass Policy

## Review is mandatory

Every strict stage must have:

```text
artifacts/goal_loop_strict/<STAGE_ID>/REVIEW.md
audit/<STAGE_ID>/AUDIT.md
audit/<STAGE_ID>/audit_decision.json
```

The review must be fresh-context and must cite the gate result path, gate result SHA, required artifacts, and coverage IDs.

## Commit eligibility

A stage commit is allowed only after:

```text
CONTEXT_RELOAD.md exists
DESIGN_BRIEF.md exists
WORKER_SUMMARY.md exists
gates pass
required artifacts exist and validate
review says Decision: PASS
audit decision JSON says PASS and fresh_context=true
postcheck passes
mark-complete passes
git status --short contains only intentional files
```

## Push eligibility

After commit:

```text
git status --short
git log -1 --oneline
git push
```

`COMPLETION.md` must record commit hash and push result.

## Forbidden completion patterns

```text
manually editing codex/status/phase_state.json
manually editing artifacts/gates/<STAGE_ID>/gate_result.json to PASS
using echo PASS or printf PASS as a gate
committing after design but before implementation
committing after implementation but before review
committing multiple stages together
continuing after a blocked stage as if it passed
using fake-only tests for real stages
using generated metrics without real source artifacts
replacing exact 200-node execution with 100 nodes
starting real clusters above 200
```

## Blocked-stage policy

When a stage is blocked:

1. Write `artifacts/goal_loop_strict/<STAGE_ID>/BLOCKED.md`.
2. Include the exact failing command, environment facts, and remediation options.
3. Do not run mark-complete.
4. Do not create a passing commit.
5. Stop the loop at the blocked stage.

Diagnostic commits for blocked stages require explicit human instruction. By default, do not commit a blocked stage.

## Final audit rule

P40 must fail if any required real 50/100/200 coverage ID is missing, blocked, skipped, fake, dry-run-only, or not tied to exact-scale real evidence.

P40 must fail if any >200 dry-run coverage ID has evidence of real runtime creation.
