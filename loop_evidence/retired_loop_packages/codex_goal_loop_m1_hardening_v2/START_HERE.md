# START_HERE: Milestone1 hardening v2

Read this file first, then read every file listed in `docs/00_INDEX.md`.

## Non-negotiable rule

Do not try to satisfy this loop by editing Markdown completion notes. The loop requires executable, fail-closed harness gates in the repository. The Markdown files in this package define those contracts; the worker agents must implement them in code, run them, and commit only after they pass.

## Initial repository assumptions

This package targets the repository after the earlier M1 loop, where `runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json` may claim `milestone1_status: PASS`. Treat that PASS as suspect until the new gates prove it.

## First action in Codex goal mode

1. Open `prompts/GOAL_MODE_START_PROMPT.md`.
2. Use its entire content as the goal prompt.
3. Do not skip H00. H00 creates the machine-checkable hardening gate framework used by all later stages.
