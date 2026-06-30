# 04_STAGE_MANIFEST.md — 多阶段执行清单

本 manifest 定义 loop 的 stage 顺序。主 agent 必须按顺序执行，除非某 stage 明确被 BLOCKED 且已落盘 blocker。

## L00_LOOP_ENGINE_HARNESS_BOOTSTRAP

### 目标

建立 loop 自身的可验证基础：状态文件 schema、subagent 输出 schema、命令日志格式、anti-regression 检查脚本、stage result 校验脚本。

### 当前 stage harness

必须新增或强化：

1. `schemas/loop_engineering/*.schema.json`
2. `scripts/loop_engineering_validate.py`
3. `tests/loop_engineering/test_loop_state_contract.py`
4. `tests/ci/test_loop_engineering_pack.py`

### 验收标准

1. previous harness 全通过。
2. 能验证 `artifacts/loop_engineering/**/stage_result.json`、subagent JSON、commands.jsonl。
3. anti-regression guardian 有可运行检查入口。
4. 本 stage 的所有 loop 状态与子 agent 输出落盘。

## L01_EXISTING_ARTIFACT_AUDIT_HARD_GATE

### 目标

审计当前 P00-P14 artifact/gate 状态，建立 committed artifact audit gate。重点补齐 P13/P14 被遗漏、空 artifact、历史 gate mismatch、real/dry-run 边界不清的问题。

### 当前 stage harness

必须新增或强化：

1. `scripts/audit_committed_artifacts.py`
2. `schemas/artifact/audit_report.schema.json`
3. `tests/audit/test_committed_artifact_audit.py`
4. `tests/ci/test_committed_artifact_audit_gate.py`

### 验收标准

1. P00-P13 所有自动 phase 的 required artifact 可审计。
2. P13 不得只因为历史 command mismatch 就完全排除在 audit 外；若存在历史 mismatch，必须作为明确 finding 记录，并区分 blocking/non-blocking。
3. P14 必须被识别为 opt-in dry-run，不得被误判为真实 1000 节点 evidence。
4. 空 JSON artifact、缺 schema、缺 producer、缺 run_id、缺 status 必须被发现。

## L02_EVIDENCE_PROVENANCE_DAG

### 目标

构建 artifact provenance DAG：每个分析、报告、可视化结果都能追溯到 source artifact、sha256、producer、schema、phase、run_id。

### 当前 stage harness

必须新增或强化：

1. provenance graph builder
2. DAG schema
3. source artifact hash check
4. report reads artifact but never becomes source-of-truth 的测试

### 验收标准

1. P09 report、P12/P13 scale report、P11 stability report 均能追溯到 source artifact。
2. 任何找不到来源的可视化或分析项必须标记 finding。
3. DAG 输出到 `artifacts/loop_engineering/reports/provenance_graph.json`。

## L03_METRIC_CATALOG_AND_COVERAGE_MATRIX

### 目标

建立统一 metric catalog 与 coverage matrix，覆盖 cluster build、management、workload、observability、fault、failover、stability、cleanup、scale、report/visualization。

### 当前 stage harness

必须新增或强化：

1. `schemas/artifact/metric_catalog.schema.json`
2. `schemas/artifact/coverage_matrix.schema.json`
3. `scripts/build_metric_coverage_matrix.py`
4. tests verifying fake + real artifact coverage

### 验收标准

1. 每个 metric 有 name、unit、source_artifact、scenario、node_count_scope、missing semantics。
2. coverage matrix 必须按 fake/small-real/30/50/100/1000-dry-run 分层。
3. 不能把 1000 dry-run 记为 real coverage。
4. 输出 `artifacts/loop_engineering/reports/metric_catalog.json` 与 `coverage_matrix.json`。

## L04_P13_P14_SCALE_AUDIT_AND_REFRESH

### 目标

对 P13/P14 做强审计：P13 的 50/100 实证、timing、cleanup、scale report、empty artifact、postcheck 兼容；P14 的 1000 dry-run/resource/planner 边界。

### 当前 stage harness

必须新增或强化：

1. P13 audit tests
2. P14 dry-run invariant tests
3. postcheck compatibility extension or separate explicit P13 audit gate
4. p13 timing breakdown schema validation

### 验收标准

1. 50/100 scale rung 必须有非空、schema-valid、status-consistent 的 evidence 或明确 BLOCKER。
2. P13 timing breakdown 必须包含 setup、cluster create、replica config、probe、cleanup、accounting 字段。
3. P14 必须只允许 dry-run/resource/planner，不允许自动真实 1000 集群。
4. 若刷新 artifact，必须重新运行对应命令并记录命令日志；不得手写 PASS。

## L05_REPORTING_V2_FOR_AUDIT_RESULTS

### 目标

把审计结果、metric catalog、coverage matrix、scale ladder、P13 timing 转成可读报告与可视化。

### 当前 stage harness

必须新增或强化：

1. report renderer tests
2. SVG/HTML/CSV golden tests
3. missing metric visualization tests
4. provenance links tests

