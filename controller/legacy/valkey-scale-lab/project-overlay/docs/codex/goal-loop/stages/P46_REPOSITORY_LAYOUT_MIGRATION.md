# P46_REPOSITORY_LAYOUT_MIGRATION

## Purpose

Separate the runnable project from historical loop evidence without weakening the harness or invalidating any committed evidence.

## Required layout

The repository root must contain two primary storage directories:

```text
project/
loop_evidence/
```

Root-level Git and platform discovery entries such as `.git`, `.github`, `.gitignore`, `AGENTS.md`, and `README.md` are allowed. They must remain thin entry points rather than duplicate project trees.

`project/` contains the runnable package, tests, configuration, scripts, schemas, templates, documentation, and active harness controls. `loop_evidence/` contains historical `artifacts/`, `audit/`, `runs/`, and retired loop packages.

## Compatibility requirements

- Commands documented for the project must run from `project/`.
- GitHub Actions must retain root discovery and execute project commands from `project/`.
- Active harness paths `artifacts/`, `audit/`, and `runs/` must resolve from the project root to the physically separate evidence directory.
- `python3 scripts/codex_gate.py precheck --all`, package compilation, CLI help, schema checks, and the test suite must remain valid.
- Historical evidence content must not be rewritten. Migration integrity must be proven by deterministic file counts, byte counts, and content digests captured before and verified after the move.
- Symlink compatibility is permitted because supported development platforms are Mac and Linux. The layout gate must fail closed if a required link is missing, broken, or points outside `loop_evidence/`.

## Required artifacts

```text
artifacts/phases/P46_REPOSITORY_LAYOUT_MIGRATION/phase_summary.json
artifacts/phases/P46_REPOSITORY_LAYOUT_MIGRATION/evidence_integrity.json
artifacts/phases/P46_REPOSITORY_LAYOUT_MIGRATION/repository_layout_report.json
artifacts/goal_loop/P46_REPOSITORY_LAYOUT_MIGRATION/CONTEXT_RELOAD.md
artifacts/goal_loop/P46_REPOSITORY_LAYOUT_MIGRATION/DESIGN_BRIEF.md
artifacts/goal_loop/P46_REPOSITORY_LAYOUT_MIGRATION/WORKER_SUMMARY.md
artifacts/goal_loop/P46_REPOSITORY_LAYOUT_MIGRATION/REVIEW.md
```

## Gates

- Harness lock and manifest validation.
- Evidence integrity comparison against the pre-migration baseline.
- Repository layout validation, including root allowlist and link targets.
- Python compilation and CLI import/help.
- Full non-real test suite, with no large-scale Valkey execution required for this storage-only migration.
- Fresh-context review and normal postcheck/mark-complete.

## Safety

- Do not delete historical artifacts, audits, or runs.
- Do not alter host networking or start large Valkey clusters.
- Do not replace historical evidence with generated placeholders.
- Do not weaken an existing schema, gate, or lock assertion to make the migration pass.
