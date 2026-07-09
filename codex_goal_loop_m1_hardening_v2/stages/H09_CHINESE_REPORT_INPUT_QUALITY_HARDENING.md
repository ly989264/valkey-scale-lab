# H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING.md — Chinese report input-quality hardening

## Stage goal

Keep offline Chinese report generation, but make report status distinguish render PASS from source-quality PASS; block milestone if inputs are weak.

## Non-negotiable scope

This stage must follow the multi-agent protocol and hard gate architecture. It must not complete with Markdown-only evidence. It must not hide missing exact-scale evidence behind fixtures or legacy artifacts.

## Required implementation outcomes

- update or create code needed for this stage;
- update unit/integration tests;
- update evidence manifest generation if the stage changes claims;
- write gate result JSON under `runs/m1-hardening/H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING/artifacts/gates/`;
- write agent and handoff artifacts under `runs/m1-hardening/H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING/`.

## Required gates

Common gates from `docs/17_COMMANDS_AND_GATES.md`, plus:

- `python3 scripts/m1h/assert_report_input_quality.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING`

## Stage-specific anti-shortcut checks

- no fixture fallback can satisfy a real/exact-scale claim;
- no legacy-only evidence can satisfy a new M1-format claim;
- no non-empty file check is sufficient;
- no fake/PARTIAL artifact can promote to real PASS;
- skipped core metrics are allowed only for blocked/fake/dry-run contexts, not real PASS.

## Exit condition

Run:

```text
python3 scripts/m1h/assert_stage_exit.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING
```

The stage may be committed and pushed only after this exits 0 and the real review subagent returns `PASS`.
