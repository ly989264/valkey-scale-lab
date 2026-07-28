# 可扩展 Valkey 集群采集与验证系统设计

## 状态

- 状态：已确认设计
- 日期：2026-07-28
- 范围：Valkey 9.1.x，30 至 2000 节点，本地 Docker nodehost 与后续原生 ECS
- 本文定义采集、验证、判定和扩展契约，不是实现计划
- 实现入口：`valkey_scale_lab.observability`；runtime 只适配 endpoint、
  actuator 和本地资源采样

## 1. 背景与问题

旧资源采集器把以下工作放进同一个约 5 秒循环：

- 读取每个 Valkey 进程的 `/proc` 指标；
- 枚举进程 FD 和 socket；
- 对每个进程执行 `CLUSTER INFO`；
- 对每个进程执行 `CLUSTER NODES`；
- 对每个进程执行 `CLUSTER LINKS`。

200 节点实验中，一台 nodehost 最多承载约 25 个 Valkey 进程。一次资源样本
最长达到约 8.918 秒，采集循环累计落后约 85.547 秒。PR70 和 PR72 通过限制
并发和分批缓解了当前 200 节点问题，但没有改变采集工作的复杂度。

其中最主要的结构性问题是：`CLUSTER NODES` 从任意一个节点都会返回该节点
看到的完整集群拓扑。对 N 个节点全部执行一次，会产生约 N 份完整拓扑，即
O(N²) 的拓扑文本、解析和证据量。这不适合作为 1000 或 2000 节点的正常验证
路径。

本设计从正常路径中移除该模式，并把以下三类职责彻底分开：

1. 集群正确性与局部状态验证；
2. 真实数据路径验证；
3. OS 和进程资源采集。

## 2. 设计目标

### 2.1 必须满足

- 正常验证路径随节点数线性增长，不产生全节点 O(N²) 拓扑采集。
- 能验证每个节点的身份、角色、shard、slot 和主从关系。
- 能验证所有 16384 个 slot 完整覆盖、无重复、无遗漏。
- 能通过少量完整拓扑视图发现局部汇总无法发现的全局视图分歧。
- 能验证每个 primary 和 replica 的真实读取路径。
- 能测量自动故障转移期间客户端观察到的恢复时间。
- 采集器故障不能被误判为 Valkey 故障。
- Docker 到原生 ECS 的迁移不改变验证协议和判定语义。
- 正常实验最终只产生 `PASS`、`FAIL` 或 `ERROR`。

### 2.2 明确不做

- 不周期执行全节点 `CLUSTER NODES`。
- 不通过 `docker exec`、SSH 或 ECS Exec 周期查询 Valkey。
- 不把资源采集和 Valkey 协议查询绑定在同一个循环。
- 不为每个 slot 发送一个 Sentinel 请求。
- 不为每个 shard 构造一组 Load Lane 专用负载。
- 不为 V1 设计复杂的容量评分、多维 verdict 或动态负载工具切换。
- 不因为 QPS、epoch 或资源指标偏离参考值直接判 Valkey 失败。

## 3. 总体架构

正常验证由三层证据构成：

```text
第一层：全节点轻量局部状态
    +
第二层：少量观察节点的完整拓扑
    +
第三层：Sentinel Lane 与 Load Lane 数据路径
```

资源采集独立运行，不属于上述拓扑和数据路径验证循环。

### 3.1 一次完整集群验证

原来的“全节点完整检查”替换为：

1. 对所有节点执行第一层轻量验证；
2. 同一轮验证中，由固定少量观察节点执行 `CLUSTER SHARDS`；
3. 汇总并深入分析局部结果和完整拓扑结果；
4. 结合 Sentinel Lane 已有的数据路径证据。

`CLUSTER SHARDS` 没有独立的周期或阶段。它跟随场景中已有的“完整集群验证”
调用执行。60 秒滚动轻量巡检和稳定期边界快照不会自动触发
`CLUSTER SHARDS`。

`CLUSTER NODES` 只保留为正式窗口结束并冻结判定之后的 postmortem 诊断工具，
不能用于正常 PASS 路径，也不能把诊断结果倒灌修改已经形成的原始观察事实。

