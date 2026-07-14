# 10_AUDIT_AND_COMMIT_POLICY.md — Review, Mark-Complete, Commit, and Push

## Review is mandatory

Every stage must have a fresh-context review before postcheck and mark-complete.

Review artifacts:

```text
artifacts/goal_loop/<STAGE_ID>/REVIEW.md
audit/<STAGE_ID>/AUDIT.md
audit/<STAGE_ID>/audit_decision.json
```

If existing `scripts/codex_gate.py postcheck` expects only the `audit/` paths, the main agent must create both the goal-loop review artifact and the existing audit artifacts.

## Review decision vocabulary

`Decision: PASS` means all stage requirements are met.

`Decision: FAIL` means at least one blocking issue exists.

Do not use ambiguous decisions such as `PASS_WITH_WARNINGS`. Non-blocking concerns can be listed under follow-up notes, but the decision must still be exactly `PASS` or `FAIL`.

## Commit policy

A stage commit is allowed only after:

1. `python3 scripts/codex_gate.py precheck --phase <STAGE_ID>` passes.
2. `python3 scripts/codex_gate.py run --phase <STAGE_ID>` passes.
3. Stage-specific assertion scripts pass.
4. Required artifacts exist and validate.
5. Review subagent writes `Decision: PASS`.
6. `python3 scripts/codex_gate.py postcheck --phase <STAGE_ID>` passes.
7. `python3 scripts/codex_gate.py mark-complete --phase <STAGE_ID>` passes.
8. `git status --short` shows only intentional stage files before commit.

## Push policy

After commit:

```bash
git status --short
git log -1 --oneline
git push
```

Write the commit hash and push result to `artifacts/goal_loop/<STAGE_ID>/COMPLETION.md`.

## Forbidden completion patterns

- Manually editing phase state to pretend a stage passed.
- Manually editing gate results to `PASS`.
- Committing after design but before implementation.
- Committing after worker implementation but before review.
- Combining two stage completions into one commit.
- Skipping push and moving to the next stage.
- Treating resource insufficiency as success.

## Blocked-stage policy

When a stage is blocked:

1. Write `artifacts/goal_loop/<STAGE_ID>/BLOCKED.md`.
2. Include the exact failing command, reason, and remediation options.
3. Do not run mark-complete.
4. Do not create a passing commit for that stage.
5. The main response must say the loop is blocked at that stage.

A blocked stage may still commit diagnostic documentation only if the user explicitly asks for that; by default, do not commit a blocked stage.
