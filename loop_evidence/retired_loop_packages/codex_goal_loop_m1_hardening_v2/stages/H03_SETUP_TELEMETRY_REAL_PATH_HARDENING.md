# H03_SETUP_TELEMETRY_REAL_PATH_HARDENING.md — Setup telemetry real-path hardening

## Stage goal

Ensure real setup telemetry claims require numeric core metrics; produce blocked claims for exact scales that lack M1-format numeric telemetry. Fix runtime if possible.

## Non-negotiable scope

This stage must follow the multi-agent protocol and hard gate architecture. It must not complete with Markdown-only evidence. It must not hide missing exact-scale evidence behind fixtures or legacy artifacts.

## Required implementation outcomes

- update or create code needed for this stage;
- update unit/integration tests;
- update evidence manifest generation if the stage changes claims;
- write gate result JSON under `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/artifacts/gates/`;
- write agent and handoff artifacts under `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/`.

## Required gates

Common gates from `docs/17_COMMANDS_AND_GATES.md`, plus:

- `python3 scripts/m1h/assert_setup_core_metrics.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING`

## Stage-specific anti-shortcut checks

- no fixture fallback can satisfy a real/exact-scale claim;
- no legacy-only evidence can satisfy a new M1-format claim;
- no non-empty file check is sufficient;
- no fake/PARTIAL artifact can promote to real PASS;
- skipped core metrics are allowed only for blocked/fake/dry-run contexts, not real PASS.

## Exit condition

Run:

```text
python3 scripts/m1h/assert_stage_exit.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING
```

The stage may be committed and pushed only after this exits 0 and the real review subagent returns `PASS`.
