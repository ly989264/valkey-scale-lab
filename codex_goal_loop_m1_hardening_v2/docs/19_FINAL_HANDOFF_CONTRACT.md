# 19_FINAL_HANDOFF_CONTRACT.md

H10 must produce:

```text
runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/artifacts/milestone1_hardened_acceptance.json
runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/handoff/FINAL_HANDOFF.md
```

The final acceptance JSON must include:

```json
{
  "hardening_loop_status": "PASS|FAIL|BLOCKED_WITH_REASON",
  "milestone1_status": "PASS|BLOCKED_WITH_REASON|FAIL",
  "false_pass_prevented": true,
  "required_claims": [],
  "passed_claims": [],
  "blocked_claims": [],
  "failed_claims": [],
  "fixture_only_claims": [],
  "legacy_only_claims": []
}
```

If any required exact-scale claim is blocked, `milestone1_status` must be `BLOCKED_WITH_REASON`. This is the expected honest result if resources are unavailable.