## 4. 第一层：全节点轻量验证

### 4.1 连接方式

- 使用 inventory 提供的 Valkey client endpoint；
- 直接使用 TCP/RESP；
- 不经过 Docker；
- 全局并发限制为 32 至 64；
- 大规模检查均匀滚动，避免一次性请求洪峰。

### 4.2 每节点命令

```text
PING
CLUSTER INFO
ROLE
CLUSTER MYID
CLUSTER MYSHARDID
CLUSTER MYSLOTS
```

除 `CLUSTER MYSLOTS` 的固定 2048 字节 bitmap 外，每个命令的返回大小不随
集群节点数增长。

### 4.3 汇总检查

汇总器必须验证：

- inventory endpoint 与 `node-id` 一致；
- 节点角色与计划一致；
- `shard-id` 和主从归属正确；
- 正常 shard 恰好有一个 primary；
- replica 指向同一 shard 的正确 primary；
- replica 复制连接状态符合当前实验阶段的预期；
- 同一 shard 的所有 slot bitmap 完全相同；
- 不同 primary shard 的 bitmap 两两不相交；
- 所有 primary bitmap 的并集恰好覆盖 `0..16383`；
- 每个 bitmap 的 population count 等于 `slot-count`；
- 实际角色、shard 和 slot 分配符合实验计划。

### 4.4 稳定期频率

120 秒无故障稳定期：

- 正式窗口开始前执行一次全节点轻量边界快照；
- 正式窗口中每 60 秒完成一轮均匀滚动轻量检查；
- 120 秒内完成两轮，最后一轮可以作为结束边界快照；
- 每个节点样本保存自己的时间戳；
- 边界快照不是分布式原子快照。

## 5. `CLUSTER MYSLOTS` 命令契约

命令：

```text
CLUSTER MYSLOTS
```

逻辑响应固定包含 7 个字段：

| 字段 | 语义 |
| --- | --- |
| `node-id` | 被查询节点的 node ID |
| `shard-id` | 被查询节点所属 shard ID |
| `role` | `primary` 或 `replica` |
| `slot-owner-id` | 提供 bitmap 的 slot owner ID |
| `slot-count` | bitmap 中置位的 slot 数 |
| `bitmap-encoding` | 固定为 `lsb0` |
| `slot-bitmap` | 固定 2048 字节的 16384-bit bitmap |

bitmap 映射：

```text
slot N -> bitmap[N >> 3] & (1 << (N & 7))
```

行为：

- 同时支持 RESP2 和 RESP3；
- primary 使用自身 slot bitmap，`slot-owner-id` 为自身 node ID；
- replica 使用本地 `replicaof` 节点的 bitmap；
- replica 与 primary 的复制链路断开时仍可返回本地已知 bitmap；
- 只有 replica 的 `replicaof == NULL` 时返回错误；
- 不返回文本 slot ranges；
- 不返回全局拓扑；
- V1 不包含 topology digest。

该命令的具体实现请参考PR#74.

## 6. 第二层：少量完整拓扑观察

### 6.1 观察节点

- 固定选择少量观察节点，当前设计为 3 至 5 个；
- 观察节点跨 AZ；
- 观察节点跨 ECS、nodehost 或 Docker 承载边界；
- 观察节点数量不随集群节点数增长。

### 6.2 命令与分析

每个观察节点执行：

```text
CLUSTER SHARDS
```

规范化后比较以下结构字段：

- shard ID；
- slot ranges；
- node ID；
- role；
- primary/replica 关系；
- endpoint 和 AZ；
- health 状态。

以下动态字段不用于结构一致性比较：

- replication offset；
- 时间戳；
- 返回顺序；
- 不影响结构的瞬时统计字段。

所有完整视图必须在以下方面一致：

- shard 数量；
- 每个 shard 的成员；
- 每个 shard 的 primary；
- replica 指向关系；
- slot 分配；
- slot 完整性和互斥性；
- 节点身份与计划匹配关系。

## 7. 第三层 A：Sentinel Lane

### 7.1 目的

Sentinel Lane 是小流量、可归因的数据路径探针，不是压力工具。它验证：

