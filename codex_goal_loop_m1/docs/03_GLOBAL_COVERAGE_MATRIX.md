# 03_GLOBAL_COVERAGE_MATRIX — 全局覆盖矩阵

## 目的

覆盖矩阵用来防止 Codex 只在某一个规格、某一个脚本、某一种测试或某一个 artifact 中补字段。每个 stage 都必须维护覆盖矩阵。

## 维度

### 执行形态

```text
fake
unit
integration
smoke
real_local_run
dry_run
blocked_run
cleanup
failure_path
```

### 节点规格

```text
small_cluster
scale_30
scale_50
scale_100
scale_200
scale_200_plus_dry_run_planning
```

### 功能路径

```text
config
plan
resource_preflight
cluster_setup
management_ops
workload
fault
failover
metrics
analysis
report
cleanup
```

### 数据路径

```text
schema
artifact_writer
artifact_reader
analysis_aggregator
report_renderer
regression_check
test_fixture
```

### 运行结果

```text
success
command_failure
timeout
missing_metric
cleanup_residual
report_input_missing
```

## 字段传播合同

任何新增字段或指标，都必须至少确认这些位置：

```text
schema:              字段在 JSON schema 或等价 validator 中定义
writer:              运行时会写出字段
reader:              analysis 能读字段
aggregator:          analysis 会聚合字段
renderer:            中文报告会展示字段
fixture:             fake / unit fixture 有字段样本
smoke:               smoke 测试能看到字段
real_path:           真实本地运行路径会产生字段
dry_run_or_blocked:  dry-run 或 blocked path 有 skipped/missing reason
regression:          gate 能检查字段没有丢失
```

## 覆盖矩阵最小表头

```text
stage_id
change_id
field_or_behavior
execution_shape
scale_rung
functional_path
data_path
outcome_class
coverage_status
evidence_path
test_or_gate
missing_or_skipped_reason
owner_notes
```

`coverage_status` 只能是：

```text
PASS
FAIL
SKIPPED_WITH_REASON
UNSUPPORTED_WITH_REASON
BLOCKED_WITH_REASON
```

空白、N/A、todo、later 都不允许进入最终矩阵。

## 强制失败条件

review subagent 发现以下任一情况，必须 FAIL：

- 字段只在一个运行规模出现。
- 字段只在一个真实脚本出现。
- 字段只在 fake fixture 出现。
- artifact writer 有字段，但 analyzer 不读。
- analyzer 读字段，但 report 不展示。
- report 展示字段，但 schema 不约束。
- fake/smoke 测试没有覆盖。
- 真实路径不可执行却被标记 PASS。
- command log、metrics JSONL、timeline JSONL 为空却标记 PASS。
