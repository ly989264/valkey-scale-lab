"""Every human sentence the offline report says, in each language it says it.

The renderer used to carry its prose inline, which made the report Chinese by
construction rather than by choice - and the operator's own goal for a 1280-node
run is a readable report handed to a team, which is not a claim any single
language can make for every team.

Two rules hold this together and both matter more than the table itself.

**The Chinese is copied, not rewritten.** Every `zh` value here is the exact
string the renderer emitted before this file existed, so a report rendered in
Chinese is byte-identical to the one the frozen runs carry. That is checked
rather than asserted: `tests/report/test_report_rendering.py` renders a stored
analysis and compares.

**A key that is missing raises rather than falling back.** A language that
silently borrowed the other's sentence would produce a report that looks
translated and is not, which is worse than one that fails to build - the same
reason nothing in this product estimates an absent measurement.

Interpolated sentences are `str.format` templates with **named** fields, so a
translation may reorder them. Positional fields could not, and word order is the
first thing that moves between these two languages.
"""

from __future__ import annotations

from typing import Mapping

LANGUAGES = ("zh", "en")

DEFAULT_LANGUAGE = "zh"

#: Where a language's report is written, relative to the run's report root. The
#: Chinese report keeps the directory it has always had, because every frozen
#: run and every document that names a path names that one.
DIRECTORY_SUFFIX = {"zh": "", "en": "-en"}


class UnknownLanguage(ValueError):
    """A language this catalog does not carry."""


