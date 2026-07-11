# 08_SCHEMA_ARTIFACT_CONTRACT — schema 与 artifact 合同

## 字段新增流程

任何新增字段必须完成以下传播链：

```text
需求定义
  -> schema
  -> writer
  -> fixture
  -> reader
  -> aggregator
  -> renderer
  -> gate
  -> documentation
```

## Artifact 类型

milestone1 至少需要这些 artifact：

```text
run_metadata.json
coverage_matrix.json 或 coverage_matrix.md
setup_timeline.json
runtime_timing_breakdown.json
node_ready_times.jsonl
command_log.jsonl
management_ops_matrix.json
management_operation_results.jsonl
topology_snapshots.jsonl
topology_diffs.jsonl
workload_windows.json
workload_metrics.jsonl
fault_timeline.jsonl
fault_matrix_report.json
failover_latency_samples.jsonl
system_metrics_timeseries.jsonl
analysis_summary.json
zh_report_index.json
```

文件名可根据项目现状调整，但语义必须完整。

## Missing data 规则

不得用 null、空字符串、NaN、Infinity、N/A 表示缺失。

缺失必须结构化：

```json
{
  "status": "MISSING",
  "reason": "why this metric is missing",
  "impact": "what analysis/report cannot conclude"
}
```

或者：

```json
{
  "status": "SKIPPED_WITH_REASON",
  "reason": "why this path is intentionally skipped"
}
```

## 空 artifact 规则

这些 artifact 不允许为空：

- command log。
- metrics JSONL。
- timeline JSONL。
- management operation results。
- fault rows。
- system metrics samples。
- report index。

如果确实没有样本，必须写结构化 skipped artifact，而不是空文件。