- 每个 primary 能读取自己 shard 的 canary；
- 每个 replica 能从本地副本读取同一 canary；
- 故障期间目标 shard 的客户端访问何时中断、何时恢复；
- control shard 是否同时正常。

### 7.2 key 选择

- 根据第一层的 slot bitmap，每个 shard 选择一个代表 slot；
- 使用 Valkey 固定的 CRC16/XMODEM 和 hash tag 预构造命中该 slot 的 key；
- 每个 shard 只创建一个静态 canary key；
- 不遍历 16384 个 slot；
- 一轮覆盖对每个 primary 和 replica 恰好执行一个 `GET`。

命名空间：

```text
vsl:sentinel:<run_scope>:{<slot-tag>}:<shard_id>
```

`run_scope` 至少隔离不同 run 和 arm。Sentinel 和 Load Lane 不得共享 prefix。

### 7.3 准备阶段

- 在正式窗口前向每个 shard 写入静态固定值；
- 确认该值已经出现在所属 replica；
- 正式窗口内 Sentinel 不再写入或更新 canary；
- 不使用 generation、动态 checksum 或每轮写入协议。

### 7.4 primary 与 replica 连接

primary：

- 使用指定节点的持久直连；
- 每轮直接执行 `GET`。

replica：

- 使用指定节点的持久直连；
- 连接准备阶段执行一次 `READONLY`；
- 正式窗口每轮只执行 `GET`；
- 新连接建立后，如果当前角色为 replica，重新执行一次 `READONLY`。

`READONLY` 只影响当前连接，不修改节点配置、角色或复制行为。

### 7.5 全节点 Sentinel 覆盖

- 每 60 秒完成一轮；
- N 个节点的请求均匀分布在 60 秒内；
- 每个节点每轮恰好一个 `GET`；
- 2000 节点约为 33 个 `GET/s`；
- 120 秒稳定期完成两轮。

### 7.6 故障窗口高频探针

故障目标 primary 所属 shard 作为 affected shard，并选择一个不受故障注入影响
的 control shard。

每 100ms：

```text
GET affected-shard-canary
GET control-shard-canary
```

固定开销约为 20 个 `GET/s`，与集群节点数无关。

该探针不执行：

- `ROLE`；
- `CLUSTER INFO`；
- `CLUSTER SHARDS`；
- 全节点查询；
- canary 写入。

客户端稳定恢复条件：

- affected 和 control 连续 10 轮成功；
- 每次返回预期固定值；
- 连续窗口约为 1 秒；
- 任一失败、超时、错误值或缺失都会重新开始连续计数；
- RTO 取最终稳定成功序列的第一次成功时间；
- 第十轮仅用于确认该成功不是瞬时结果。

故障转换期间的暂时访问失败属于被测过程的一部分。只有在场景规定的恢复
期限内无法形成上述稳定成功序列，检查任务才返回 `FAIL`。

### 7.7 重连策略

- actuator 明确杀掉的节点：记录连接断开，故障窗口内暂停重连；
- actuator 开始恢复该节点后：重新连接并重新确认身份和角色；
- 其他存活节点意外断线：独立后台重连，不阻塞其他节点；
- 存活 replica 被提升为 primary 时，原 TCP 连接继续使用；
- 所有断线、重连和恢复时间都保留在 Sentinel 证据中。

## 8. 第三层 B：Load Lane

### 8.1 固定工具与参数

V1 使用 `memtier_benchmark`：

```text
--cluster-mode
-c 1
-t 1
--pipeline=1
--ratio=1:9
--key-minimum=0
--key-maximum=99999
--data-size=32
--rate-limiting=<adapter-computed-per-connection-rate>
--key-prefix=vsl:load:<run_scope>:
```

其他固定规则：

- 全局目标约 10000 QPS；
- 该目标适用于所有准入规格，不按 200、1000、2000 节点分别写死；
- 不预填充；
- 不预热；
- GET miss 是允许且正常的结果；
- 不为每个 shard 准备独立 key 集合；
- 不动态增加 client、thread 或 pipeline；
- 正式窗口内不因故障动态补偿 QPS。

命名空间：

```text
vsl:load:<run_scope>:...
```

### 8.2 QPS 适配

