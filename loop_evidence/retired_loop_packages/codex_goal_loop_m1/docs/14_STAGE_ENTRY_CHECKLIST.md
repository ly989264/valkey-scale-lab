# 14_STAGE_ENTRY_CHECKLIST — stage 入口清单

主 agent 每个 stage 开始时必须完成：

```text
[ ] 读取 00_INDEX.md
[ ] 读取 01_GOAL_CONTRACT.md
[ ] 读取 02_STAGE_MANIFEST.md
[ ] 读取 03_GLOBAL_COVERAGE_MATRIX.md
[ ] 读取 04_STRONG_HARNESS_LOOP_ENGINE.md
[ ] 读取 05_MULTI_AGENT_STAGE_PROTOCOL.md
[ ] 读取 06_CONTEXT_TRANSFER_PROTOCOL.md
[ ] 读取当前 stage 文件
[ ] 读取上一个 stage 的 CONTEXT_RELOAD.md，如果存在
[ ] 读取仓库 AGENTS.md，如果存在
[ ] 记录 git status
[ ] 记录 HEAD commit
[ ] 确认当前 stage 未被跳过
[ ] 建立本 stage coverage matrix 草稿
[ ] 启动 design subagent
```

如果上述任一项失败，必须先修复入口问题，不能直接开发。
