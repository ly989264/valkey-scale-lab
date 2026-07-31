# Valkey Scale Lab first-principles refactor

## Goal

Make the current Valkey experiment paths truthful, direct, maintainable,
and easier to extend through ordinary code changes.

## Non-goals

- no native ECS implementation;
- no 1000/2000-node admission run;
- no MYSLOTS redesign;
- no new controller or framework;
- no loop_evidence migration;
- no global schema rewrite;
- no unrelated performance optimization.

## Status

| Stage | Status | Base SHA | Commit SHA | Worker attempts |
|---|---|---|---|---:|
| S1 Measurement truth | PENDING | | | 0 |
| S2 M2 parameter flow | PENDING | | | 0 |
| S3 Cluster extraction | PENDING | | | 0 |
| S4 Fault extraction | PENDING | | | 0 |
| S5 Management extraction | PENDING | | | 0 |
| S6 Lifecycle and artifacts | PENDING | | | 0 |
| S7 Final deletion and regression | PENDING | | | 0 |

Allowed status values:

- PENDING
- ACTIVE
- PASS
- BLOCKED

## S1 Measurement truth

Stage 1：修正实验事实

目标：先保证项目报告的数据是真的。

必须完成：

1. 分开记录：

   * fault sent；
   * process gone；
   * first PFAIL；
   * quorum FAIL；
   * promotion；
   * cluster OK；
   * read recovery；
   * write recovery；
   * redundancy recovery。
2. `promotion_latency_ms` 和 `cluster_recovery_latency_ms` 使用不同端点。
3. write RTO 必须来自实际写请求；暂时不测写时就不输出 write RTO。
4. 删除四个 CLI 请求伪装成 200 QPS workload 的旧路径。
5. 删除故障 event window 无条件 PASS。
6. 删除错误的 `CLUSTER FAILOVER TAKEOVER` 文案。
7. 将只影响客户端 proxy 的场景改名为：

   * `client_path_delay`
   * `client_path_loss`
   * `client_path_flap`

禁止：

* 调整 `cluster-node-timeout`；
* 修改建群策略；
* 拆大文件；
* 增加新的观测框架。

完成条件：

```bash
cd project
python3 -m pytest -q \
  tests/unit/test_scalable_observability.py \
  tests/integration/test_docker_runtime_contract.py

./gate test gate.m2.contracts
./gate suite repository.all
```

## S2 M2 parameter flow

Stage 2：消除 M2 参数的重复权威

目标：候选参数只按一条路径传递。

唯一参数流：

```text
milestone.json
      ↓
catalog invocation parameters
      ↓
m2_performance_capture
      ↓
trial/report 中的实际 treatment
      ↓
m2_performance_gate 验证 treatment 一致性和结果
```

必须完成：

1. `milestone.json` 继续选择当前 candidate。
2. `catalog.json` 只定义参数类型，不复制业务规则。
3. 删除 Controller 中固定 candidate tuple。
4. 删除 Capture 中：

   * `DIRECT_FORMATION_CANDIDATE`
   * 固定 p16 限制
   * 固定 20000ms candidate 限制。
5. 删除 Gate 中对具体 candidate 名称的硬编码。
6. Gate 只检查：

   * 请求值与实际运行值一致；
   * baseline/candidate 配对正确；
     -预算是否通过。
7. 删除只为同步多层定义而存在的 `v3-direct-p16` 版本分支。
8. 增加一个测试：传入另一个合法参数时，无需修改 Capture/Gate/Controller 源码。

禁止：

* 新增 `ExperimentSpec` 框架；
* 新增候选注册表；
* 新增插件系统；
* 新增候选发现状态机。

完成条件：

```bash
cd project
./gate test gate.m2.contracts
./gate suite repository.all
```

## S3 Cluster extraction

Stage 3：拆出 cluster formation

目标：机械移动建群代码，不改变行为。

移动到：

```text
runtime/cluster_operations.py
```

范围：

* cluster create strategy；
* tree MEET；
* `ADDSLOTS` / `ADDSLOTSRANGE`；
* replica MEET；
* `CLUSTER REPLICATE`；
* cluster known/slots/role/convergence waits；
* 相关并发常量。

`docker_runtime.py` 只调用这些函数。

禁止：

