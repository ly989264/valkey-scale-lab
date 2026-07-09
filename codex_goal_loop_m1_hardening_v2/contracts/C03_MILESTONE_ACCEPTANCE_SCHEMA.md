# C03 Milestone acceptance schema

Final acceptance must separate hardening status from milestone status.

```json
{
  "hardening_loop_status": "PASS|FAIL|BLOCKED_WITH_REASON",
  "milestone1_status": "PASS|FAIL|BLOCKED_WITH_REASON",
  "false_pass_prevented": true,
  "required_claim_count": 0,
  "passed_claim_count": 0,
  "blocked_claim_count": 0,
  "failed_claim_count": 0,
  "claims": []
}
```

Hardening can PASS while milestone is BLOCKED. Milestone cannot PASS with blocked required claims.
