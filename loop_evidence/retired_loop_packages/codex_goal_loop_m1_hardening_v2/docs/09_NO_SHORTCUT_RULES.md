# 09_NO_SHORTCUT_RULES.md

## Static shortcut scan

H00 must implement a static scan that fails if milestone hardening code contains shortcut patterns such as:

```text
fallback to tests/fixtures for PASS
if not real_run: PASS
legacy evidence satisfies M1 claim
metric_count > 0 is sufficient
status in {PASS, SKIPPED_WITH_REASON}
simulated design subagent
simulated worker subagent
simulated review subagent
unknown phase ignored
non-empty file is enough
```

The exact scanner may use AST or conservative text matching, but it must report file, line, and reason.

## Allowed use of fixtures

Fixtures are allowed only for:

- unit tests;
- schema validation tests;
- parser tests;
- report renderer tests.

Fixtures must not appear in exact-scale M1 acceptance claims except as `evidence_kind: FIXTURE_ONLY` with `required_for_milestone_pass: false`.

## Allowed use of legacy evidence

Legacy evidence can appear only as:

```json
{"evidence_kind":"LEGACY_EVIDENCE_ONLY","required_for_milestone_pass":false}
```

or as raw input to an explicit reconstruction claim that proves all required M1 fields without invention.
