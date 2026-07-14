# Milestone 1 性能瓶颈分析

## 结论

Milestone 1 已通过 50 和 200 节点真实准入，但“通过”不等于执行链路高效。
当前 200 节点完整运行耗时 3829.529 秒（63.83 分钟）。其中：

| 排名 | 区域 | 200 节点耗时 | 占总时长 | 50 节点耗时 | 占总时长 |
|---|---:|---:|---:|---:|---:|
| 1 | 管理矩阵 | 1839.174 s | 48.0% | 269.558 s | 27.6% |
| 2 | 资源遥测，两次共四个采集 pass | 1616.537 s | 42.2% | 402.896 s | 41.3% |
| 3 | 故障矩阵 | 225.111 s | 5.9% | 204.831 s | 21.0% |
| 4 | 清理 | 97.864 s | 2.6% | 62.537 s | 6.4% |
| 5 | 集群形成 | 42.218 s | 1.1% | 31.777 s | 3.3% |

管理矩阵中，两轮 rolling restart 共 1548.443 秒，占管理矩阵 84.2%，占整个
200 节点运行 40.4%。资源遥测和 rolling restart 合计占总时长 82.6%，应作为
第一轮优化对象。

本报告的 50/200 数据均来自最终 admitted evidence，而不是 fixture：

- `../loop_evidence/meta_runs/milestone1-v5/evidence/scale-50/`
- `../loop_evidence/meta_runs/milestone1-v6/evidence/scale-200/`

## 本轮优化实现状态

本轮代码实现遵循“先减少重复物理工作，不伪造更强证据”的边界：

- system metrics 在每个采集 pass 中把所有 nodehost 合并为一次
  `docker stats --no-stream`。200 节点当前两次调度、四个 pass 的 stats 调用数从
  800 次降为 4 次；批量命令失败时回退到逐容器 best-effort，并保留结构化
  `MISSING`，不让单次 stats timeout 中止整个 full flow。
- container CPU 以独立 `docker_stats/container_cpu_percent` 数值输出；不冒充
  `cpu_user_percent` 或 `cpu_system_percent`。cluster 指标使用 `cluster_info` 来源，
  `cluster_state` 用数值布尔值并保留 raw label。
- rolling restart 使用 live topology 计划、不同 shard/nodehost 的最多 8 路安全
  batch、目标节点加 representative probe、失败时 full diagnostic、最终 full probe。
  所有 primary 在重启前先完成受控 failover，所有重启 replica 必须证明 link up、
  sync 完成且 replication offset 追平；恢复 placement 前再次执行同一同步门禁。
  最终逐 logical node 比较 role、replica master 和 primary slots，漂移即 FAIL。
- cleanup nodehost 使用 Docker `--init` 回收孤儿进程；退出检查读取
  `/proc/<pid>/stat`，Z/X zombie 记为已退出，读取不确定性 fail closed。原先镜像内
  不存在 `pgrep` 却被误判 PASS 的检查已改为 `/proc` 扫描。仍保留 stop + rm 和
  最终 label residual scan，没有为了速度直接跳过安全清理。
- 三个 partition 场景仍各自执行独立物理事件，避免违反 provenance 合同；仅把
  reconnect 后四次重复全量 gate 合并为一次更强的 structured clean snapshot。

本轮没有把末尾连续采集的 system metrics 改名成 management/fault lifecycle
样本。它们不是在真实阶段边界采集；在增量 boundary sampler 实现前，H08 lifecycle
coverage 应继续诚实 BLOCKED，不能靠补标签“修绿”。以下收益在真实 A/B 完成前仍是
估算，不作为新的 admitted 结果。

## 端到端时间账

### 50 节点

总时长为 975.674 秒（16.26 分钟）。生命周期记录显示：

| 阶段 | 耗时 |
|---|---:|
| resource_preflight | 1.432 s |
| runtime_start | 1.473 s |
| cluster_form | 31.777 s |
| stabilize | 0.066 s |
| baseline_workload | 0.376 s |
| management_matrix | 269.558 s |
| fault_matrix | 204.831 s |
| recovery + validation | 0.116 s |
| 未命名 gap 1，实际为首轮 system metrics | 99.990 s |
| analysis + report | 0.002 s |
| 未命名 gap 2，实际为第二轮 system metrics | 302.906 s |
| cleanup | 62.537 s |

### 200 节点

总时长为 3829.529 秒（63.83 分钟）。生命周期记录显示：