### 验收标准

至少输出：

```text
artifacts/loop_engineering/reports/index.html
artifacts/loop_engineering/reports/coverage_matrix.csv
artifacts/loop_engineering/reports/coverage_heatmap.svg
artifacts/loop_engineering/reports/scale_ladder.svg
artifacts/loop_engineering/reports/p13_timing_waterfall.svg
artifacts/loop_engineering/reports/missing_metrics.csv
artifacts/loop_engineering/reports/provenance_graph.json
```

所有可视化必须由 JSON/JSONL/CSV artifact 生成，不能硬编码数值。

## L06_SMALL_REAL_SCENARIO_AUDIT_PARITY

### 目标

先把 6 节点真实场景的 audit/metric/report 做齐，作为大集群扩展前的对照组。

### 当前 stage harness

必须覆盖：

1. cluster smoke
2. management ops
3. workload smoke
4. observability smoke
5. fault sandbox
6. failover primary stop
7. stability soak
8. cleanup

### 验收标准

1. fake tests 与 real Valkey 6-node gate 都有对应 harness。
2. 每个真实场景都有统一 metric extraction。
3. failover 中 split-brain 未测时必须显式 MISSING，不得伪造。
4. 报告中能区分 measured、missing、skipped。

## L07_30_50_100_CLUSTER_BUILD_METRICS

### 目标

增强 30/50/100 真实集群建立场景的量化指标采集与审计。

### 当前 stage harness

必须覆盖：

1. resource preflight
2. process/container startup timing
3. cluster meet/create timing
4. slot assignment timing
5. role convergence timing
6. membership convergence
7. SET/GET data-path probe
8. cleanup timing and residual scan
9. 30/50/100 scale report consistency

### 验收标准

1. 30/50/100 都有 scale build metrics。
2. 1000+ 只列为 dry-run/resource/planner。
3. 任何资源不足不能标 PASS，只能 BLOCKED。
4. 可视化必须展示 scale ladder 与 timing breakdown。

## L08_30_50_100_FAULT_FAILOVER_SCENARIOS

### 目标

扩展大集群故障注入与故障接管：30、50、100 真实集群都需要覆盖至少 primary stop failover；可安全实现时覆盖 replica stop、AZ minority/majority partition 或 sandbox delay。

### 当前 stage harness

必须设计并实现：

1. fake deterministic fault/failover tests
2. 30-node real fault/failover gate
3. 50-node real fault/failover gate
4. 100-node real fault/failover gate
5. fault safety guard：禁止 host network/global firewall mutation
6. failover report schema
7. workload before/during/after fault metric windows

### 验收标准

每个 30/50/100 real fault gate 必须输出：

```text
fault_report_<N>.json
failover_report_<N>.json
workload_window_report_<N>.json
valkey_e2e_evidence_fault_<N>.json
cleanup_report_fault_<N>.json
```

必须量化：

1. fault apply latency
2. fault clear latency
3. promotion observed
4. failover latency ms
5. cluster state before/during/after
6. nodes observed before/during/after
7. availability window
8. workload errors/timeouts before/during/after
9. split-brain indicators or explicit MISSING reason
10. cleanup residual count

1000+ 不自动真实故障注入，只做 dry-run planning 与资源估算，除非用户另开明确任务。

## L09_STABILITY_SOAK_MULTI_STAGE_METRICS

### 目标

把稳定性与 soak 从短 smoke 扩展为多阶段 metric model：baseline、steady、fault、recovery、post-recovery。

### 当前 stage harness

必须覆盖：

1. fake soak timeline tests
2. small real soak gate
3. 30/50/100 bounded soak gates or explicitly gated resource-aware profiles
4. latency percentiles
5. memory growth/leak summaries
6. restart delta
7. error taxonomy
8. baseline comparison

### 验收标准

1. 每个 soak profile 输出 JSONL time series。
2. 报告能展示 trend、window comparison、missing metrics。
3. 大集群 soak 不能因时间短而伪造 long-run 结论；短窗口必须标 bounded。

## L10_FULL_CHAIN_FINAL_AUDIT_AND_VISUALIZATION_GATE

### 目标

形成最终全链路审计 gate：fake + small-real + 30/50/100-real + 1000-dry-run 的完整 coverage matrix、metric catalog、provenance DAG、HTML/SVG/CSV 报告。

### 当前 stage harness

必须新增 final gate：

```bash
python3 scripts/final_audit_gate.py --out-dir artifacts/loop_engineering/final_audit
python3 -m pytest -q tests/final_audit
```

### 验收标准

1. 全部 previous harness PASS。
2. final audit gate PASS。
3. coverage matrix 不把 dry-run 当 real。
4. 所有可视化由 artifact 生成。
5. 所有 missing metrics 有 reason 和 impact。
6. final HTML 报告能定位到 source artifact 与 commit SHA。
7. stage_result、global_loop_state、final report 都已 commit + push。
