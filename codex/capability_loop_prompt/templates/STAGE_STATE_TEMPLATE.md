# Stage State Template

```json
{
  "schema_version": "v1",
  "stage_id": "CMLxx_...",
  "status": "STARTED|BLOCKED|PASS|FAIL",
  "state": "START|CONTEXT_REFRESH|...",
  "started_at": "...",
  "updated_at": "...",
  "active_constraints": [],
  "previous_harness": {
    "required": true,
    "status": "UNKNOWN|PASS|FAIL",
    "log_path": "..."
  },
  "current_harness": {
    "designed": false,
    "frozen": false,
    "freeze_path": "..."
  },
  "agents": {
    "requirements_harness": "PENDING|PASS|FAIL",
    "worker": "PENDING|PASS|FAIL",
    "regression_guard": "PENDING|PASS|FAIL",
    "review": "PENDING|PASS|FAIL"
  },
  "validation": {
    "current_stage_gate": "PENDING|PASS|FAIL",
    "real_valkey_profiles": []
  }
}
```
