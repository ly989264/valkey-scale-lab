# C02 Stage status schema

Each stage completion JSON must include:

```json
{
  "schema_version": "v1",
  "artifact_type": "m1h_stage_status",
  "stage_id": "Hxx",
  "status": "PASS|FAIL|BLOCKED_WITH_REASON",
  "review_decision": "PASS|FAIL|BLOCKED_WITH_REASON",
  "gate_results": [],
  "evidence_claims_added": [],
  "blocked_claims": [],
  "commit_sha": "...",
  "pushed": true
}
```
