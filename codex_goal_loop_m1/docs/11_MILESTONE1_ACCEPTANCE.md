# 11_MILESTONE1_ACCEPTANCE — milestone1 最终验收标准

## 验收对象

```text
fake fixtures
unit tests
integration tests
本地 smoke
本地小集群真实运行
本地 30 节点真实运行
本地 50 节点真实运行
本地 100 节点真实运行
本地 200 节点真实运行
200+ dry-run planning
blocked run
cleanup failure path
report generation path
```

## 验收内容

1. 集群能拉起。
2. 集群最终 clean。
3. 管理操作有 matrix。
4. 管理操作有 command log。
5. 故障有 timeline。
6. failover 有 latency 数据。
7. workload 有前/中/后对比。
8. 系统指标有采集。
9. analysis 能读取全部 artifact。
10. 中文可视化报告能自动生成。
11. cleanup 后无残留。
12. missing metrics 有明确 reason 且被聚合。
13. 新增字段没有只停留在单一路径。
14. report 不依赖 LLM 或外网。

## 最终 gate 输出

最终 gate 必须输出：

```text
milestone1_status: PASS / FAIL / BLOCKED_WITH_REASON

cluster_setup: PASS / FAIL
management_ops: PASS / FAIL
fault_failover: PASS / FAIL
workload_benchmark: PASS / FAIL
system_metrics: PASS / FAIL
analysis: PASS / FAIL
visual_report_zh: PASS / FAIL
cleanup: PASS / FAIL
cross_scenario_coverage: PASS / FAIL
```

## 必须 FAIL 的情况

- command log 为空。
- metrics JSONL 为空。
- timeline JSONL 为空。
- 报告不能离线生成。
- 报告不是中文。
- 新字段只在单一规模出现。
- 新字段没有 schema。
- 新字段没有 fixture。
- 新字段没有 analyzer。
- 新字段没有 report renderer。
- 真实运行失败却标记 PASS。
