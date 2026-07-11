# 15_STAGE_EXIT_CHECKLIST — stage 出口清单

主 agent 每个 stage 结束前必须完成：

```text
[ ] 当前 stage 所有必做项完成
[ ] 覆盖矩阵更新
[ ] schema 已更新
[ ] artifact writer 已更新
[ ] artifact reader 已更新
[ ] analyzer 已更新
[ ] 中文 report renderer 已更新或预留明确接入
[ ] fake fixture 已更新
[ ] smoke/integration tests 已更新
[ ] dry-run / blocked path 有 reason
[ ] failure path 有测试或 reason
[ ] cleanup path 已覆盖
[ ] 强 harness gates 已运行
[ ] review subagent 最终 PASS
[ ] 写 DESIGN_BRIEF.md
[ ] 写 WORKER_SUMMARY.md
[ ] 写 REVIEW.md
[ ] 写 COMPLETION.md
[ ] 写 CONTEXT_RELOAD.md
[ ] commit
[ ] push
[ ] git status clean
```

任何未完成项都必须导致 stage 不完成。
