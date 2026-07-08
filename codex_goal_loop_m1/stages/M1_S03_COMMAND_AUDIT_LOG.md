# M1-S03 — 命令级审计日志补全


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



## 目标

所有关键命令进入 command log，任何 PASS 的管理/故障/cleanup 操作都可追溯到底层命令。

## 覆盖对象

```text
cluster meet
addslots
replicate
cluster info
cluster nodes
reshard
setslot
migrate / move slot
rebalance
failover
forget
reset
shutdown / stop / restart
fault apply / clear
cleanup
probe
```

## 每条命令字段

```text
operation_id
step_id
command_id
host_id
node_logical_id
client_port
argv
started_at_unix_ms
ended_at_unix_ms
duration_ms
exit_code
stdout_path 或 stdout_sha256
stderr_path 或 stderr_sha256
retry_index
timeout_ms
status
error_type
```

## 必做项

1. 建立通用 command log schema。
2. 所有运行路径使用统一 command recorder。
3. 替换只直接调用 docker/valkey-cli 但不记录的路径。
4. fake fixture 要有成功、失败、超时、retry 样本。
5. smoke/integration 测试必须校验 command log 非空。
6. analysis 聚合慢命令 TopN、失败命令、重试命令。
7. 中文报告展示慢命令 TopN、失败命令、重试命令。
8. cleanup 命令也必须记录。
9. 已存在空 command log 的问题必须被 gate 捕获。

## 强 harness

gate 必须检查：

- command log 非空。
- 必需字段完整。
- PASS 操作能追溯 command log。
- 失败命令不被吞掉。
- 真实不可用路径不会伪造 command。



## stage 完成条件

只有同时满足以下条件，主 agent 才能认为当前 stage 完成：

1. 当前 stage 所有必做项完成。
2. 覆盖矩阵已经更新。
3. 相关 schema / artifact writer / artifact reader / analyzer / report renderer / fixtures / gates 都已同步。
4. fake/unit/integration/smoke gates 已运行。
5. 真实本地运行 gate 如果环境无法执行，必须输出结构化 blocked artifact；不得伪造 PASS。
6. review subagent 最终结论是 `PASS`。
7. git diff 只包含本 stage 合理范围。
8. 已 commit。
9. 已 push 到当前工作分支。
10. 已写入下个 stage 可读取的 handoff 文档。

严禁在 review FAIL 或 gates FAIL 时 commit 并进入下一 stage。
