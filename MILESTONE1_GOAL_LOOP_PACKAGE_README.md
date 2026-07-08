# valkey-scale-lab milestone1 goal-loop package

这是给 `ly989264/valkey-scale-lab` 使用的 Codex App goal-mode loop-engineering 文档包。

目标：用 Codex App 的 goal 模式启动一个受强 harness 看护的多 stage loop，完成 milestone1：本地至多 200 个真实 Valkey 节点的集群拉起、管理、故障注入、故障转移、指标采集、分析和中文自动化可视化报告。

本包只包含 Markdown 文件，不包含 shell 脚本，不负责替你放置文件。解压本 zip 到仓库根目录即可得到 `codex_goal_loop_m1/` 目录；顶层说明文件为 `MILESTONE1_GOAL_LOOP_PACKAGE_README.md`，不会覆盖仓库原有 README。

## 使用方式

1. 打开目标仓库：

```text
https://github.com/ly989264/valkey-scale-lab
```

建议从你指定的目标提交开始：

```text
211dcbc74a3a6dd41ee1c4421cf0f9bbd98a0ffe
```

2. 将本包中的 `codex_goal_loop_m1/` 目录放到仓库根目录。

3. 打开 Codex App，并使用 goal 模式创建一个新任务。

4. 将下面文件的完整内容粘贴为 goal prompt：

```text
codex_goal_loop_m1/prompts/GOAL_MODE_START_PROMPT.md
```

5. goal 启动后，主 agent 必须按 stage manifest 逐个 stage 推进：

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

长期稳定性 soak stage 已从本 loop 中删除，不在本 milestone1 goal 中执行。

## 成功标准

这个 loop 的成功标准不是“代码看起来改了”，而是：

- 每个 stage 都被 design / worker / review 多 agent 流程处理。
- 每个 stage 都受强 harness gate 看护。
- 每个 stage 的改动进入通用路径，不是只补一个脚本、一个规模、一个测试或一个 artifact。
- 每个新增字段都贯穿 schema / artifact writer / artifact reader / analyzer / report renderer / fixture / gate。
- 每个 stage review PASS 后才允许 commit 和 push。
- 最终可以离线自动生成中文可视化报告，不依赖 LLM。
