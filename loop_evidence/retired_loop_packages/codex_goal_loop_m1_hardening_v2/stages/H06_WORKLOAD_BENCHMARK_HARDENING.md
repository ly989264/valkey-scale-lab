# H06_WORKLOAD_BENCHMARK_HARDENING.md — Workload benchmark hardening

## Stage goal

Require benchmark depth: profiles, windows, required metrics, row count thresholds, full-slot coverage, connections/pipeline evidence or block.

## Non-negotiable scope

This stage must follow the multi-agent protocol and hard gate architecture. It must not complete with Markdown-only evidence. It must not hide missing exact-scale evidence behind fixtures or legacy artifacts.

## Required implementation outcomes

- update or create code needed for this stage;
- update unit/integration tests;
- update evidence manifest generation if the stage changes claims;
- write gate result JSON under `runs/m1-hardening/H06_WORKLOAD_BENCHMARK_HARDENING/artifacts/gates/`;
- write agent and handoff artifacts under `runs/m1-hardening/H06_WORKLOAD_BENCHMARK_HARDENING/`.

## Required gates

Common gates from `docs/17_COMMANDS_AND_GATES.md`, plus:

- `python3 scripts/m1h/assert_workload_benchmark_strength.py --stage H06_WORKLOAD_BENCHMARK_HARDENING`

## Stage-specific anti-shortcut checks

- no fixture fallback can satisfy a real/exact-scale claim;
- no legacy-only evidence can satisfy a new M1-format claim;
- no non-empty file check is sufficient;
- no fake/PARTIAL artifact can promote to real PASS;
- skipped core metrics are allowed only for blocked/fake/dry-run contexts, not real PASS.

## Exit condition

Run:

```text
python3 scripts/m1h/assert_stage_exit.py --stage H06_WORKLOAD_BENCHMARK_HARDENING
```

The stage may be committed and pushed only after this exits 0 and the real review subagent returns `PASS`.
