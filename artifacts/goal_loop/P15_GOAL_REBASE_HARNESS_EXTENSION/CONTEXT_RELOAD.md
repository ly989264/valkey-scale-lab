# CONTEXT_RELOAD — P15_GOAL_REBASE_HARNESS_EXTENSION

## Stage identity

- Stage ID: P15_GOAL_REBASE_HARNESS_EXTENSION
- Branch: codex/valkey-scale-lab-loop
- Date/time: 2026-07-02T15:28:44Z
- Current harness next output: `COMPLETE_AUTOMATIC_PHASES`
- Git status summary: clean worktree; local branch is ahead of `origin/codex/valkey-scale-lab-loop` by 1 commit (`2b55a74 Initialize harness loop control pack`)
- Current stage reason: `codex/phase_manifest.json` still has `automatic_stop_after` set to `P13_SCALE_LADDER_50_100` and does not contain P15-P26 entries, so `CODEX_START_HERE.md` directs the loop to treat `P15_GOAL_REBASE_HARNESS_EXTENSION` as the current bootstrap stage.

## Documents reread

| Document | Read? | Notes |
|---|---:|---|
| AGENTS.md | yes | Goal-loop harness rules, stage reload list, subagent flow, safety rules. |
| CODEX_START_HERE.md | yes | First action, P15 bootstrap rule, command sequence, completion definition. |
| CODEX_GOAL_LOOP_START.md | yes | User-visible goal summary and operator approval boundaries. |
| docs/codex/02_PHASES.md | yes | Existing P00-P14 phase intent and criteria. |
| docs/codex/04_AUDITOR.md | yes | Fresh-context audit requirements and required audit outputs. |
| docs/codex/goal-loop/00_INDEX.md | yes | Required read order, document map, stage doc requirement. |
| docs/codex/goal-loop/01_GOAL_CONTRACT.md | yes | Required management/fault coverage and completion/blocking conditions. |
| docs/codex/goal-loop/02_STAGE_MANIFEST.md | yes | P15-P26 stage list, required manifest fields, common gates, common artifacts. |
| docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md | yes | Mandatory design, worker, gate, review, postcheck, mark-complete sequence. |
| docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md | yes | Required Markdown artifacts and cross-stage journal. |
| docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md | yes | P15 harness extension requirements, assertion script names, schema families. |
| docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md | yes | Canonical events, metrics, workload windows, management/failover/fault metrics. |
| docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md | yes | Required management operation rows and semantics. |
| docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md | yes | Required failover, stop fault, network fault, partition, split-brain, workload rows. |
| docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md | yes | 100-node default cap, 200-node bounded exception, resource preflight policy. |
| docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md | yes | Review, postcheck, mark-complete, exact stage commit/push rules. |
| docs/codex/goal-loop/stages/P15_GOAL_REBASE_HARNESS_EXTENSION.md | yes | P15-specific harness-only objective, gates, artifacts, review focus. |

## Current stage contract summary

- Required implementation: append P15-P26 manifest entries, set `automatic_stop_after` to `P26_FINAL_REPORT_REGRESSION`, keep P14 non-automatic opt-in dry-run, add goal-loop artifact schemas, add fail-closed assertion scripts, add tests, update P15-P26 phase summaries, and update audit/review hooks if required.
- Required gates: `python3 scripts/codex_gate.py precheck --phase P15_GOAL_REBASE_HARNESS_EXTENSION`, `python3 scripts/safety_scan.py`, `python3 -m compileall -q scripts src`, `python3 -m pytest -q tests/unit tests/integration`, `python3 scripts/assert_goal_loop_stage.py --phase P15_GOAL_REBASE_HARNESS_EXTENSION`, `python3 scripts/codex_gate.py run --phase P15_GOAL_REBASE_HARNESS_EXTENSION`, and `python3 scripts/codex_gate.py postcheck --phase P15_GOAL_REBASE_HARNESS_EXTENSION`.
- Required artifacts: `artifacts/phases/P15_GOAL_REBASE_HARNESS_EXTENSION/phase_summary.json`, `artifacts/phases/P15_GOAL_REBASE_HARNESS_EXTENSION/quant_summary.json`, `artifacts/goal_loop/P15_GOAL_REBASE_HARNESS_EXTENSION/CONTEXT_RELOAD.md`, `DESIGN_BRIEF.md`, `WORKER_SUMMARY.md`, `REVIEW.md`, and `COMPLETION.md`.
- Explicit non-goals: do not implement real management/fault runtime behavior in P15, do not claim real Valkey coverage for P15, do not run P14, do not change host networking, firewall, routing, or OS network services.

## Risks and assumptions

- Safety risks: new assertions and manifest gates must fail closed without weakening `scripts/codex_gate.py`, `codex/gate_lock.json`, safety scanning, or existing schema validation.
- Resource risks: P15 itself has max nodes 0 and should not require Docker or real Valkey, but later stages must preserve resource preflight and real-evidence requirements.
- `待验证` items: whether existing `codex_gate.py` can validate new stage artifacts without modification; whether `gate_lock.json` must include new harness files; whether audit postcheck requires legacy `audit/<STAGE_ID>/AUDIT.md` in addition to goal-loop `REVIEW.md`; whether the local unpushed control-pack commit should be amended into the final P15 commit or left as a prior setup commit.

## Handoff to design subagent

- Design prompt path: `docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md`
- Stage doc path: `docs/codex/goal-loop/stages/P15_GOAL_REBASE_HARNESS_EXTENSION.md`
- Notes: design must remain read-only and propose exact manifest, schema, script, test, and audit-hook changes for P15 only. P16-P26 runtime implementations are future-stage work, but P15 must make the harness unable to falsely pass those future stages.
