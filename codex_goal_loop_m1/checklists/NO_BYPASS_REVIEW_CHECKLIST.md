# NO_BYPASS_REVIEW_CHECKLIST

review 必查：

```text
[ ] 没有 hard-coded PASS
[ ] 没有空 JSONL PASS
[ ] 没有只检查文件存在
[ ] 没有吞掉 stderr/exit_code
[ ] 没有 except pass 导致 false PASS
[ ] 没有 fake real evidence
[ ] 没有 report-only metric
[ ] 没有 schema-only field
[ ] 没有 writer-only field
[ ] 没有 single-scale-only field
[ ] 没有 single-test-only field
```
