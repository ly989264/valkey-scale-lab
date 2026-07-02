# 04 — Capability Stage Plan

## 总体完成定义

最终完成时，真实 Valkey 30/50/100 节点集群必须覆盖：

| 能力 | 必须从 SKIPPED/MISSING 变成什么 |
|---|---|
| 集群管理 | remove node、add node、reshard、rebalance、rolling restart 有真实执行结果、耗时、收敛、回滚/清理证据 |
| 故障注入 | process stop/restart、owned nodehost kill/restart、network partition 有真实 observed impact |
| 故障转移 | failover latency、unavailable window、promotion、slot coverage recovery 有 measured value 或明确 FAIL |
| split-brain | minority/majority partition、dual-primary indicator、duration；未发生时为 `ABSENT_OBSERVED`，不能是 `MISSING` |
| workload | before/during/after recovery 都有 QPS、latency、error 数据 |
| 稳定性 | 30/60 分钟 bounded soak 有稳定性 summary 与回归数据 |
| 报告 | schema-first artifacts 汇总到 CSV/Markdown/HTML/图表，图表只读 artifact 数据 |

## Stage 命名

使用 `CMLxx`，避免与既有 `Pxx` phase 冲突。

## CML00_CAPABILITY_LOOP_BOOTSTRAP

目标：创建 supplemental capability loop 的 manifest、state、artifact 目录、stage journal、基础 runner/CLI 入口、schema 骨架、harness freeze 机制。

必须实现：

1. `codex/capability_matrix_loop/stage_manifest.json`。
2. `codex/capability_matrix_loop/state.json`。
3. `codex/capability_matrix_loop/harness_lock.json`，只锁新 loop harness 文件。
4. `tools/capability_matrix_gate.py` 或等价 CLI。
5. capability matrix baseline：读取已有 artifacts/audit，标出当前 MISSING/SKIPPED/partial 能力。
6. previous harness verification 自动记录。

验证标准：

1. previous harness verification PASS。
2. 新 gate 对缺失 artifact 必须 FAIL。
3. 新 gate 对 fake real_valkey evidence 必须 FAIL。
4. 新 gate 对完整 CML00 bootstrap artifact PASS。
5. stage result PASS 后 commit/push。

## CML01_UNIFIED_OBSERVATION_AND_ARTIFACT_MODEL

目标：统一“真实操作/故障 -> 指标观测 -> 量化分析 -> 可视化”的数据模型，作为后续所有 stage 的共同基座。

必须实现：

1. `capability_matrix.json` schema。
2. `operation_event.jsonl` / `fault_event.jsonl` / `metrics_window.jsonl` / `workload_window.jsonl` schema。
3. before/during/after/recovery/all-run window model。
4. analysis summary：delta、error_rate、qps_drop_ratio、latency_delta、unavailable_ms、sample_coverage。
5. report index：CSV/Markdown/HTML/chart 路径与 source checksum。
6. missing data policy：`MISSING`、`ABSENT_OBSERVED`、`UNSUPPORTED_WITH_EVIDENCE` 有明确语义。

验证标准：

1. 空 metrics 不能 PASS。
2. 0 填充 missing 不能 PASS。
3. 图表没有 source artifact checksum 不能 PASS。
4. 旧 artifact 不能冒充当前 run。
5. 最小真实 Valkey data-path sample 产生完整 window artifact。

## CML02_CLUSTER_MANAGEMENT_REAL_OPS_30

目标：在真实 30 节点 Valkey 集群上补齐集群管理操作。

必须实现：

1. remove node 真执行：选择可恢复目标，迁移/清理 slots，确认 cluster convergence。
2. add node 真执行：新增 owned node，meet，分配角色，确认 cluster visibility。
3. reshard 真执行：迁移可控 slot set，记录 slot movement、duration、errors。
4. rebalance 真执行：使用 Valkey cluster rebalance 或项目内均衡策略，记录 before/after slot distribution。
5. rolling restart 真执行：逐节点重启，保证 slot coverage 与 data path 观测。
6. 每个操作都有 before/during/after workload window。

验证标准：

1. 30 节点真实 gate PASS。
2. 上述操作不能是 `SKIPPED_WITH_REASON`，除非 reviewer 判定 Valkey/环境确实不支持且有替代覆盖；默认不接受 skip。
3. 每个操作都有 timing、status、convergence、cluster state、slot coverage、workload impact。
4. cleanup PASS。
5. 生成 management report、analysis summary、visual report。

