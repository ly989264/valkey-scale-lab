# CONTEXT_RELOAD — P46_REPOSITORY_LAYOUT_MIGRATION

## Stage identity

- Stage ID: `P46_REPOSITORY_LAYOUT_MIGRATION`
- Branch: `codex/valkey-scale-lab-loop`
- Date/time: `2026-07-11 Asia/Singapore`
- Current harness next output: `COMPLETE_AUTOMATIC_PHASES`; P46 is an explicitly requested non-runtime maintenance stage.
- Git status summary: clean before P46 bootstrap; only intentional P46 contract files are now modified/untracked.

## Documents reread

| Document | Read? | Notes |
|---|---:|---|
| AGENTS.md | Yes | Artifact-first product, harness integrity, multi-agent loop, deterministic cleanup. |
| CODEX_START_HERE.md | Yes | Preserve package/CLI shape and run precheck, gates, review, postcheck. |
| CODEX_GOAL_LOOP_START.md | Yes | Strong harness and structured subagent handoff remain mandatory. |
| docs/codex/02_PHASES.md | Yes | Machine manifest is authoritative; stages close only after postcheck. |
| docs/codex/04_AUDITOR.md | Yes | Audit must cite actual gates and artifacts and fail closed. |
| docs/codex/goal-loop/00_INDEX.md | Yes | Goal-loop document precedence confirmed. |
| docs/codex/goal-loop/01_GOAL_CONTRACT.md | Yes | No invented evidence and no incomplete stage claims. |
| docs/codex/goal-loop/02_STAGE_MANIFEST.md | Yes | Stage scope, gates, artifacts, and review must be explicit. |
| docs/codex/goal-loop/03_MULTI_AGENT_STAGE_PROTOCOL.md | Yes | Design, worker, main-agent gates, and fresh review sequence required. |
| docs/codex/goal-loop/04_CONTEXT_TRANSFER_PROTOCOL.md | Yes | Handoffs are file-backed and must identify uncertainty. |
| docs/codex/goal-loop/05_STRONG_HARNESS_GATE_SPEC.md | Yes | Gates must verify behavior rather than the presence of placeholders. |
| docs/codex/goal-loop/06_QUANTIFICATION_SPEC.md | Yes | Missing values need explicit status/reason; no fabricated metrics. |
| docs/codex/goal-loop/07_MANAGEMENT_OPS_SPEC.md | Yes | Management evidence remains historical product data and must be preserved. |
| docs/codex/goal-loop/08_FAULT_MATRIX_SPEC.md | Yes | Fault/failover evidence remains historical product data and must be preserved. |
| docs/codex/goal-loop/09_SCALE_AND_RESOURCE_POLICY.md | Yes | P46 starts no large cluster and changes no network resources. |
| docs/codex/goal-loop/10_AUDIT_AND_COMMIT_POLICY.md | Yes | PASS review, postcheck, mark-complete, commit, and push order applies. |
| docs/codex/goal-loop/stages/P46_REPOSITORY_LAYOUT_MIGRATION.md | Yes | Two-directory physical separation with compatibility and digest proof. |

## Current stage contract summary

- Required implementation: move runnable project/control files under `project/`; move historical evidence under `loop_evidence/`; retain only thin root discovery entries; preserve operational relative paths from the project root.
- Required gates: lock/manifest precheck, layout validator, evidence digest comparison, schema validation, compilation, CLI help, non-real tests, fresh review.
- Required artifacts: phase summary, evidence integrity baseline, layout report, structured design/worker/review documents, audit decision.
- Explicit non-goals: no Valkey behavior changes, no historical evidence rewrites, no host networking changes, no large-scale execution.

## Risks and assumptions

- Safety risks: accidental deletion or mutation of approximately 17,500 tracked evidence files; broken symlinks; CI executing from the wrong directory.
- Resource risks: hashing roughly 691 MB and a large Git rename set; no runtime node resources are required.
- `待验证` items: full test assumptions about repository root; whether all retired loop packages are reference-only; remote push behavior because the local branch began two commits behind.

## Handoff to design subagent

- Design prompt path: `docs/codex/goal-loop/prompts/DESIGN_SUBAGENT_PROMPT.md`
- Stage doc path: `docs/codex/goal-loop/stages/P46_REPOSITORY_LAYOUT_MIGRATION.md`
- Notes: Prefer a fail-closed compatibility layout and deterministic evidence digest. Do not weaken locked controls or rewrite historical JSON references.