| 阶段 | 耗时 |
|---|---:|
| resource_preflight | 1.470 s |
| runtime_start | 5.401 s |
| cluster_form | 42.218 s |
| stabilize | 0.267 s |
| baseline_workload | 0.347 s |
| management_matrix | 1839.174 s |
| fault_matrix | 225.111 s |
| recovery + validation | 0.520 s |
| 未命名 gap 1，实际为首轮 system metrics | 403.458 s |
| analysis + report | 0.006 s |
| 未命名 gap 2，实际为第二轮 system metrics | 1213.079 s |
| cleanup | 97.864 s |

两个未命名 gap 与采集规模严格吻合：首轮每个逻辑节点约 2.00 秒，第二轮采集
三个伪 lifecycle window，耗时约为首轮的三倍。

## 瓶颈 1：资源遥测

### 现象

200 节点遥测共耗时 1616.537 秒，约 26.94 分钟。最终文件包含 24000 行
system metrics，分成 `setup`、`cleanup`、`workload` 三组，每组 8000 行。

### 根因

1. P36 内部先调用一次 `write_system_metrics_artifacts(..., ["full_flow"])`。
2. 返回外层后，同一个运行又无条件调用一次采集器；此时它推导出
   `setup`、`cleanup`、`workload` 三个 window。
3. 采集器是 `window -> logical node` 的双重串行循环。
4. 每个逻辑节点都执行一次 `docker stats --no-stream`。
5. 200 个逻辑节点实际只位于 8 个 nodehost 容器内，同一容器的 stats 被每个
   pass 重复读取 25 次。

因此一次 200 节点 pass 约 403 秒，四个 pass 约 1616 秒。这不是 Valkey
采集成本，而是 Docker Desktop `stats --no-stream` 的采样等待乘以重复调用次数。

### 数据质量问题

这个瓶颈同时影响诊断可信度：

- 最终 `setup`、`cleanup`、`workload` 标签不是在对应阶段实时采样，而是在完整
  流程结束后连续采集的后置标签，不能用于阶段因果分析。
- `rss_bytes`、网络 I/O、PIDs 是 nodehost 容器级值，却被标成每个 logical node
  的值，导致一个容器的指标被重复 25 次。
- Docker stats 提供的 `cpu_percent` 没有进入输出；`cpu_user_percent` 和
  `cpu_system_percent` 被记录为 `MISSING`。当前证据无法判断 host CPU 是否饱和。
- 第二次采集重写 `system_metrics_timeseries.jsonl` 和 report；第一次 full-flow
  采集只残留在追加的总 metrics 文件中，报告口径不一致。

### 优化

P0：后续把采集改为真实 lifecycle boundary 增量 session，再合并当前两个调度入口；
不能删除 outer call 后只留下 `full_flow`，也不能复制一次样本冒充多个窗口。

P0（已实现第一步）：每个 physical pass 对所有 nodehost 使用一次批量 Docker
stats。nodehost 与 logical-node artifact 拆分、Valkey INFO 并发留到独立 schema
变更，避免本轮扩大证据面。

P0：在真实阶段边界采样，而不是运行结束后给样本补 window 标签。至少采集
setup 结束、management 前后、fault 前后、cleanup 前的真实时间点。

按旧证据中每次 stats 约 2 秒估算，800 次降至 4 次可把这部分从约 1616 秒降至
约 8 秒；Valkey INFO、文件写入和 fallback 会增加实际耗时。收益必须由新的 50
节点 real A/B 证明，不能用估算替代证据。

## 瓶颈 2：Rolling Restart

### 现象

| 操作 | 50 节点 | 200 节点 | 4 倍节点的放大倍数 |
|---|---:|---:|---:|
| rolling_restart_replica_first | 91.340 s | 690.193 s | 7.56x |
| rolling_restart_primary_safe | 55.201 s | 858.250 s | 15.55x |

两轮显著超线性。显式管理命令自身并不慢：200 节点两轮 restart 的 1000 条
已记录命令累计执行时间仅约 48.5 秒，但 wall time 为 1548.4 秒。主要时间消耗
在未写入 command log 的健康探测、角色探测、收敛等待和串行调度。

### 根因

1. `max_concurrent_restarts` 硬编码为 1，400 次 process restart 完全串行。
2. 每重启一个节点都调用 `_p17_wait_clean_cluster`。它依次验证 known nodes、
   slots、cluster state、role counts，并且每个条件都对全部节点做 final probe。
3. 随后 `_p30_wait_health_snapshot` 再调用 `_p17_cluster_health`，对全部节点逐个读取
   `CLUSTER INFO` 和 `CLUSTER NODES`。
