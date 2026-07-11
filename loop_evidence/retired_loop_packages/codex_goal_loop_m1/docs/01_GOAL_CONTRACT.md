# 01_GOAL_CONTRACT — milestone1 目标合同

## 目标

在 `valkey-scale-lab` 中完成 milestone1：

> 本地运行真实 Valkey 集群，至多 200 个真实节点。完成集群拉起、管理操作、故障注入、故障转移、指标采集、分析和中文自动化可视化报告。报告必须能定位瓶颈，且全链路不依赖 LLM。

## 非目标

本 loop 不做：

- ECS 多机 native runtime。
- 500 / 1000 / 2000 真实节点执行。
- 长期稳定性 soak。
- 依赖在线服务或 LLM 的报告生成。
- 只为了过测试而写 fake real 结果。
- 只补某个规模、某个测试或某个脚本的局部实现。

## 目标仓库

```text
repo: https://github.com/ly989264/valkey-scale-lab
target_start_commit: 211dcbc74a3a6dd41ee1c4421cf0f9bbd98a0ffe
```

## milestone1 完成后的能力

```text
1. 本地可重复执行真实 Valkey 小集群、30、50、100、200 节点。
2. 每次运行生成独立 run 目录。
3. 每次运行有统一 run metadata。
4. 集群拉起链路有细粒度 timeline 和 per-node/per-nodehost 指标。
5. 管理操作有矩阵、command log、topology diff、workload impact。
6. 故障和 failover 有完整 timeline。
7. workload 有 smoke 和 benchmark 两类能力。
8. 系统级指标能按阶段/窗口聚合。
9. analysis 能读取所有 schema 化 artifact。
10. 中文可视化报告可离线自动生成。
11. 最终验收 gate 能发现局部补丁、漏接 schema、空 artifact 和 false PASS。
```


## 全局硬约束：每个 stage 都必须遵守

每个 stage 开始前，主 agent 必须重新读取本包中的这些文档：

- `codex_goal_loop_m1/docs/00_INDEX.md`
- `codex_goal_loop_m1/docs/01_GOAL_CONTRACT.md`
- `codex_goal_loop_m1/docs/02_STAGE_MANIFEST.md`
- `codex_goal_loop_m1/docs/03_GLOBAL_COVERAGE_MATRIX.md`
- `codex_goal_loop_m1/docs/04_STRONG_HARNESS_LOOP_ENGINE.md`
- `codex_goal_loop_m1/docs/05_MULTI_AGENT_STAGE_PROTOCOL.md`
- `codex_goal_loop_m1/docs/06_CONTEXT_TRANSFER_PROTOCOL.md`
- 当前 stage 文件
- 上一个 stage 的 `CONTEXT_RELOAD.md`、`COMPLETION.md`、`REVIEW.md`

“场景覆盖”不是只覆盖不同测试形态。覆盖矩阵必须同时覆盖以下维度：

```text
执行形态：
fake / unit / integration / smoke / real local run / dry-run / blocked run / cleanup / failure path

节点规格：
小集群 / 30 / 50 / 100 / 200 / 200+ dry-run planning

功能路径：
config / plan / resource preflight / cluster setup / management ops / workload / fault / failover / metrics / analysis / report / cleanup

数据路径：
schema / artifact writer / artifact reader / analysis aggregator / report renderer / regression check / test fixture

运行结果：
正常成功 / 命令失败 / 超时 / 指标缺失 / cleanup 残留 / report 输入缺失
```

每个 stage 必须执行这些规则：

1. 不能只改某一个具体规模。
2. 不能只改某一个测试。
3. 不能只在某个脚本里临时写字段。
4. 新增字段或指标必须固化到通用 artifact schema。
5. 新增字段或指标必须每次相关运行自动采集。
6. 新增字段或指标必须能被 analysis 读取。
7. 新增字段或指标必须能进入最终中文可视化报告。
8. fake fixture、smoke、真实 30/50/100/200、本地 dry-run/blocked 路径都要有对应测试，或有结构化 skipped / missing / unsupported reason。
9. 运行产物和源码要在当前 stage 就妥善分离，不能把产物整理推迟给后续 stage。
10. 如果某字段只存在于一个规模、一个测试、一个临时脚本、一个 artifact writer，而没有进入 schema / writer / reader / analyzer / renderer / fixture / gate，review 必须 FAIL。
