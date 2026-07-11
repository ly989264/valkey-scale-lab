# 13_BLOCKED_STATUS_POLICY.md

## BLOCKED is acceptable when honest

If exact-scale evidence cannot be produced in the current environment, use `BLOCKED_WITH_REASON` and stop milestone PASS.

## Required blocked fields

```json
{
  "status": "BLOCKED_WITH_REASON",
  "capability": "workload_benchmark",
  "scale": 200,
  "reason": "resource preflight failed: ...",
  "required_artifacts": ["..."],
  "missing_fields": ["..."],
  "rerun_command": "...",
  "required_before_milestone_pass": true
}
```

## Forbidden blocked behavior

Do not convert blocked to PASS because:

- a fixture exists;
- a smaller real run exists;
- old Valkey evidence exists;
- a report was generated;
- the gate would otherwise fail.
