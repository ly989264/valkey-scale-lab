# 06 — Scale Execution Policy

## 1. 默认规模

本 loop 的真实执行目标：

```text
30 nodes -> first capability completion
50 nodes -> scale replay
100 nodes -> default ceiling closure
```

不要默认执行 200/500/1000 real cluster。

## 2. Profile 命名

建议所有 capability suite 支持：

```text
profile=fast-unit       # no real cluster, schema/harness/unit only
profile=real-30         # real 30 nodes
profile=real-50         # real 50 nodes
profile=real-100        # real 100 nodes
profile=dryrun-200      # planner/resource only
profile=dryrun-500      # planner/resource only
profile=dryrun-1000     # opt-in dry-run/resource only
profile=real-200        # disabled by default; future explicit opt-in
profile=real-500        # disabled by default; future explicit opt-in
profile=real-1000       # disabled by default; separate explicit command only
```

## 3. Resource preflight

每个 real profile 必须先检查：

```text
Docker availability
Valkey image/version
CPU count
available memory
free disk
port range availability
leftover owned containers/processes
container naming collision
expected node count
configured per-node memory limit
soak duration timeout
```

preflight 失败时，不能改成 PASS。写 `resource_preflight_report.json`，stage 状态为 FAIL/BLOCKED。

## 4. 30/50/100 真实 gate 原则

每个 scale closure 都必须重新运行当前规模的真实 gate。可以复用代码，不可复用旧规模 artifact 作为当前规模 evidence。

每个 evidence artifact 至少包含：

```json
{
  "real_valkey": true,
  "valkey_version_prefix_required": "9.1.",
  "scale_nodes_expected": 50,
  "scale_nodes_observed": 50,
  "probe_result": "PASS",
  "cluster_state_observed": "ok",
  "slot_coverage": "PASS",
  "data_path_result": "PASS"
}
```

## 5. 200/500/1000 支持方式

CML12 的目标是参数化能力，不是默认实跑大规模：

1. capability suite 不写死 30/50/100。
2. planner 能生成 200/500/1000 rung。
3. preflight 能估算资源。
4. report 能展示 dry-run blockers。
5. 1000 必须继承既有 opt-in 环境变量：

```bash
export VSLAB_ALLOW_1000_DRYRUN=I_UNDERSTAND_THIS_IS_NOT_A_DEFAULT_GATE
```

真实 1000 执行不属于本 automatic loop。

## 6. Soak 时长

CML08 要求 30/60 分钟 bounded soak。为了 token 和诊断效率：

1. 先用 fast-unit/short-real smoke 验证 harness 与 cleanup。
2. 再运行 30-minute real soak。
3. 30-minute PASS 后运行 60-minute real soak。
4. 不允许用 60 秒 smoke 冒充 30/60 分钟 soak。
5. 如果机器资源不足，写 BLOCKED，不要 PASS。
