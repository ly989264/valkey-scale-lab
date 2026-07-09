# 14_GIT_PROTOCOL.md

## Commit and push rules

- Every stage must commit exactly the stage work unless a BLOCKED stop prevents code changes.
- Commit message must start with the stage id.
- Push must succeed before moving to the next stage.
- Do not amend previous stage commits unless explicitly instructed by the user.
- Do not squash away evidence artifacts required by the hardening loop.

## Dirty tree rule

The review subagent must inspect `git status` and `git diff --stat`. A stage may not pass with unexplained dirty changes.
