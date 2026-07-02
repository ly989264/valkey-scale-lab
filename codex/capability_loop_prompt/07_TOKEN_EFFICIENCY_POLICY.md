# 07 — Token Efficiency Policy

## 1. 原则

强 harness 和强 loop 不等于无节制展开上下文。每个 stage 只处理一个明确能力切片，所有大上下文用文件摘要、path、sha256、artifact 引用替代重复粘贴。

## 2. 每 stage 的最小上下文包

主 agent 给子 agent 的上下文只包含：

```text
stage objective
active constraints summary
relevant file paths
previous stage next_stage_context.md
current failure logs if any
harness freeze paths/checksums
```

不要给子 agent 发送整个仓库树或全部历史日志。

## 3. 早失败顺序

每个 stage 先跑便宜检查，再跑昂贵 real cluster：

```text
syntax/compile
schema/unit tests
negative harness tests
previous harness postcheck
fast real smoke if applicable
real 30/50/100 gate
report/audit
```

发现失败立即停止后续昂贵命令，写 `failed_runs.jsonl`。

## 4. 小 diff 策略

每个 stage 只改当前目标必需文件。禁止顺手重构大模块。需要重构时，把重构拆成独立 stage 或在当前 stage 中证明它是实现目标的最小路径。

## 5. Artifact 引用策略

给 reviewer 的摘要用：

```text
path
sha256
record count
first/last timestamp
status summary
```

不要把大 JSONL 或完整日志粘进 prompt。

## 6. Run profile 策略

在同一 stage 内使用 profile 分层减少浪费：

1. `fast-unit` 验证 schema/harness。
2. `short-real` 验证真实调用路径。
3. `real-<scale>` 只在前两者 PASS 后执行。

但最终 stage 完成标准必须以 required real profile 为准，不能用 fast profile 代替。

## 7. 子 agent 数量控制

每个 stage 默认 3 个子 agent：

```text
requirements+harness
worker
regression+review
```

只有 scale/soak/复杂故障 stage 才追加 scale guard。不要为简单修复无限拉 agent。
