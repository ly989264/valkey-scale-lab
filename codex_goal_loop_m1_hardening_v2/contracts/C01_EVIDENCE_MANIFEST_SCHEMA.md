# C01 Evidence manifest schema

The evidence manifest is generated, not hand-written.

Required top-level fields:

```json
{
  "schema_version": "v1",
  "artifact_type": "m1h_evidence_manifest",
  "created_at": "ISO-8601",
  "source_commit": "git sha",
  "claims": []
}
```

Each claim requires:

```json
{
  "claim_id": "string",
  "stage_id": "string",
  "capability": "setup_telemetry|command_audit|management_matrix|workload_benchmark|fault_timeline|system_metrics|report|cleanup|acceptance",
  "scale": 30,
  "evidence_kind": "REAL_EXACT_SCALE|REAL_SMALL_SMOKE|M1_FORMAT_RECONSTRUCTED_FROM_REAL_RAW|LEGACY_EVIDENCE_ONLY|FIXTURE_ONLY|DRY_RUN_ONLY|BLOCKED_WITH_REASON|INVALID",
  "required_for_milestone_pass": true,
  "source_artifacts": [],
  "semantic_checks": {},
  "status": "PASS|FAIL|BLOCKED_WITH_REASON"
}
```