_CATALOG: dict[str, dict[str, str]] = {
    # -- conclusion summary ------------------------------------------------
    "concl.setup": {
        "zh": "- 主要启动耗时: {metric} = {value} ms。",
        "en": "- Longest setup stage: {metric} = {value} ms.",
    },
    "concl.node": {
        "zh": "- 最慢节点: {node}，ready_ms={ready}。",
        "en": "- Slowest node: {node}, ready_ms={ready}.",
    },
    "concl.command": {
        "zh": "- 最慢命令: {command} {kind} = {value} ms。",
        "en": "- Slowest command: {command} {kind} = {value} ms.",
    },
    "concl.management": {
        "zh": "- 最慢管理操作: {operation} = {value} ms。",
        "en": "- Slowest management operation: {operation} = {value} ms.",
    },
    "concl.workload": {
        "zh": "- Workload 瓶颈窗口: {profile} {window}，p99={p99} ms，错误率={error_rate}。",
        "en": "- Worst workload window: {profile} {window}, p99={p99} ms, error rate={error_rate}.",
    },
    "concl.failover": {
        "zh": "- Failover p95={p95} ms；split-brain max={split_brain} ms。",
        "en": "- Failover p95={p95} ms; split-brain max={split_brain} ms.",
    },
    "concl.resource": {
        "zh": "- 资源异常节点: {node}，rss_sum={rss} bytes。",
        "en": "- Most resource-loaded node: {node}, rss_sum={rss} bytes.",
    },
    "concl.cleanup": {
        "zh": "- Cleanup 状态: {status}，剩余资源={remaining}。",
        "en": "- Cleanup status: {status}, resources remaining={remaining}.",
    },
    "concl.missing": {
        "zh": "- 缺失指标数量: {count}；缺失项保留原因，不用估算值替代。",
        "en": "- Missing metrics: {count}. Each keeps its reason; none is replaced by an estimate.",
    },
    # -- document furniture ------------------------------------------------
    "doc.title": {
        "zh": "中文自动化可视化分析报告",
        "en": "Automated Offline Analysis Report",
    },
    "doc.standfirst": {
        "zh": "本报告由本地 artifact 自动生成，不调用 LLM、不访问外网、不依赖在线图表服务。所有结论来自 schema 化 JSON/JSONL、CSV 和本地 SVG 产物。",
        "en": "Generated from this run's own local artifacts. It calls no LLM, reaches no network, and depends on no online charting service. Every figure comes from schema-validated JSON/JSONL, CSV and locally drawn SVG.",
    },
    "doc.html_lang": {"zh": "zh-CN", "en": "en"},
    "doc.eyebrow_offline": {"zh": "离线 artifact 渲染", "en": "offline artifact render"},
    "doc.eyebrow_no_llm": {"zh": "不调用 LLM", "en": "no LLM"},
    "doc.status": {"zh": "状态", "en": "Status"},
    "doc.source_stage": {"zh": "来源阶段", "en": "Source stage"},
    "doc.note": {
        "zh": "缺失项一律保留原因，不用估算值替代；下表每一行都可回溯到运行自身已校验的 artifact。",
        "en": "Every absence keeps its reason and is never replaced by an estimate; each row below traces back to an artifact this run validated itself.",
    },
    "doc.footer": {
        "zh": "本页与同目录下的 CSV、SVG 均由本项目脚本离线生成，可在无外网环境中重复产出；每个数字都取自运行已写出并校验的 artifact，不做二次推算。",
        "en": "This page and the CSV and SVG files beside it are produced offline by this project's own scripts and can be regenerated without network access. Every number is taken from an artifact the run wrote and validated; nothing is recomputed here.",
    },
    # -- verdict strip -----------------------------------------------------
    "verdict.run_status": {"zh": "运行状态", "en": "Run status"},
    "verdict.total_commands": {"zh": "命令总数", "en": "Commands"},
    "verdict.failed_commands": {"zh": "失败命令", "en": "Failed"},
    "verdict.retry_commands": {"zh": "重试命令", "en": "Retried"},
    "verdict.missing_metrics": {"zh": "缺失指标", "en": "Missing metrics"},
    # -- section headings --------------------------------------------------
    "sec.overview": {"zh": "总览页", "en": "Overview"},
    "sec.conclusions": {"zh": "结论摘要", "en": "Conclusions"},
    "sec.run_metadata": {"zh": "运行元数据", "en": "Run metadata"},
    "sec.findings": {"zh": "分析发现", "en": "Findings"},
    "sec.missing_metrics": {"zh": "缺失指标", "en": "Missing metrics"},
    "sec.setup_waterfall": {"zh": "集群拉起瀑布图", "en": "Cluster bring-up waterfall"},
    "sec.stage_durations": {"zh": "阶段耗时排序", "en": "Stage durations, ranked"},
    "sec.slow_nodes": {"zh": "慢节点 TopN", "en": "Slowest nodes"},
    "sec.slow_commands": {"zh": "慢命令 TopN", "en": "Slowest commands"},
    "sec.failed_commands": {"zh": "失败命令", "en": "Failed commands"},
    "sec.retry_commands": {"zh": "重试命令", "en": "Retried commands"},
    "sec.command_coverage": {"zh": "命令审计覆盖", "en": "Command audit coverage"},
    "sec.management_matrix": {"zh": "管理操作矩阵", "en": "Management operation matrix"},
    "sec.topology_diff": {"zh": "管理 topology diff 摘要", "en": "Management topology diff summary"},
    "sec.workload": {"zh": "Workload 基准压测", "en": "Workload benchmark"},
    "sec.fault_timeline": {"zh": "故障 Timeline", "en": "Fault timeline"},
    "sec.failover_distribution": {"zh": "Failover 延迟分布", "en": "Failover latency distribution"},
    "sec.split_brain": {"zh": "Split-brain 窗口", "en": "Split-brain windows"},
    "sec.fault_workload": {"zh": "故障期间 Workload 影响", "en": "Workload impact during faults"},
    "sec.resource_trends": {"zh": "资源观测趋势", "en": "Resource observation trends"},
    "sec.resource_nodes": {"zh": "资源异常节点 TopN", "en": "Most resource-loaded nodes"},
    "sec.charts": {"zh": "图表", "en": "Charts"},
    "sec.generated_files": {"zh": "生成表格", "en": "Generated files"},
    # -- table column headings --------------------------------------------
    "col.conclusion": {"zh": "artifact 派生结论", "en": "Conclusion derived from artifacts"},
    "col.field": {"zh": "字段", "en": "Field"},
    "col.value": {"zh": "值", "en": "Value"},
    "col.metric": {"zh": "指标", "en": "Metric"},
    "col.status": {"zh": "状态", "en": "Status"},
    "col.reason": {"zh": "原因", "en": "Reason"},
    "col.stage_metric": {"zh": "阶段指标", "en": "Stage metric"},
    "col.duration_ms": {"zh": "耗时 ms", "en": "Duration ms"},
    "col.node": {"zh": "节点", "en": "Node"},
    "col.role": {"zh": "角色", "en": "Role"},
    "col.command": {"zh": "命令", "en": "Command"},
    "col.operation": {"zh": "操作", "en": "Operation"},
    "col.kind": {"zh": "类型", "en": "Kind"},
    "col.command_kind": {"zh": "命令类型", "en": "Command kind"},
    "col.count": {"zh": "数量", "en": "Count"},
    "col.command_count": {"zh": "命令数", "en": "Commands"},
    "col.workload_profile": {"zh": "压测 profile", "en": "Workload profile"},
    "col.window": {"zh": "采集窗口", "en": "Window"},
    # The resource table's first column has always been the shorter word, and a
    # byte-comparison against the frozen report is what caught the two keys below
    # being folded into their near-neighbours.
    "col.resource_window": {"zh": "窗口", "en": "Window"},
    "col.achieved_qps": {"zh": "实际 QPS", "en": "Achieved QPS"},
    "col.p99_ms": {"zh": "p99 延迟 ms", "en": "p99 latency ms"},
    "col.error_rate": {"zh": "错误率", "en": "Error rate"},
    "col.sample": {"zh": "样本", "en": "Sample"},
    "col.observed_events": {"zh": "观察事件数", "en": "Events observed"},
    "col.missing_events": {"zh": "缺失事件", "en": "Events missing"},
    "col.fault_type": {"zh": "故障类型", "en": "Fault type"},
    "col.client_unavailable_ms": {"zh": "客户端不可用 ms", "en": "Client unavailable ms"},
    "col.workload_recovery_ms": {"zh": "workload 恢复 ms", "en": "Workload recovery ms"},
    "col.samples": {"zh": "样本数", "en": "Samples"},
    "col.rss_sum": {"zh": "RSS 汇总 bytes", "en": "RSS total bytes"},
    "col.fd_sum": {"zh": "FD 汇总", "en": "FD total"},
    "col.missing_count": {"zh": "缺失数", "en": "Missing"},
    # -- inline prose ------------------------------------------------------
    "workload.coverage_md": {
        "zh": "- 覆盖 profile: {profiles}",
        "en": "- Profiles covered: {profiles}",
    },
    "workload.slot_coverage_md": {
        "zh": "- 全 slot 覆盖: {covered}。该值来自 workload_windows.json 的 hash_slot_coverage，用于确认基准压测不是只走固定 hash tag。",
        "en": "- Full slot coverage: {covered}. Taken from hash_slot_coverage in workload_windows.json, which is what confirms the benchmark did not run against one fixed hash tag.",
    },
    "workload.coverage_html": {
        "zh": "覆盖 profile: <code>{profiles}</code>；全 slot 覆盖: <code>{covered}</code>。该结论来自本地 workload artifact，不依赖 LLM 或外网。",
        "en": "Profiles covered: <code>{profiles}</code>; full slot coverage: <code>{covered}</code>. Both come from local workload artifacts, with no LLM and no network.",
    },
    "workload.window_md": {
        "zh": "- {profile} {window}: 实际 QPS={qps}，p99 延迟 ms={p99}，错误率={error_rate}",
        "en": "- {profile} {window}: achieved QPS={qps}, p99 latency ms={p99}, error rate={error_rate}",
    },
    "svg.workload_bar": {
        "zh": "QPS={qps} p99={p99} 错误率={error_rate}",
        "en": "QPS={qps} p99={p99} error rate={error_rate}",
    },
    "svg.workload_aria": {
        "zh": "Workload QPS p99 错误率",
        "en": "Workload QPS p99 error rate",
    },
    "svg.workload_title": {
        "zh": "Workload QPS / p99 / 错误率",
        "en": "Workload QPS / p99 / error rate",
    },
    "svg.command_latency": {"zh": "命令耗时分布", "en": "Command latency distribution"},
    "svg.management_duration": {"zh": "管理操作耗时排序", "en": "Management operation durations"},
    "img.workload_alt": {
        "zh": "Workload QPS p99 错误率对比",
        "en": "Workload QPS, p99 and error rate compared",
    },
    "img.metric_chart_alt": {
        "zh": "ANALYSIS_REPORTING artifact metrics chart",
        "en": "ANALYSIS_REPORTING artifact metrics chart",
    },
    # -- "nothing to draw" and "nothing to list" ---------------------------
    "empty.setup_svg": {
        "zh": "setup_telemetry.json 未提供可绘制的数值阶段耗时。",
        "en": "setup_telemetry.json supplied no numeric stage durations to draw.",
    },
    "empty.command_svg": {
        "zh": "command_log.jsonl 未提供可绘制的命令耗时。",
        "en": "command_log.jsonl supplied no command durations to draw.",
    },
    "empty.management_svg": {
        "zh": "management_operation_results.jsonl 未提供可绘制的管理操作耗时。",
        "en": "management_operation_results.jsonl supplied no management durations to draw.",
    },
    "empty.topology_svg": {
        "zh": "management_topology_diffs.jsonl 未提供 topology diff。",
        "en": "management_topology_diffs.jsonl supplied no topology diff.",
    },
    "empty.workload_rows": {"zh": "无 workload benchmark 行", "en": "no workload benchmark rows"},
    "empty.fault_events": {
        "zh": "无 fault_timeline_events.jsonl 输入",
        "en": "no fault_timeline_events.jsonl input",
    },
    "empty.fault_workload": {
        "zh": "无 fault workload impact 输入",
        "en": "no fault workload impact input",
    },
    "empty.resource_observation": {
        "zh": "无 resource_observation.json 输入",
        "en": "no resource_observation.json input",
    },
    "empty.stage_durations": {"zh": "无可排序的阶段耗时", "en": "no stage durations to rank"},
    "empty.slow_nodes": {"zh": "无慢节点样本", "en": "no slow-node samples"},
    "empty.slow_commands": {"zh": "无慢命令样本", "en": "no slow-command samples"},
    "empty.command_log": {"zh": "无 command log 样本", "en": "no command log samples"},
    "empty.management": {"zh": "无管理操作样本", "en": "no management operation samples"},
    "empty.topology": {"zh": "无 topology diff 样本", "en": "no topology diff samples"},
    "empty.workload": {"zh": "无 workload benchmark 样本", "en": "no workload benchmark samples"},
    "empty.fault_timeline_samples": {"zh": "无 fault timeline 样本", "en": "no fault timeline samples"},
    "empty.fault_timeline_artifact": {"zh": "无 fault timeline artifact", "en": "no fault timeline artifact"},
    "empty.fault_workload_input": {
        "zh": "无故障期间 workload impact 输入",
        "en": "no workload-impact-during-fault input",
    },
    "empty.resource_analysis": {"zh": "无 resource analysis 输入", "en": "no resource analysis input"},
    "empty.resource_nodes": {"zh": "无异常节点排序输入", "en": "no input to rank loaded nodes"},
    "empty.setup_telemetry": {"zh": "未提供 setup telemetry", "en": "no setup telemetry supplied"},
    "empty.fault_timeline_csv": {"zh": "无故障 timeline 输入", "en": "no fault timeline input"},
    # -- reasons the adapter records, which land in the data ---------------
    "reason.no_timings": {
        "zh": "runtime_timing_breakdown 未提供 timings",
        "en": "runtime_timing_breakdown supplied no timings",
    },
    "reason.no_per_node_ready": {
        "zh": "full-flow 生命周期未记录单节点 ready 时间，不用阶段总时长估算",
        "en": "the full-flow lifecycle records no per-node ready time, and a stage total is not used to estimate one",
    },
    "reason.no_command_audit": {
        "zh": "未找到 command_audit 产物",
        "en": "no command_audit artifact found",
    },
    "reason.no_management_ops": {
        "zh": "management_sequence 未提供 operations",
        "en": "management_sequence supplied no operations",
    },
    "reason.no_workload_windows": {
        "zh": "workload_windows 未提供窗口",
        "en": "workload_windows supplied no windows",
    },
    "reason.latency_not_observed": {
        "zh": "该延迟未被观测",
        "en": "this latency was not observed",
    },
    "reason.no_fault_sequence": {
        "zh": "未找到 fault_sequence.json",
        "en": "no fault_sequence.json found",
    },
    "reason.no_client_outage_measure": {
        "zh": "该故障场景不测量客户端不可用窗口；见 Failover 延迟分布",
        "en": "this fault scenario does not measure a client-unavailability window; see the failover latency distribution",
    },
    "reason.no_fault_scenarios": {
        "zh": "fault_sequence 未记录场景",
        "en": "fault_sequence recorded no scenarios",
    },
    "reason.no_split_brain": {
        "zh": "full-flow 故障通道不制造脑裂，未观测该窗口",
        "en": "the full-flow fault lane creates no split brain, so this window was not observed",
    },
    "reason.no_cluster_down": {
        "zh": "full-flow 故障通道未观测 cluster-down 窗口",
        "en": "the full-flow fault lane did not observe a cluster-down window",
    },
    "reason.no_resource_analyses": {
        "zh": "scalable_stability_observation 未提供 resource_analyses",
        "en": "scalable_stability_observation supplied no resource_analyses",
    },
    "reason.no_per_node_resource": {
        "zh": "资源观测按 sampler 聚合，未保留单节点序列，不做估算排名",
        "en": "resource observation aggregates per sampler and keeps no per-node series, so no ranking is estimated",
    },
    "reason.no_git_sha": {
        "zh": "full-flow 运行未记录 git_sha",
        "en": "a full-flow run records no git_sha",
    },
    "reason.no_valkey_version": {
        "zh": "full-flow 运行未在 analysis 中记录 valkey 版本，见 generated_valkey_configs_manifest",
        "en": "a full-flow run records no Valkey version in the analysis; see generated_valkey_configs_manifest",
    },
    "reason.no_baseline": {
        "zh": "本报告不与冻结基线比较；差异比对由 diff_stage_artifacts.py 负责",
        "en": "this report does not compare against a frozen baseline; diff_stage_artifacts.py owns that comparison",
    },
}


def messages(lang: str = DEFAULT_LANGUAGE) -> Mapping[str, str]:
    """Every sentence, in one language.

    Raises rather than defaulting on an unknown language, because a report that
    quietly came out in the wrong one would be worse than one that refused: the
    operator would have no way to tell from the artifact which they asked for.
    """

    if lang not in LANGUAGES:
        raise UnknownLanguage(f"unknown report language {lang!r}; known: {', '.join(LANGUAGES)}")
    return {key: value[lang] for key, value in _CATALOG.items()}


def report_dirname(base: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """The directory one language's report is written to, beside the others."""

    if lang not in LANGUAGES:
        raise UnknownLanguage(f"unknown report language {lang!r}; known: {', '.join(LANGUAGES)}")
    return f"{base}{DIRECTORY_SUFFIX[lang]}"
