# Codex App Goal-Mode Start Prompt

You are in the `valkey-scale-lab` repository. Execute the strong goal loop described by the repository Markdown documents.

Goal: complete the missing cluster-management operation matrix, the missing fault/failover matrix, and full quantitative collection under the strong harness.

You must follow these controlling files exactly:

```text
AGENTS.md
CODEX_START_HERE.md
CODEX_GOAL_LOOP_START.md
docs/codex/goal-loop/00_INDEX.md
docs/codex/goal-loop/01_GOAL_CONTRACT.md
docs/codex/goal-loop/02_STAGE_MANIFEST.md
docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md
docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md
docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md
docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md
docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md
docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md
docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md
docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md
```

Start now:

1. Run `python3 scripts/codex_gate.py next`.
2. Inspect whether `codex/phase_manifest.json` contains P15-P26.
3. If P15-P26 are missing, current stage is `P15_GOAL_REBASE_HARNESS_EXTENSION`; implement only that stage first.
4. At every stage start, reread all goal-loop docs and write `artifacts/goal_loop/<STAGE_ID>/CONTEXT_RELOAD.md`.
5. For every stage, spawn a read-only design subagent, then a worker subagent, then a fresh-context review subagent. Use the prompt files in `docs/codex/goal-loop/prompts/`.
6. Do not mark complete, commit, or push until gates, artifacts, and review pass.
7. After a stage passes postcheck and mark-complete, commit and push that stage before starting the next stage.
8. Continue through `P26_FINAL_REPORT_REGRESSION` unless blocked by a real safety/resource/gate failure.

Safety constraints:

- Do not mutate host networking, firewall, routing, or physical interfaces.
- Do not use `sudo` for networking.
- Use only owned Docker/container namespaces or sandbox proxy faults.
- Do not run P14 1000-node execution.
- Do not fabricate metrics.

Begin with the document reload and P15/P-next determination. Do not ask for clarification unless a safety approval is required.
