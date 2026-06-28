# Audit — <PHASE_ID>

Decision: <PASS|FAIL>
Fresh Context: <YES|NO>
Auditor: <fresh-context-codex-reviewer-or-human>
Audit Time: <ISO-8601 UTC>

Gate Result: artifacts/gates/<PHASE_ID>/gate_result.json
Observed Gate Result SHA256: <sha256>

## Scope inspected

- `codex/phase_manifest.json`
- `docs/codex/02_PHASES.md`
- phase source changes
- gate result and logs
- required artifacts
- schema validation output
- cleanup evidence
- real Valkey evidence, if required

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| <gate-name> | PASS | <PASS|FAIL> | <log/artifact path> |

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| <artifact-path> | <schema-path> | <valid|invalid|missing> | <notes> |

## Safety findings

- Host network mutation: <absent|present>
- Global firewall mutation: <absent|present>
- Sudo default path: <absent|present>
- Cleanup logic: <verified|missing|failed>
- Default node cap <= 100: <verified|failed>

## Real Valkey findings

Required for this phase: <YES|NO>
Evidence file: <path-or-N/A>
Valkey version observed: <value-or-N/A>
Independent live probe: <PASS|FAIL|N/A>

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| <risk> | <low|medium|high|critical> | <yes|no> | <notes> |

## Final rationale

<Brief evidence-based rationale. Do not rely on the implementation agent's claims.>
