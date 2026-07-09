# C12 No simulated subagent contract

`assert_no_simulated_subagents.py` must scan stage handoff and agent files.

Forbidden phrases outside this contract package:

```text
simulated design subagent
simulated worker subagent
simulated review subagent
explicit subagent launch failed
usage-limit error; this document preserves
performed as a separate role artifact
```

If these appear in stage artifacts, the stage must FAIL or BLOCK. The correct behavior is to stop and report `BLOCKED_WITH_REASON` when real subagents are unavailable.
