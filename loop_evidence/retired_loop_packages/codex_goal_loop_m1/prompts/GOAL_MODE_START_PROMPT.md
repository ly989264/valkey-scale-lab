# GOAL_MODE_START_PROMPT — 粘贴到 Codex App goal mode 的启动提示词

你现在在 `ly989264/valkey-scale-lab` 仓库中工作。目标是执行 milestone1 的强 harness loop-engineering。

目标起点：

```text
repo: https://github.com/ly989264/valkey-scale-lab
target_start_commit: 211dcbc74a3a6dd41ee1c4421cf0f9bbd98a0ffe
docs_root: codex_goal_loop_m1/
```

## 绝对目标

完成 milestone1：

```text
本地运行真实 Valkey 集群，至多 200 个真实节点。
完成集群拉起、管理操作、故障注入、故障转移、指标采集、分析和中文自动化可视化报告。
报告必须由程序离线自动生成，不依赖 LLM。
```

## 不做

```text
不做 ECS 多机 native runtime。
不做 500/1000/2000 真实节点。
不做长期稳定性 soak。
不做依赖外网或 LLM 的报告。
不做局部补丁。
```

## 你必须先做

1. 读取仓库根目录 `AGENTS.md`，如果存在。
2. 读取 `codex_goal_loop_m1/AGENTS_MILESTONE1.md`。
3. 读取 `codex_goal_loop_m1/docs/00_INDEX.md`。
4. 读取所有核心 docs。
5. 读取 stage manifest。
6. 从 `M1-S01` 开始，按顺序执行每个 stage。
7. 删除长期 soak stage 的概念，不要实现它，不要创建它。

## 每个 stage 必须执行

每个 stage 必须采用多 agent 流程：

```text
主 agent 重新加载文档
  -> 启动 design subagent
  -> 主 agent 审查设计
  -> 启动 worker subagent
  -> 主 agent 运行强 harness gates
  -> 启动 review subagent
  -> review PASS 后 commit
  -> push 当前分支
  -> 写 handoff 文档
  -> 下一 stage
```

如果 Codex UI 支持显式 subagent，请使用显式 subagent。如果不支持显式 subagent，也必须严格模拟三个独立角色，并分别写出：

```text
DESIGN_BRIEF.md
WORKER_SUMMARY.md
REVIEW.md
```

## 强制覆盖要求

每个 stage 都必须维护覆盖矩阵。覆盖不是只覆盖测试类型，还必须覆盖：

```text
执行形态
节点规格
功能路径
数据路径
运行结果
```

新增字段或指标必须贯穿：

```text
schema -> writer -> fixture -> reader -> aggregator -> renderer -> gate -> docs
```

## 完成条件

一个 stage 只有在以下条件满足时才能完成：

```text
stage tasks complete
coverage matrix complete
schema/writer/reader/analyzer/renderer/fixture/gate complete
fake/unit/integration/smoke gates run
real heavy gates run or BLOCKED_WITH_REASON
review subagent PASS
commit done
push done
handoff docs written
```

如果 review FAIL、gates FAIL、push FAIL，必须停止，不得进入下一 stage。

## 当前 stage 顺序

```text
M1-S01 工程结构、运行元数据、产物分离规则
M1-S02 本地集群拉起链路指标补全
M1-S03 命令级审计日志补全
M1-S04 管理操作矩阵增强
M1-S05 workload 从 smoke 升级为 benchmark
M1-S06 故障注入和 failover timeline 增强
M1-S07 系统级指标采集
M1-S08 中文自动化可视化报告
M1-S09 milestone1 验收 gate
```

现在开始执行 `M1-S01`。
