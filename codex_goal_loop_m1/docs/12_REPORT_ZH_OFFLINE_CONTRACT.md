# 12_REPORT_ZH_OFFLINE_CONTRACT — 中文离线报告合同

## 目标

报告必须由程序自动生成，中文展示，不依赖 LLM、不依赖外网、不依赖在线图表服务。

## 输入

报告只允许读取本地 schema 化 artifact：

```text
run metadata
setup timeline
command log
management matrix
workload metrics
fault timeline
failover samples
system metrics
cleanup report
coverage matrix
analysis summary
```

## 输出

```text
reports/index.html
reports/report.md
reports/exports/*.csv
reports/assets/*.svg
reports/report_index.json
```

## 页面内容

报告必须包含：

1. 总览页。
2. 运行元数据。
3. 集群拉起瀑布图。
4. 阶段耗时 TopN。
5. 慢节点 TopN。
6. 慢命令 TopN。
7. 管理操作矩阵。
8. 管理操作 topology diff 摘要。
9. 故障 timeline。
10. failover latency 分布。
11. workload impact 对比。
12. 系统资源趋势。
13. 异常节点列表。
14. missing metrics 聚合。
15. cleanup 结果。
16. 结论摘要。

## 中文要求

报告中的标题、表头、解释文字、结论摘要必须是中文。代码字段名可以保留英文，但必须有中文说明。

## 离线要求

不允许：

- 调用 LLM。
- 调用外部 API。
- 引入 CDN。
- 使用在线 chart 服务。
- 依赖浏览器联网下载资源。

允许：

- 生成静态 HTML。
- 生成 Markdown。
- 生成 CSV。
- 生成本地 SVG。
- 使用项目内置模板。
