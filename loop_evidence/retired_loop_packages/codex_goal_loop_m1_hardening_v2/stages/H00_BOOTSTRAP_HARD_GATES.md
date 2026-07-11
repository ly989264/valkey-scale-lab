# H00_BOOTSTRAP_HARD_GATES.md — Bootstrap hard gate framework

## Stage goal

Create scripts/m1h gate framework, evidence manifest builder, static no-shortcut scans, stage-exit checker, no-simulated-subagent checker, and tests. Do not touch milestone acceptance status yet.

## Non-negotiable scope

This stage must follow the multi-agent protocol and hard gate architecture. It must not complete with Markdown-only evidence. It must not hide missing exact-scale evidence behind fixtures or legacy artifacts.

## Required implementation outcomes

- update or create code needed for this stage;
- update unit/integration tests;
- update evidence manifest generation if the stage changes claims;
- write gate result JSON under `runs/m1-hardening/H00_BOOTSTRAP_HARD_GATES/artifacts/gates/`;
- write agent and handoff artifacts under `runs/m1-hardening/H00_BOOTSTRAP_HARD_GATES/`.

## Required gates

Common gates from `docs/17_COMMANDS_AND_GATES.md`, plus:

- `python3 scripts/m1h/assert_no_fixture_fallback.py --stage H00_BOOTSTRAP_HARD_GATES`
- `python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H00_BOOTSTRAP_HARD_GATES`
- `python3 scripts/m1h/assert_no_simulated_subagents.py --stage H00_BOOTSTRAP_HARD_GATES`
- `python3 scripts/m1h/assert_stage_exit.py --stage H00_BOOTSTRAP_HARD_GATES`
- `python3 scripts/m1h/build_evidence_manifest.py --out runs/m1-hardening/evidence_manifest.json`

## Stage-specific anti-shortcut checks

- no fixture fallback can satisfy a real/exact-scale claim;
- no legacy-only evidence can satisfy a new M1-format claim;
- no non-empty file check is sufficient;
- no fake/PARTIAL artifact can promote to real PASS;
- skipped core metrics are allowed only for blocked/fake/dry-run contexts, not real PASS.

## Exit condition

Run:

```text
python3 scripts/m1h/assert_stage_exit.py --stage H00_BOOTSTRAP_HARD_GATES
```

The stage may be committed and pushed only after this exits 0 and the real review subagent returns `PASS`.