memtier 的 rate limiting 是单连接限制。适配器根据观察到的 primary 数量计算
每连接 rate：

```text
per_connection_rate = round(10000 / observed_primary_count)
```

QPS 允许约 `±30%` 的参考偏差。QPS 偏差本身：

- 不判 `FAIL`；
- 不判 `ERROR`；
- 只记录 warning。

### 8.3 输出

- stdout/stderr 写入日志文件；
- 保存 JSON 结果；
- 保存 HDR latency 结果；
- 不记录每个业务请求；
- 不开启 debug 或每 client 详细日志。

### 8.4 preflight 与失败

正式实验前必须执行目标规格的 memtier preflight：

- 能建立所需 cluster 连接；
- 进程能保持运行；
- 能生成完整 JSON/HDR 输出；
- 没有 FD 或连接初始化错误。

preflight 失败：

- 返回 `ERROR`；
- 不开始正式实验；
- 不注入故障。

同一次实验中不自动切换负载工具。若资格验证证明 memtier 不适用于某个规模，
应通过独立实现变更替换 Load Lane，不能在运行中 fallback。

## 9. 自动故障转移观察

### 9.1 actuator

actuator 是故障动作的权威记录者，必须记录：

- target；
- action；
- action start；
- signal/request sent；
- action completed；
- result。

计划内 kill 是实验事件，不是 `FAIL`。actuator 无法实际执行故障动作属于工具
错误，返回 `ERROR`。

### 9.2 控制面采样

故障转换期间只查询 affected shard 的存活节点：

```text
ROLE
CLUSTER INFO
```

- 周期为 500ms；
- 使用持久连接；
- 不查询全节点；
- 不执行 `CLUSTER SHARDS`；
- 用于解释谁被提升、主从关系何时改变、节点本地何时看到
  `cluster_state:ok`；
- 精确客户端 RTO 仍由 100ms Sentinel 探针计算。

### 9.3 候选收敛

一次 affected shard 轮次是对该 shard 所有存活节点执行一轮
`ROLE + CLUSTER INFO`。

候选收敛要求连续两轮满足：

- 同一个明确 primary；
- 其他存活节点的 replica 指向关系一致；
- 所有被查询节点报告 `cluster_state:ok`；
- 两轮间隔 500ms；
- 中间没有失败、缺失或角色变化。

连续两轮成立后，执行一次正式完整集群验证。只有该完整验证通过，才正式判定
拓扑收敛。

### 9.4 failover 与 redundancy recovery

两个成功条件必须分开：

- failover 成功：所有 slot 恢复为恰好一个可服务 primary；
- redundancy recovery 成功：预期 replica 数量恢复，并完成复制追赶。

affected shard 在原 primary 被杀后暂时没有 replica，不等于 failover 失败；
但 redundancy recovery 尚未完成。

## 10. 120 秒无故障稳定性

正式窗口中同时运行：

- Load Lane；
- 60 秒一轮的全节点轻量检查；
- 60 秒一轮的全节点 Sentinel 覆盖；
- 5 秒一次的主机资源采样；
- 60 秒一轮的 Valkey 进程资源采样。

判定原则：

- 持续存在的 role、主从关系或 slot 变化由轻量检查发现；
- Sentinel 发现的数据路径错误由对应检查直接判 `FAIL`；
- 非计划 Valkey 进程退出判 `FAIL`；
- 只观察到 epoch 增加，而角色、slot、完整拓扑、Sentinel 和 Load 均正常：
  `PASS` 并增加 warning；
- 三层证据均未捕获的短暂变化不追溯判失败；
- 报告使用“未观察到异常”，不宣称“证明没有发生任何变化”。

## 11. OS 与进程资源采集

### 11.1 执行模型

每台 ECS/nodehost 启动一个长期存活的本地轻量采样器：

- 主机指标每 5 秒采一次；
- 进程指标每 60 秒滚动完成一轮；
- 本地结构化记录；
- 批量或通过已有长连接上传；
- 采集与上传解耦；
- 禁止每个样本创建 SSH、ECS Exec、`docker exec` 或新 shell 会话。

资源采集器不得执行任何 Valkey 命令。

