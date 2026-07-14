# RUNBOOK_PLACE_AND_LAUNCH.md — Place Markdown Pack and Start Codex Goal Loop

## 1. Place files

Unzip the Markdown package at the repository root. It should place or replace only `.md` files.

Expected changed files include:

```text
AGENTS.md
CODEX_START_HERE.md
CODEX_GOAL_LOOP_START.md
docs/codex/goal-loop/**/*.md
```

Do not use a shell placement script. The zip is already laid out with repository-relative paths.

## 2. Open Codex App

Open the Codex App and select the repository root as the project folder.

Use Goal mode for this loop. Keep the work local unless you intentionally configured Codex cloud for this repository.

## 3. Paste the start prompt

Paste the full contents of:

```text
docs/codex/goal-loop/prompts/GOAL_MODE_START_PROMPT.md
```

## 4. Approvals

Approve repository-scoped edit/test/Docker/Git operations. Deny host-level networking, firewall/routing mutation, `sudo` network changes, unrelated process control, and 1000-node execution.

## 5. Monitor progress

Useful commands outside Codex:

```bash
python3 scripts/codex_gate.py next
git log --oneline -5
git status --short
```

Stage artifacts are under:

```text
artifacts/goal_loop/<STAGE_ID>/
artifacts/phases/<STAGE_ID>/
audit/<STAGE_ID>/
```

## 6. Stop condition

The loop should continue through `P26_FINAL_REPORT_REGRESSION`. It should stop early only on a real safety, resource, or gate failure, in which case it writes `BLOCKED.md` and does not mark the stage complete.
