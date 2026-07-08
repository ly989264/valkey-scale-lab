# COVERAGE_ENFORCEMENT_CHECKLIST

审查每个新增字段：

```text
[ ] schema
[ ] artifact writer
[ ] artifact reader
[ ] analysis aggregator
[ ] Chinese report renderer
[ ] fake fixture
[ ] unit/integration test
[ ] smoke path
[ ] real local run path or BLOCKED_WITH_REASON
[ ] dry-run path
[ ] blocked path
[ ] failure path
[ ] cleanup path
[ ] regression gate
```