* 修改建群顺序；
* 修改并发度；
* 增加 ClusterBuilder、StrategyFactory 等抽象；
* 同时做性能优化。

完成条件：

```bash
cd project
python3 -m pytest -q tests/integration/test_docker_runtime_contract.py
./gate suite repository.all
./gate test real.local.full-flow \
  --param nodes=30 \
  --param config=templates/configs/scale_30.yaml
```

## S4 Fault extraction

Stage 4：拆出 fault/failover

目标：把故障动作和恢复流程从 Docker 大文件中移出。

移动到：

```text
runtime/fault_operations.py
```

范围：

* primary `SIGKILL`；
* process pause/resume；
* nodehost pause/unpause；
* network disconnect/reconnect；
* client-path proxy；
* affected shard observer；
* 原 primary 恢复为 replica；
* redundancy recovery。

禁止：

* 新增 Fault DSL；
* 新增 fault plugin；
* 增加理论故障种类；
* 改变 Stage 1 已固定的指标语义。

完成条件：

```bash
cd project
python3 -m pytest -q \
  tests/unit/test_scalable_observability.py \
  tests/integration/test_docker_runtime_contract.py

./gate suite repository.all
```

## S5 Management extraction

Stage 5：拆出 management operations

目标：把管理操作从 `docker_runtime.py` 移出。

移动到：

```text
runtime/management_operations.py
```

范围：

* add/remove node；
* add/remove replica；
* reshard；
* rebalance；
* rolling restart。

这一阶段保持现有算法不变。现有逐 slot、逐 primary 的迁槽算法可以在重构完成后单独优化，避免结构重构和性能优化混在一个 diff 中。

完成条件：

```bash
cd project
python3 -m pytest -q tests/integration/test_docker_runtime_contract.py
./gate suite repository.all
./gate test real.local.full-flow \
  --param nodes=30 \
  --param config=templates/configs/scale_30.yaml
```

## S6 Lifecycle and artifacts

Stage 6：简化 lifecycle 和 Artifact

目标：运行事实与离线报告分开。

新顺序：

```text
实验执行
   ↓
冻结原始结果
   ↓
立即 cleanup
   ↓
验证 cleanup
   ↓
离线 analysis
   ↓
离线 report
```

当前 cleanup 位于 artifact validation、analysis 和 report 之后。

必须完成：

1. Cleanup 在运行资源不再需要时立即执行。
2. `analysis_summary.json` 和 `report_index.json` 不再属于 required raw artifact。
3. 生命周期步骤只能来自真实执行 span。
4. 删除事后合成的：

   * `create_cluster PASS`
   * `meet_nodes PASS`
   * `assign_slots PASS`
   * `add_replica PASS`
5. 保留以下原始数据：

   * run/state；
   * command log；
   * events；
   * metrics；
   * scenario-specific raw result；
   * cleanup result。
6. 分析和报告可以失败，但不能把已经完成的 Valkey 实验改写成“没有执行”。

当前代码确实存在根据文件引用直接生成多个 `status: PASS` 生命周期步骤的逻辑。

禁止：

* 设计新的统一 Artifact Schema；
* 全局迁移所有历史 Artifact；
* 改写 `loop_evidence`；
* 一次性消灭项目所有 `"MISSING"` 字符串。

完成条件：

```bash
cd project
./gate suite repository.all
./gate test real.local.full-flow \
  --param nodes=30 \
  --param config=templates/configs/scale_30.yaml
```

## S7 Final deletion and regression

Stage 7：删除残留并做最终回归

目标：只删除已经没有调用者的旧路径。

必须完成：

1. 删除已迁移函数的重复实现。
2. 删除临时 re-export，仅保留真实公共入口。
3. 删除旧伪 workload。
4. 删除旧 M2 candidate/version 分支。
5. 删除死测试和死 fixture。
6. `docker_runtime.py` 只剩运行时入口和 Docker 生命周期。
7. 不进行新的架构调整。

最终验证：

```bash
cd project

python3 -m compileall -q src scripts
./gate suite repository.all
./gate test gate.m2.contracts

./scripts/build_valkey_image.sh

./gate test real.local.full-flow \
  --param nodes=50 \
  --param config=templates/configs/scale_50.yaml

./gate test real.local.full-flow \
  --param nodes=200 \
  --param config=templates/configs/scale_200.yaml
```