## CML03_PROCESS_AND_NODEHOST_FAULTS_30

目标：在真实 30 节点上补齐 process stop/restart 与 owned nodehost kill/restart。

定义：`nodehost kill` 在本地/容器环境中只能指 owned virtual host、owned host-agent、owned container group 或 sandbox process；不能 kill 物理主机、宿主网络或无关进程。

必须实现：

1. process stop fault：停止目标 Valkey process/container。
2. process restart clear：恢复原目标，确认身份、role、cluster view。
3. nodehost kill：停止 owned virtual host group / host agent / container group。
4. nodehost restart：恢复并采集 recovery metrics。
5. observed impact：cluster state、slot coverage、data path、workload error、latency、QPS。

验证标准：

1. 30 节点真实 fault gate PASS。
2. fault lifecycle apply/clear 都有 timestamp、target、scope、safety check。
3. during window 必须观察到影响或明确 `ABSENT_OBSERVED`，不能空白。
4. clear 后 recovery window 必须有 cluster/data-path evidence。
5. cleanup PASS，无 owned resource leftover。

## CML04_NETWORK_PARTITION_AND_AZ_FAULTS_30

目标：在真实 30 节点上补齐 network partition、minority/majority partition、虚拟 AZ 故障。

必须实现：

1. container-scoped partition 或 sandbox proxy partition。
2. minority partition scenario。
3. majority partition scenario。
4. AZ-level targeting，基于 virtual AZ labels。
5. 观测 partition 两侧：cluster nodes、role claim、slot coverage、write/read success、workload impact。

验证标准：

1. 禁止 host-level firewall/route/interface mutation。
2. 30 节点真实 network fault gate PASS。
3. partition window 至少有多次 samples。
4. clear 后 topology 恢复与 data path 恢复。
5. metrics/report/chart 都能定位 partition 时间窗。

## CML05_FAILOVER_LATENCY_AND_RECOVERY_30

目标：量化 failover latency、unavailable window、promotion、slot coverage recovery。

必须实现：

1. primary stop scenario。
2. primary partition scenario。
3. promotion detection：原 replica 变 primary 的时间点。
4. slot coverage recovery：coverage 从 fail 到 ok 的时间点。
5. unavailable window：SET/GET 或 cluster write/read 不可用的开始/结束。
6. failover report：duration、confidence、sample coverage、raw event links。

验证标准：

1. 30 节点真实 failover gate PASS。
2. promotion 缺失时 stage FAIL，不得写 MISSING 过关。
3. latency/unavailable/slot recovery 必须有数值和 evidence path。
4. report 中每个结论能回链到 raw samples。

## CML06_SPLIT_BRAIN_INDICATORS_30

目标：把 split-brain 从 MISSING 变成可审计指标。

必须实现：

1. dual-primary indicator：同一 slot/shard 在同一观测窗口中出现冲突 primary claim 的布尔指标。
2. split-brain duration：冲突存在时的持续时间；未观察到冲突时为 0 且状态 `ABSENT_OBSERVED`。
3. minority/majority write acceptance：两侧 read/write success/error。
4. raw `CLUSTER NODES` samples 归档。
5. 证据与推断分离：evidence、inference、missing 三类字段。

验证标准：

1. 不允许 split-brain 字段是 `MISSING`，除非 sample coverage 不足且 stage 失败。
2. 如果 Valkey 正确避免 split-brain，结果应为 `ABSENT_OBSERVED` + duration 0 + 足够 sample coverage。
3. dual-primary=true 时必须给出冲突 samples 和 duration。
4. 30 节点真实 partition scenario PASS。

## CML07_WORKLOAD_FAULT_WINDOWS_30

目标：所有管理/故障/恢复场景都有 before/during/after QPS、latency、error。

必须实现：

1. workload window scheduler：before、during、after recovery 对齐事件时间轴。
2. QPS：requested、achieved、drop ratio。
3. latency：p50/p95/p99；缺 percentile 时 FAIL 或 MISSING_WITH_REASON 且不能作为目标能力 PASS。
4. error 分类：timeout、connection、MOVED/ASK retry、clusterdown、write rejected、read stale/failed。
5. 汇总到 capability matrix。

验证标准：