4. 200 节点下，四项 clean gate 约产生 `4N` 个全量命令；
   `_p30_wait_health_snapshot` 在最佳情况下仍做两次各含 INFO/NODES 的全量扫描，
   再产生 `4N` 个命令。一次 restart 最低约 1600 个 node command，400 次
   restart 至少约 64 万个。primary-safe 每次 TAKEOVER 还多一轮 clean gate，
   两个 rolling operation 合计接近 80 万个未记录探测命令，复杂度接近 O(N^2)。
5. primary-safe 的计划覆盖全部 200 个节点。角色在 TAKEOVER 后动态翻转，最终
   记录了 200 次 TAKEOVER，即每个 shard 往返 failover 两次，而不是只处理初始
   的 100 个 primary。这解释了它比 replica-first 更慢。
6. 代码已经生成逐节点 `restart_rows` 和 `restart_events`，但 P36 没有把这些
   明细持久化到 admitted artifacts；现有结果只能从总 wall time 和源码推断
   每节点分布，无法直接找出 p95 慢节点。

### 优化

P0：先补齐探测 telemetry。记录每次 health gate 的 representative probe、full
probe、重试次数、命令数和 wall time，并持久化 restart rows。

P1：将四个全量健康条件合并为一次结构化 snapshot。先对每 AZ representative
做快探测，仅在不一致时全量扫描；每个 batch 后保留一次全量 gate。

P1（已实现）：按 live role、shard 和 nodehost 做最多 8 路有界并发；primary
在停进程前先降为已同步 replica，因此 batch 不并发移除 live-primary quorum。
每个 batch 探测所有 target 加每 AZ representative，异常时升级 full diagnostic，
操作末尾执行 full probe 和 placement comparison。

P1：重新审视 primary-safe 的目标语义。若合同要求“所有节点均重启”，保留节点
覆盖但避免同一 shard 无必要的往返 takeover；若合同只要求 primary-safe 路径，
则必须先更新明确合同和检查，不能通过少跑节点换取性能。

## 瓶颈 3：故障矩阵

200 节点 fault matrix 为 225.111 秒，规模从 50 到 200 只增加约 20 秒，说明它
主要受固定等待控制，而不是节点数量控制。

| 故障 | 50 节点 | 200 节点 | 原因 |
|---|---:|---:|---|
| split_brain_detection | 82.389 s | 88.599 s | 30 秒 node timeout 等待 + reconnect 后全量 clean gate |
| minority_majority | 79.419 s | 88.642 s | 同上 |
| network_partition | 39.922 s | 42.598 s | reconnect 后等待 gossip/failure 状态清除 |

三个场景执行的是同一种 nodehost network disconnect/connect 物理动作，其中两个
额外硬等待 `cluster-node-timeout + 1s`。它们合计占 200 节点 fault matrix 的
97.6%。

不能把三个 required scenario 合并成一次 capture：当前 evaluator 明确拒绝跨
scenario 复用 operation provenance。已实现的安全优化仅合并每次 reconnect 后的
known/state/roles/slots/handshake/fail/pfail recovery gate，物理故障与场景证据保持
独立。

## 瓶颈 4：Cleanup

200 节点 cleanup 为 97.864 秒：

- `cleanup_verify_process_exit_seconds`: 45.352 秒
- `cleanup_remove_containers_seconds`: 51.775 秒
- 其他步骤合计小于 1 秒

进程 TERM 本身仅 0.084 秒，但随后 `kill -0` 验证固定等满 45 秒，所有 nodehost
的 `verify_exit` 最终还是 `SKIPPED_WITH_REASON`。高度疑似 daemonized Valkey 子进程
退出后成为未被 `sleep infinity` PID 1 回收的 zombie；`kill -0` 仍把 zombie 当作
存活进程。

随后对 8 个 nodehost 执行 `docker stop -t 5` 再 `rm -f`。虽然调用端使用 8 路
并发，Docker Desktop 的 stop 路径表现接近串行，耗时约 52 秒。

P1（已实现）：验证读取 `/proc/<pid>/stat`，把 zombie 视为已退出，并让 nodehost
使用 Docker init 回收子进程。当前没有跳过 `docker stop`；真实 A/B 若仍证明 stop
很慢，才可另行设计“双重进程验证 PASS 后直接 rm，任何不确定性回退 stop+rm”。

## 瓶颈 5：集群形成

200 节点 cluster form 只占总时长 1.1%，不是全流程第一优先级，但其内部仍有
明显断层：

- 50 节点（25 primary）`valkey-cli --cluster create`: 2.119 秒
- 100 节点（50 primary）同阶段历史同链路: 106.050 秒
- 200 节点（100 primary）: 106.327 秒

