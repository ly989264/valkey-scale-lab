# CODEX_START_HERE.md — Goal Loop Entry Point

Read `AGENTS.md` first. Then execute the goal-loop stage plan without waiting for human intervention unless a real safety, resource, or gate failure blocks progress.

## Target repository

Implement and harden `valkey-scale-lab` so it can run Valkey 9.1.x cluster experiments locally on Mac/Linux Docker and later distribute work across multiple Mac/Linux hosts.

The system must test and analyze:

- cluster-management performance metrics;
- management operation matrix behavior;
- failover effectiveness and latency curves;
- split-brain and minority/majority partition behavior;
- stability and soak behavior;
- workload impact under normal, management, failure, and recovery periods;
- artifact-first quantitative analysis and reporting.

## First action

Run the current harness status command:

```bash
python3 scripts/codex_gate.py next
```

Then inspect whether `codex/phase_manifest.json` already contains stages `P15_GOAL_REBASE_HARNESS_EXTENSION` through `P26_FINAL_REPORT_REGRESSION`.

- If the new stages are missing, treat `P15_GOAL_REBASE_HARNESS_EXTENSION` as the current bootstrap stage and implement the manifest/gate/doc integration required by `docs/codex/goal-loop/stages/P15_GOAL_REBASE_HARNESS_EXTENSION.md`.
- If the new stages exist, implement only the next incomplete automatic stage returned by the harness.
- If an older P00-P13 stage is still incomplete, complete it without weakening the new goal-loop requirements. Do not mark old stages complete through hand-edited status.

## Goal-loop completion condition

The loop is complete when all automatic stages through `P26_FINAL_REPORT_REGRESSION` pass postcheck, have fresh-context review `Decision: PASS`, are marked complete by the harness, and are committed/pushed.

`P14_SCALE_1000_OPTIN_DRYRUN` remains intentionally not automatic.

## Required command sequence per stage

```bash
python3 scripts/codex_gate.py precheck --phase <STAGE_ID>
python3 scripts/codex_gate.py run --phase <STAGE_ID>
# create/verify artifacts, run extra assertions, and run fresh-context review
python3 scripts/codex_gate.py postcheck --phase <STAGE_ID>
python3 scripts/codex_gate.py mark-complete --phase <STAGE_ID>
git status --short
git add <stage files>
git commit -m "<STAGE_ID>: <concise summary>"
git push
```

Do not write `PASS` manually into any gate result. Gate results must be produced by the harness.

## Required implementation shape

Preserve the existing package and CLI shape:

```text
src/valkey_scale_lab/
  cli.py
  config/
  planner/
  runtime/
  valkey/
  workload/
  metrics/
  fault/
  analysis/
  report/
  orchestrator/
  artifacts/
```

Goal-loop stages may add subpackages, but must not break existing imports or commands.

## Mandatory document flow

At each stage start, reread the goal-loop docs listed in `AGENTS.md` and write a compact reload artifact using `docs/codex/goal-loop/templates/CONTEXT_RELOAD_TEMPLATE.md`.

Then follow `docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md` exactly:

1. design subagent;
2. worker subagent;
3. gate run and fixes;
4. review subagent;
5. postcheck;
6. mark complete;
7. commit and push.

No stage can be closed based on memory or a previous stage's context.
