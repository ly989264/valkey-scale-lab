# CODEX_GOAL_LOOP_START.md — Human-Visible Codex App Start File

Use this file when launching the Codex App Goal-mode loop.

## Launch summary

Goal: extend `valkey-scale-lab` with the missing cluster-management operation matrix, the missing fault/failover matrix, and comprehensive quantitative artifact collection under a strong, multi-stage, multi-agent harness.

Primary user requirements:

- remove, reshard, rebalance, and rolling restart must be implemented and measured;
- failover latency curves must cover 30/50/100/200 nodes;
- replica stop, node-host stop, AZ stop, network delay/loss/partition/flap, minority/majority partition, split-brain window, and fault-period workload QPS/latency/error changes must be implemented and measured;
- every stage must be protected by a strong harness;
- every stage must use main-agent orchestration plus design, worker, and review subagents;
- stage-to-stage and subagent-to-main transfer must happen through structured Markdown artifacts;
- no stage may commit/push until complete.

## Start prompt

Paste `docs/codex/goal-loop/prompts/GOAL_MODE_START_PROMPT.md` into Codex App Goal mode.

## Operator approvals

Approve only project-scoped operations:

- reading and editing repository files;
- running Python tests and harness scripts;
- running Docker commands for owned containers/networks/volumes;
- collecting logs from owned containers;
- committing and pushing stage commits.

Do not approve:

- host firewall, routing, or interface mutation;
- `sudo` network changes;
- killing unrelated host processes;
- modifying global OS services;
- running 1000-node execution.
