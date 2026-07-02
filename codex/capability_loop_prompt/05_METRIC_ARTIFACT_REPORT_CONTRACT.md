# 05 — Metric, Artifact, Analysis, Report Contract

## 1. 统一证据链

每个能力必须产生一条可追踪链路：

```text
+------------------+      +------------------+      +------------------+      +------------------+
| operation/fault  | ---> | raw observations | ---> | analysis summary | ---> | report/chart     |
| real execution   |      | metrics/events   |      | quantified       |      | visualized       |
+------------------+      +------------------+      +------------------+      +------------------+
        |                         |                         |                         |
        v                         v                         v                         v
  operation_id/fault_id      run_id + window_id         source checksums          source checksums
```

没有这条链路，能力不能 PASS。

## 2. 必须采集的 raw observations

每个 scenario 至少包含：

```text
run_metadata.json
config_effective.json
cluster_plan.json
valkey_e2e_evidence.json
operation_event.jsonl
fault_event.jsonl
metrics_timeseries.jsonl
cluster_topology_samples.jsonl
workload_window.jsonl
events.jsonl
cleanup_report.json
```

故障类还需要：

```text
fault_report.json
failover_report.json
split_brain_report.json
```

管理类还需要：

```text
management_ops_report.json
slot_movement_report.json
rolling_restart_report.json
```

稳定性需要：

```text
stability_report.json
soak_timeseries_summary.json
```

## 3. Window model

窗口枚举：

```text
before
operation_or_fault_apply
during
clear_or_recovery_start
after_recovery
all_run
```

每条 workload/metrics sample 必须有：

```json
{
  "run_id": "...",
  "scenario_id": "...",
  "scale_nodes": 30,
  "window_id": "during",
  "operation_id": "optional",
  "fault_id": "optional",
  "timestamp": "...",
  "sample_interval_ms": 1000
}
```

## 4. Workload metrics

每个 window 必须量化：

```json
{
  "requested_qps": 1000,
  "achieved_qps": 973.2,
  "qps_drop_ratio_from_before": 0.23,
  "latency_ms": {
    "p50": 1.2,
    "p95": 8.4,
    "p99": 19.8
  },
  "errors": {
    "total": 42,
    "rate": 0.0042,
    "by_class": {
      "timeout": 12,
      "clusterdown": 3,
      "connection": 27
    }
  }
}
```

缺 percentile 不允许填 0。必须：

```json
{"value": null, "status": "MISSING", "reason": "not_enough_samples"}
```

但目标能力闭环 stage 不应 PASS 在关键字段 MISSING 上。

## 5. Failover metrics

必须量化：

```text
fault_apply_at
last_success_before_unavailable
first_error_at
first_new_primary_seen_at
slot_coverage_lost_at
slot_coverage_recovered_at
first_success_after_recovery
promotion_latency_ms
unavailable_window_ms
slot_coverage_recovery_ms
role_transition_evidence_path
```

promotion 不能靠推测。至少需要 topology sample 或 independent probe evidence。

## 6. Split-brain metrics

必须区分：

| 字段 | 含义 |
|---|---|
| `dual_primary_observed` | 同一 shard/slot 在同一窗口出现冲突 primary claim |
| `duration_ms` | 冲突窗口持续时间；未冲突则 0 |
| `status` | `OBSERVED` 或 `ABSENT_OBSERVED`；sample coverage 不足时 stage FAIL |
| `evidence_samples` | raw `CLUSTER NODES` sample paths |
| `inference_notes` | minority/majority 推断，不可替代 evidence |

如果 Valkey 正常避免 split-brain，合法结果是：

```json
{
  "dual_primary_observed": false,
  "duration_ms": 0,
  "status": "ABSENT_OBSERVED",
  "sample_coverage": "PASS"
}
```

## 7. Analysis summary

每个 scenario 生成：

```json
{
  "schema_version": "v1",
  "artifact_type": "capability_analysis_summary",
  "scenario_id": "network_partition_majority_30",
  "scale_nodes": 30,
  "status": "PASS",
  "computed_metrics": {
    "qps_drop_ratio": 0.31,
    "p95_latency_delta_ms": 12.8,
    "error_rate_during": 0.042,
    "unavailable_window_ms": 1840,
    "slot_recovery_ms": 2300
  },
  "source_artifacts": [
    {"path": "...", "sha256": "..."}
  ]
}
```

## 8. 可视化要求

图表必须从 artifact 生成，不能从临时内存或 narrative 生成。每个图表在 `report_index.json` 记录：

```json
{
  "chart_id": "qps_latency_fault_window_network_partition_30",
  "path": "reports/.../qps_latency.svg",
  "source_artifacts": [
    {"path": "artifacts/.../workload_window.jsonl", "sha256": "..."}
  ],
  "regenerated_at": "...",
  "deterministic_inputs": true
}
```

建议图表：

```text
scenario timeline
QPS before/during/after
latency p50/p95/p99 over time
error rate over time
failover duration waterfall
slot coverage timeline
split-brain indicator timeline
soak stability trend
scale comparison 30/50/100
```
