# 05_MULTI_AGENT_STAGE_PROTOCOL — 多 agent stage 协议


## 每个 stage 的多 agent 流程

主 agent 不允许直接开始写代码。每个 stage 必须按以下顺序推进：

```text
主 agent 重新加载文档
  -> design subagent 设计
  -> 主 agent 审阅设计并形成执行计划
  -> worker subagent 开发
  -> 主 agent 运行强 harness gates
  -> review subagent 审计
  -> 主 agent 修复 review 问题
  -> gates 全 PASS
  -> review 最终 PASS
  -> commit
  -> push
  -> 写 stage handoff 文档
  -> 进入下一个 stage
```

### design subagent 必须输出

- 目标理解。
- 当前代码中相关路径。
- 需要修改的通用路径。
- schema / writer / reader / analyzer / renderer / fixture / gate 的传播计划。
- 覆盖矩阵。
- 风险和待验证点。
- 不允许局部实现的检查点。

### worker subagent 必须输出

- 实际修改列表。
- 新增/修改 schema。
- 新增/修改 artifact writer。
- 新增/修改 analyzer。
- 新增/修改 report renderer。
- 新增/修改 fake fixture / smoke / integration / real-path contract test。
- 运行过的命令和结果。
- 未能运行的真实重型 gate 以及 blocked reason。

### review subagent 必须输出

- 是否满足当前 stage 所有验收标准。
- 是否存在只覆盖单一规模、单一路径、单一测试的局部补丁。
- 是否有 schema/writer/reader/analyzer/renderer/fixture 任一环节漏接。
- 是否存在 fake real / false PASS / empty artifact / hard-coded artifact。
- 是否可 commit。
- 结论只能是 `PASS`、`FAIL` 或 `BLOCKED_WITH_REASON`。


## 主 agent 职责

主 agent 负责：

1. 重新加载所有核心 md 文档。
2. 确认当前 stage id。
3. 创建或更新 coverage matrix。
4. 启动 design subagent。
5. 审查 design 输出。
6. 启动 worker subagent。
7. 运行 gates。
8. 启动 review subagent。
9. 根据 review 修复问题。
10. 只有 review PASS 才 commit/push。
11. 写 context reload handoff。
12. 进入下一 stage。

## design subagent 不允许做什么

- 不允许直接修改代码。
- 不允许缩小 scope。
- 不允许只设计单一规模。
- 不允许把 schema/analyzer/report 接入推给未来 stage。
- 不允许用“后续再补”作为方案。

## worker subagent 不允许做什么

- 不允许只实现 happy path。
- 不允许只改一个测试。
- 不允许写空 artifact。
- 不允许 hard-code PASS。
- 不允许在真实路径不可运行时伪造结果。
- 不允许遗漏 cleanup/failure path。

## review subagent 不允许做什么

- 不允许只看 tests pass。
- 不允许忽略覆盖矩阵。
- 不允许接受 partial implementation。
- 不允许接受 empty command log / empty metrics / empty timeline。
- 不允许接受未接入最终中文报告的新增字段。
