# 02_NON_NEGOTIABLE_CONTRACT.md

## Contract over prose

Codex must not define stage completion by text. Every stage must create or update executable hard gates. A review document can summarize gate results, but it cannot replace them.

## Forbidden completion paths

A stage is invalid if any of these occurs:

1. It claims PASS with only Markdown completion notes.
2. It claims PASS using fixture fallback for a real-scale requirement.
3. It claims PASS using legacy real evidence for a new M1-format requirement.
4. It treats `SKIPPED_WITH_REASON` as PASS for a core metric in a real run.
5. It accepts a non-empty file as sufficient proof without schema and semantic validation.
6. It accepts fake/PARTIAL timeline as real fault/failover proof.
7. It accepts report generation as evidence of source quality.
8. It uses simulated subagents.
9. It commits before review PASS and hard gates PASS.

## Required fail-closed behavior

If an exact-scale real run cannot be performed, the correct state is:

```json
{"status":"BLOCKED_WITH_REASON","reason":"...","missing_claims":[...]}
```

It is never acceptable to convert blocked exact-scale evidence into PASS by relying on a smaller run, a fixture, or a historical artifact.