50 primary 后出现接近固定 100 秒的平台，像是 `valkey-cli --cluster create`
内部 gossip/confirmation 等待，而不是 slot 命令线性成本。仓库已有 manual tree
meet + parallel slots 策略，但旧 A/B 只覆盖 50 节点，且旧结果下 manual 反而更慢。

P2：在 100 节点先做 default/manual 新 A/B，单独记录 meet、slot broadcast、
convergence 和 command output。只有 manual 在当前 nodehost runtime 上稳定获胜后，
才考虑改默认；200 节点 real run 不能自动触发。

## 工作负载结果的解释边界

基线 workload 请求 200 QPS，但实际只有：

- 50 节点: 14.02 QPS，p50 71.05 ms
- 200 节点: 14.72 QPS，p50 69.64 ms

两种规模几乎相同，说明这不是 Valkey 随节点数增长而退化。workload 每个 GET/SET
都新执行一次 `docker exec ... valkey-cli -c`，其进程创建和 Docker Desktop RPC
约占 60-80 ms。因此当前 QPS/latency 主要衡量 harness command launch，不应当作
Valkey 数据面吞吐结论。

此外，200 节点 `remove_primary_drained_or_safe_replaced` 的 event window 有 471 次
成功和 236 次失败，错误率 33.38%，其中 221 次 `CLUSTERDOWN`、15 次连接错误。
固定 workload seed 恰好可能是被停止的目标节点，且 client 没有多 seed retry。
该结果同时混合了“单入口失效”和“集群服务不可用”。

P0：性能 workload 应使用持久连接的 cluster client 或专用 benchmark 进程，避免
每 op 启动 `docker exec`。P0：availability workload 应显式区分 fixed-seed、
multi-seed failover、target-node availability 三个指标，保留原始错误分类。

## 优先级与验证标准

| 优先级 | 改动 | 200 节点测得可归因时间上限 | 首轮验证 |
|---|---|---:|---|
| P0 | 批量 nodehost stats（已实现） | 1616 s 区域 | hermetic + 50 real A/B |
| P0 | rolling/probe 明细与 target probe（已实现） | 先提升可解释性 | hermetic + 50 real |
| P1 | rolling safe batch + sync/placement gate（已实现） | 1548 s 区域 | 50 real，再 200 real |
| P1 | partition recovery 单 snapshot（已实现） | recovery probe 部分 | 50 real |
| P1 | init + zombie-aware cleanup（已实现） | 约 45-90 s | cleanup real gate |
| P1 | 真实 lifecycle boundary sampler（未实现） | 证据正确性优先 | 独立设计 + H08 gate |
| P2 | 100 节点 cluster-create A/B | 约 100 s | 100 real，非 200 自动 |

“可归因时间上限”是当前区域的测得 wall time，不是承诺收益。删除 telemetry 重复
调用减少是高置信收益；rolling、fault recovery、cleanup 和 cluster-create 的
wall-time 收益必须通过新的 real A/B 才能确认。

## 下一轮必须补的观测

1. 所有端到端 wall time 必须 100% 归属到命名 span，不再出现 403 秒和 1213 秒
   的未命名 gap。
2. 每个 rolling node/batch 记录 restart、role handoff、representative probe、full
   probe、retry/sleep、workload overlap 的独立耗时。
3. 所有隐式 probe 记录计数和累计 wall time，避免 command log 只显示 48 秒而
   1548 秒无法解释。
4. container metrics 与 logical-node metrics 分开建模，并在真实采样时间写入。
5. workload 区分 harness launch latency、client latency 和 server latency。
6. 每个优化保存 before/after product digest、节点数、健康、cleanup 和 timing，
   不用较小运行冒充 50/200 结果，也不静默下采样。

## 本轮验证结果

- 全量 hermetic regression：`731 passed, 2 skipped`，耗时 88.94 秒。
- 两轮独立 review 均检查了 correctness、quorum、frozen scale、ownership、artifact
  provenance 与复杂度；修复了 primary sync、placement、cleanup fail-open、probe
  scope 和 stats fallback 等问题后，无剩余代码级 blocker。
- Docker real smoke：两个真实临时容器一次批量 stats 在 1.403 秒内返回两份
  `PASS`，重复输入容器名只返回一个映射；测试容器随后删除并确认零残留。
- exact-50 real gate 未伪造执行。CLI 正确拒绝了缺少 controller ownership 的调用；
  当前 v6 controller 又因 `controller kernel changed after bootstrap` 拒绝调度。没有
  绕过 guard 或伪设 controller 环境变量。因此本报告中的新收益仍是代码复杂度分析
  和 smoke 结果，不是新的 exact-50/200 admitted A/B。