### 11.2 主机字段

每 5 秒采集：

- CPU 累计计数：user、system、idle、iowait、steal；
- running/blocked process 数量；
- `MemAvailable` 和动态 swap 使用情况；
- 可用时的 cgroup CPU usage/throttling；
- 可用时的 cgroup memory current/max 和 OOM counter；
- 每个有效网络接口的 RX/TX bytes、packets、errors、drops；
- wall clock 和 monotonic timestamp。

实验开始记录一次静态信息：

- CPU 数量；
- `MemTotal`；
- `SwapTotal`；
- cgroup limits；
- 网络接口身份。

当前运行配置关闭 AOF，不采集磁盘 I/O。未来启用 AOF/RDB 时，磁盘指标作为
独立可选模块加入。

### 11.3 Valkey 进程字段

每 60 秒只采集：

- PID、state、start time；
- user/system CPU time；
- RSS；
- FD 总数。

FD 只统计目录条目，不逐个 `readlink`，不保存 socket 或 FD 目标明细。

### 11.4 分析用途

禁止孤儿指标。每个正式采集字段必须有自动分析消费者：

- CPU counters -> 利用率、p95、峰值和高负载窗口；
- cgroup CPU -> throttled 时间和比例；
- memory -> 最低可用量和最小 headroom；
- OOM -> 正式窗口增量和时间；
- network bytes/packets -> throughput、PPS、p95 和峰值；
- network errors/drops -> 增量及其与故障时间线的重合；
- process CPU/RSS/FD -> 单进程分布、全体汇总和最大节点；
- timestamps -> 与 actuator、Sentinel、Load、拓扑事件关联。

没有分析消费者的字段不能加入采集协议。

### 11.5 采集器自身开销

V1 记录本地采样器自身：

- CPU time；
- RSS；
- 单次采集耗时；
- 5 秒周期 overrun。

报告 p95、峰值和 overrun，但不设置主观 CPU/RSS 硬阈值：

- 开销偏高或偶发 overrun -> warning；
- 资源字段少量缺失 -> warning；
- 只有关键采集链路因此无法工作时，才由对应任务返回 `ERROR`；
- 资源指标本身不直接把 Valkey 实验判 `FAIL`。

如果 OOM 实际杀掉 Valkey，Valkey 进程检查返回 `FAIL`，资源证据用于说明根因。

## 12. 检查任务与最终判定

### 12.1 每个检查任务

每个必要检查任务只返回：

```text
OK
FAIL
ERROR
```

固定流程：

```text
采集器自身无法完成采集
    -> 重试一次
    -> 仍失败：ERROR

成功取得结果，但不符合当前阶段的固定预期
    -> FAIL

成功取得结果，且符合当前阶段预期
    -> OK
```

边界：

- 本地代码异常、任务未发起、解析器自身错误、必要证据无法写入：
  采集工作失败；
- Valkey 拒绝连接、超时、返回错误值或错误角色，而当前阶段要求它正常：
  成功观察到集群异常；
- 故障转换期暂时访问失败符合阶段过程，不逐样本判 FAIL；该任务最终根据是否
  在期限内恢复来返回 `OK` 或 `FAIL`；
- 计划内 actuator kill 是预期事件；
- OS 诊断样本少量缺失只 warning。

采集器只按预先定义的检查规则返回结果，不能增加新的最终状态，也不能把
warning 自行升级为 `FAIL`。

### 12.2 最终结果

```text
全部必要检查 OK
    -> PASS

存在至少一个有效 FAIL
    -> FAIL

没有 FAIL，但至少一个必要检查 ERROR
    -> ERROR

FAIL 和 ERROR 同时存在
    -> FAIL，并附带工具错误
```

不使用：

- `INVALID`；
- `INCONCLUSIVE`；
- `PASS_WITH_WARNINGS` 枚举；
- 独立 capacity verdict；
- 多维状态合并。

warning 作为结果的附加列表，不改变 `PASS`：

- epoch-only 变化；
- QPS 超出 `±30%` 参考范围；
- 资源高负载；
- 非关键资源样本缺失；
- 采集器开销偏高但没有影响关键证据。

## 13. 异常诊断升级

