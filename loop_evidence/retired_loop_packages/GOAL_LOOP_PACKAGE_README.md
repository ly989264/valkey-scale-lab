# valkey-scale-lab Goal Loop Markdown Package

This package is a Markdown-only control pack for starting a Codex App Goal-mode loop against `ly989264/valkey-scale-lab`, default branch `codex/valkey-scale-lab-loop`.

## Placement

Unzip this package at the repository root. The package intentionally contains only `.md` files. It does not contain shell scripts, JSON, YAML, Python, or generated artifacts.

Expected high-impact files after placement:

```text
AGENTS.md
CODEX_START_HERE.md
CODEX_GOAL_LOOP_START.md
docs/codex/goal-loop/**/*.md
```

`AGENTS.md` and `CODEX_START_HERE.md` are intended replacements for the existing bootstrap guidance. They preserve the current safety rules and add the new management/fault/quantification loop.

## How this package is meant to be used

1. Place the Markdown files.
2. Commit the documentation/bootstrap change manually or let the first Codex stage do it after it has run the existing static harness checks.
3. Open Codex App in the project root.
4. Select Goal mode.
5. Paste the contents of `docs/codex/goal-loop/prompts/GOAL_MODE_START_PROMPT.md`.
6. Keep Docker available. Permit project-local file edits, project-local test execution, Docker commands, and Git commit/push. Do not approve host-level networking, host firewall/routing mutation, or unrelated process control.

## Design intent

The pack turns the existing phase loop into a stronger stage loop with these properties:

- every stage starts by rereading the stage documents;
- every stage uses a design subagent, a worker subagent, and a review subagent;
- stage state is written to structured Markdown handoff files so context compaction cannot erase the contract;
- no stage may commit or push until gates, artifacts, and review pass;
- remove/reshard/rebalance/rolling restart are treated as real management operations with quantitative evidence;
- fault scenarios include failover latency curves at 30/50/100/200 nodes, replica stop, host/AZ stop, network delay/loss/partition/flap, minority/majority partition, split-brain window, and workload QPS/latency/error impact.