1. P05 fault window 跳过状态必须被替换为真实 windows。
2. 每个目标 scenario 至少有三段窗口数据。
3. before/during/after 的 run_id、scenario_id、fault_id/operation_id 能 join。
4. 图表展示时间线、QPS、latency、error rate。

## CML08_BOUNDED_SOAK_30_60_MINUTES

目标：补齐至少 30/60 分钟 bounded soak，先在 30 节点上稳定跑通，再为 50/100 closure 复用。

必须实现：

1. 30-minute soak profile。
2. 60-minute soak profile。
3. steady workload + periodic metrics + periodic cluster state probe。
4. leak/restart/error summary。
5. bounded timeout、cleanup、resource preflight。
6. progressive extension hooks：2h/4h/overnight 只作为 opt-in profile。

验证标准：

1. 30 分钟真实 soak artifact PASS。
2. 60 分钟真实 soak artifact PASS，或者如果本地资源/时间 policy 明确阻塞，则 stage 不能 PASS，只能写 blocked diagnosis。
3. soak 期间 metrics sample gap、error burst、restart count 有量化 summary。
4. cleanup PASS。

## CML09_REPORTING_AND_CAPABILITY_MATRIX_CLOSE_30

目标：把 30 节点所有场景收敛到能力矩阵与报告。

必须实现：

1. capability matrix：每行 capability/scenario/scale/status/evidence/metrics/report。
2. CSV export。
3. Markdown/HTML report。
4. deterministic charts：timeline、QPS、latency、error、failover durations、slot coverage、split-brain indicator、soak stability。
5. artifact source checksums。

验证标准：

1. 30 节点目标能力无 `MISSING`。
2. 不允许只有 narrative，没有 raw evidence。
3. report index 校验所有 chart/source path 和 checksum。
4. reviewer 可以从报告回链到 raw artifacts。

## CML10_SCALE_REPLAY_50

目标：将 30 节点已补齐能力重放到真实 50 节点。

必须实现：

1. resource preflight for 50。
2. 50 节点 capability suite：管理操作、process fault、network partition、failover、split-brain indicator、workload windows、bounded soak profile。
3. 50 vs 30 comparison：duration、QPS impact、error rate、recovery time、resource usage。

验证标准：

1. 50 节点真实 gate PASS。
2. 目标能力无 `MISSING`。
3. resource/cleanup PASS。
4. 30/50 comparison report PASS。

## CML11_SCALE_REPLAY_100

目标：将能力矩阵闭环提升到默认上限 100 节点。

必须实现：

1. resource preflight for 100。
2. 100 节点 capability suite。
3. 100 vs 50 vs 30 comparison。
4. scale regression budget：关键 duration/error/QPS drop 不得无解释失控。

验证标准：

1. 100 节点真实 gate PASS。
2. 默认路径不超过 100 节点。
3. 所有目标能力在 100 节点有 evidence。
4. cleanup PASS。

## CML12_FUTURE_SCALE_200_500_1000_SUPPORT

目标：保证 200/500/1000 后续可扩展，但不默认实跑。

必须实现：

1. 200/500 planner + resource preflight + dry-run stage profile。
2. 1000 dry-run/resource-check，沿用既有 opt-in policy。
3. capability suite 的 scale-rung 参数化，不写死 30/50/100。
4. multi-host placement hooks。
5. report 能展示 future dry-run estimated capacity 与 blockers。

验证标准：

1. 200/500 dry-run 不启动真实节点。
2. 1000 dry-run 必须要求显式 env/config opt-in。
3. 默认 gate 不执行 200/500/1000 real cluster。
4. 参数化测试证明新增 rung 不需要复制粘贴核心逻辑。

## CML13_FINAL_FULL_CHAIN_AUDIT_AND_PUSH

目标：最终审计全链路能力闭环，确认补齐目标完成。

必须实现：

1. 全 previous harness verification。
2. CML00-CML12 stage result 全部 PASS。
3. 30/50/100 capability matrix 无目标能力 MISSING/SKIPPED。
4. final report：汇总每个能力、规模、证据、指标、分析、图表、cleanup。
5. final fresh-context audit。

验证标准：

1. reviewer 能从 final report 回链到 raw evidence。
2. fake/static/old artifact 不能通过 final audit。
3. 1000 仍为 opt-in dry-run，不被误执行。
4. commit/push 完成。
