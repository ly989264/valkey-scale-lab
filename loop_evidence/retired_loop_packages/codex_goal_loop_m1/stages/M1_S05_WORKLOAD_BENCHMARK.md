# M1-S05 — workload 从 smoke 升级为 benchmark


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

把轻量 data-path smoke workload 升级为可分析性能影响的 benchmark workload。

## Workload profiles

```text
smoke
uniform
hotspot
mixed_rw
write_heavy
read_heavy
```

## 配置字段

```text
target_qps
duration_seconds
warmup_seconds
connections
pipeline
keyspace
value_size
hash_slot_distribution
read_ratio
write_ratio
timeout_ms
```

## 采集窗口

```text
baseline
pre_event
event
recovery
post_recovery
all_run
```

## 指标字段

```text
requested_qps
achieved_qps
throughput_ratio
ok_ops
error_ops
error_rate
latency_p50
latency_p90
latency_p95
latency_p99
latency_p999
timeout_count
connection_error_count
moved_count
ask_count
cluster_down_count
readonly_count
tryagain_count
```

## 必做项

1. 保留 smoke workload，但新增 benchmark workload。
2. 实现全 slot key generator，不能只用固定 hash tag。
3. 支持低强度 benchmark，让小集群也能跑。
4. 支持管理操作、故障、failover 挂 workload impact。
5. 更新 workload schema 和 workload window artifact。
6. fake fixture 覆盖每种 profile。
7. analysis 聚合 QPS、p99、error_rate delta。
8. 中文报告展示故障前/中/后 QPS、p99、error_rate 对比。
9. 报告必须说明 workload 是否覆盖全 slot。

## 强 harness

gate 必须检查：

- smoke 和 benchmark 被区分。
- uniform profile 覆盖多个 slot。
- 固定 hash tag 不再作为唯一 workload 路径。
- 小集群也有低强度 benchmark。
- workload impact 可被 management/fault/failover 引用。



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
