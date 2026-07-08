# 02_STAGE_MANIFEST — milestone1 stage manifest

## Stage 顺序

```text
M1-S01 -> M1-S02 -> M1-S03 -> M1-S04 -> M1-S05 -> M1-S06 -> M1-S07 -> M1-S08 -> M1-S09
```

长期稳定性 soak 已删除，不存在单独 stage。

## Stage 列表

| Stage ID | 标题 | 是否允许只改文档 | 是否要求代码改动 | 是否要求报告接入 | 是否要求 cross-scenario gate |
|---|---|---:|---:|---:|---:|
| M1-S01 | 工程结构、运行元数据、产物分离规则 | 否 | 是 | 是 | 是 |
| M1-S02 | 本地集群拉起链路指标补全 | 否 | 是 | 是 | 是 |
| M1-S03 | 命令级审计日志补全 | 否 | 是 | 是 | 是 |
| M1-S04 | 管理操作矩阵增强 | 否 | 是 | 是 | 是 |
| M1-S05 | workload 从 smoke 升级为 benchmark | 否 | 是 | 是 | 是 |
| M1-S06 | 故障注入和 failover timeline 增强 | 否 | 是 | 是 | 是 |
| M1-S07 | 系统级指标采集 | 否 | 是 | 是 | 是 |
| M1-S08 | 中文自动化可视化报告 | 否 | 是 | 是 | 是 |
| M1-S09 | milestone1 验收 gate | 否 | 是 | 是 | 是 |

## 每个 stage 的必须产物

每个 stage 都必须生成或更新：

```text
artifacts 或 runs 下的 stage gate result
coverage matrix
design brief
worker summary
review report
completion record
context reload handoff
```

建议路径：

```text
runs/<run_id>/artifacts/goal_loop/<stage_id>/DESIGN_BRIEF.md
runs/<run_id>/artifacts/goal_loop/<stage_id>/WORKER_SUMMARY.md
runs/<run_id>/artifacts/goal_loop/<stage_id>/REVIEW.md
runs/<run_id>/artifacts/goal_loop/<stage_id>/COMPLETION.md
runs/<run_id>/artifacts/goal_loop/<stage_id>/CONTEXT_RELOAD.md
runs/<run_id>/artifacts/goal_loop/<stage_id>/coverage_matrix.md
```

如果当前代码尚未支持 `runs/<run_id>/...`，M1-S01 必须先实现。

## 不允许的完成方式

- 只新增文档但没有实现。
- 只改一个 stage-specific script。
- 只改 30 节点真实路径。
- 只改 200 节点路径。
- 只改 fake 测试。
- 只改 report，不采集底层 artifact。
- 只采集 artifact，不接入 analysis/report。
- 真实运行不可用时伪造 PASS。
