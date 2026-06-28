# 04_AUDITOR.md — Fresh-Context Reviewer/Auditor Protocol

## 1. Purpose

The auditor prevents the implementation agent from self-certifying. The auditor must enter with fresh context and judge only evidence present in the repository, gate logs, and artifacts.

## 2. Required auditor inputs

For phase `<PHASE_ID>`, the auditor must inspect:

```text
AGENTS.md
codex/phase_manifest.json
docs/codex/02_PHASES.md
artifacts/gates/<PHASE_ID>/gate_result.json
artifacts/gates/<PHASE_ID>/stdout/*.log
artifacts/gates/<PHASE_ID>/stderr/*.log
artifacts/phases/<PHASE_ID>/*
schemas/**/*
```

The auditor should also inspect relevant source diffs for the phase.

## 3. Required auditor outputs

Create:

```text
audit/<PHASE_ID>/AUDIT.md
audit/<PHASE_ID>/audit_decision.json
```

Use `templates/audit/AUDIT_TEMPLATE.md` and `templates/audit/audit_decision.template.json`.

## 4. Decision rules

The auditor must return FAIL if any of these are true:

- a manifest gate failed or was not run;
- required artifact is missing;
- artifact schema validation failed;
- real Valkey gate is required but evidence is fake, missing, or not Valkey 9.1.x;
- cleanup is missing or reports owned resource leftovers;
- report contains fabricated metrics;
- a safety rule is violated;
- postcheck cannot pass;
- the auditor did not have fresh context.

## 5. Fresh-context prompt

Use the exact prompt in `templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md`, replacing placeholders. The implementation agent must not write the audit on behalf of the fresh-context auditor.

