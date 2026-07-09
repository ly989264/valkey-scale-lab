# 15_REVIEW_RUBRIC.md

The review subagent must answer these questions with evidence paths:

1. Did the stage implement executable hard gates?
2. Did the gates exit 0 or correctly block?
3. Did the stage avoid fixture fallback for real acceptance?
4. Did the stage avoid legacy evidence for new M1 claims?
5. Are all new fields wired through schema -> writer -> reader -> analyzer -> renderer -> gate?
6. Are exact-scale claims classified in the evidence manifest?
7. Did any core metric remain skipped in a real PASS claim?
8. Are fake/PARTIAL artifacts prevented from satisfying real claims?
9. Are subagent artifacts real and non-simulated?
10. Is the next-stage handoff sufficient without chat context?

Review decision must be one of:

```text
PASS
FAIL
BLOCKED_WITH_REASON
```
