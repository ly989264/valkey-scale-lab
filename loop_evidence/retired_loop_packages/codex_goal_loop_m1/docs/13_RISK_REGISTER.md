# 13_RISK_REGISTER — 风险登记

## 已知风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| Codex 只改某个具体规模 | 指标覆盖不完整 | 覆盖矩阵 + review 强制检查 |
| command log 为空但矩阵 PASS | 审计不可用 | command log non-empty gate |
| 报告只展示静态摘要 | 无法定位瓶颈 | 增加瀑布图、TopN、timeline |
| workload 太轻 | 无法分析性能影响 | 新增 benchmark workload |
| fake 与 real schema 分叉 | 测试不能代表真实运行 | schema 单一来源 |
| blocked run 被伪造成 PASS | 结果不可信 | BLOCKED_WITH_REASON 规则 |
| 产物混入源码 | 仓库膨胀和 diff 噪声 | M1-S01 建立 runs 目录 |
| context compact 丢约束 | stage 跑偏 | 每 stage 读取 docs + handoff |
| 中文报告依赖 LLM | 离线不可用 | 程序模板化生成 |
| long soak 被误做 | 时间失控 | soak 不在本 loop 内 |

## review 必查风险

每次 review 必须检查：

- 是否新增了 hard-coded PASS。
- 是否只检查文件存在。
- 是否有空 JSONL。
- 是否新增了未接入 schema 的字段。
- 是否新增了未接入 report 的指标。
- 是否把真实运行结果写死。
- 是否破坏旧路径兼容。