正式判定和诊断必须分开。

一旦检查任务通过有效观察确认不符合预期，该任务直接返回 `FAIL`。后续诊断
不能把该 FAIL 改回 OK。

诊断可以依次扩大：

1. 检查同 shard 的相关节点；
2. 扩大 `CLUSTER SHARDS` 观察节点；
3. 冻结正式窗口及其原始证据；
4. 正式窗口结束后执行 `CLUSTER NODES` 等 postmortem 命令。

采集器自身技术失败只重试一次。技术重试与 Valkey 语义失败不能混为一谈。

## 14. 规模复杂度

| 组件 | 正常复杂度 | 2000 节点量级 |
| --- | --- | --- |
| 全节点轻量检查 | O(N) | 每轮约 4MB bitmap 加小量元数据 |
| 少量 `CLUSTER SHARDS` | 固定观察数 × O(N) | 3 至 5 份完整视图 |
| Sentinel 全节点覆盖 | O(N) / 60s | 约 33 GET/s |
| Sentinel 故障高频探针 | O(1) | 约 20 GET/s |
| affected shard 控制面 | O(shard replicas) | 与全局节点数无关 |
| 主机资源 | O(hosts) | 分布式本地采样 |
| 进程资源 | O(N) / 60s | 每进程固定少量 `/proc` 读取 |
| Load Lane 请求 | 固定约 10000 QPS | 不随节点数提高目标 QPS |

memtier 和 Sentinel 的持久连接数量仍为 O(N)。这是 2000 节点 preflight 必须
实际验证的 FD 和连接资源风险，但不会通过提高 thread、client 或 pipeline
进行动态补偿。

正常路径不存在全节点 `CLUSTER NODES`，因此不再产生 O(N²) 拓扑证据。

## 15. Docker 到 ECS 的迁移边界

以下部分保持不变：

- RESP 命令；
- `CLUSTER MYSLOTS` 契约；
- 三层验证逻辑；
- Sentinel 和 Load Lane；
- 检查任务 `OK/FAIL/ERROR` 语义；
- 最终 `PASS/FAIL/ERROR` 语义；
- 资源字段和分析规则。

运行时适配器只负责替换：

- inventory 和 endpoint 发现；
- 进程启动、停止和恢复；
- actuator 实现；
- 本地资源采样器部署；
- 日志与证据上传。

不得把 Docker 特有命令带入验证层。自定义 Valkey 构建必须记录 source、
patch、image 和 binary digest；ECS worker 只运行经过 digest 验证的构建产物。

## 16. 验收标准

实现完成后至少证明：

1. 正常路径不周期执行全节点 `CLUSTER NODES`；
2. Valkey 协议检查不使用 `docker exec`；
3. 2000 节点计划中不存在 O(N²) 正常采集步骤；
4. `CLUSTER MYSLOTS` 的 7 字段、lsb0 和 replica 语义符合契约；
5. 全节点 bitmap 汇总能发现 slot 缺失、重复和 shard 不一致；
6. 少量 `CLUSTER SHARDS` 能发现完整视图分歧；
7. Sentinel 能逐节点覆盖 primary/replica；
8. 故障探针达到 100ms 周期并产生稳定恢复时间；
9. affected shard 控制面使用 500ms 周期和连续两轮收敛规则；
10. 主机 5 秒、进程 60 秒采样不会调用 Valkey；
11. memtier 使用固定参数、目标 QPS 和隔离 keyspace；
12. 采集器技术失败、Valkey 语义失败和计划内故障不会相互误判；
13. 所有检查只返回 `OK/FAIL/ERROR`；
14. 最终结果只返回 `PASS/FAIL/ERROR`；
15. Docker 和 ECS 后端满足同一验证与判定契约。

## 17. 非契约实现细节

以下内容可以由实现按现有代码模式选择，但不得改变本文语义：

- JSON 文件名和字段排列；
- 批量上传大小；
- 本地 spool 文件切分；
- RESP client 的内部类结构；
- worker 与 controller 的传输实现；
- 报告页面的展示布局。

任何实现选择都不能新增采集层级、改变命令契约、放宽 slot/角色检查，或增加
新的最终状态。
