# Codex App 启动 Prompt：Valkey 真实能力矩阵闭环

你正在本地仓库 `valkey-scale-lab` 中工作。当前本地代码必须与远端分支 `origin/codex/valkey-scale-lab-loop` 严格同步。你的任务不是重做已有 P00-P13 loop，而是在其基础上追加一个“Capability Matrix Loop”，补齐真实 Valkey 集群 30/50/100 节点上的能力矩阵，并为后续 200/500/1000 节点保留可扩展路径。

## 0. 第一原则

1. 不允许破坏、削弱、绕过既有 harness。
2. 每个 stage 开始前必须重新读取仓库根目录与本 prompt 包中的约束 MD，防止上下文遗忘。
3. 每个 stage 必须先验证之前所有 harness 仍通过，再设计当前 stage harness，再开发，再验证；验证失败必须修复实现，不能修改“没有问题的”harness 来规避失败。
4. 每个 stage 需要多 agent：主 agent 控制 loop；需求/设计子 agent 负责需求分析和 harness 设计；worker 子 agent 负责实现；review/guard 子 agent 负责验证 harness 完整性、回归和真实证据。
5. 每个 stage 的阶段、状态、执行结果、约束快照、子 agent 输入输出、验证命令、日志路径、artifact 路径，都必须落盘，不能只留在对话上下文里。
6. 每个 stage 只有在所有验证通过、fresh-context review PASS、stage result artifact PASS 后，才能 commit 并 push 当前分支。
7. 默认实跑规模只允许 30/50/100。200/500 可做资源预检、计划、dry-run 与可选 real profile；1000 默认只能 dry-run/resource-check，真实执行必须单独显式 opt-in。

## 1. 启动前必须读取的文件

先读取并摘要落盘到 `artifacts/capability_matrix_loop/session_context.md`：

```text
AGENTS.md
CODEX_START_HERE.md
README.md
codex/status/phase_state.json
docs/codex/00_MISSION.md
docs/codex/01_ARCHITECTURE_CONTRACT.md
docs/codex/02_PHASES.md
docs/codex/03_HARNESS_AND_GATES.md
docs/codex/04_AUDITOR.md
docs/codex/05_ARTIFACTS.md
docs/codex/06_FAULT_ISOLATION.md
docs/codex/07_SCALE_POLICY.md
codex/capability_loop_prompt/README.md
codex/capability_loop_prompt/00_REPOSITORY_CONTEXT.md
codex/capability_loop_prompt/01_LOOP_ENGINEERING_PROTOCOL.md
codex/capability_loop_prompt/02_MULTI_AGENT_PROTOCOL.md
codex/capability_loop_prompt/03_HARNESS_POLICY.md
codex/capability_loop_prompt/04_CAPABILITY_STAGE_PLAN.md
codex/capability_loop_prompt/05_METRIC_ARTIFACT_REPORT_CONTRACT.md
codex/capability_loop_prompt/06_SCALE_EXECUTION_POLICY.md
codex/capability_loop_prompt/07_TOKEN_EFFICIENCY_POLICY.md
```

如果本 prompt 包不在 `codex/capability_loop_prompt/`，先定位它，再读取同名文件；定位结果写入 `artifacts/capability_matrix_loop/prompt_pack_location.json`。

## 2. Git 同步与安全起点

执行并记录输出：

```bash
git status --short
git branch --show-current
git remote -v
git fetch origin codex/valkey-scale-lab-loop
git rev-parse HEAD
git rev-parse origin/codex/valkey-scale-lab-loop
```

如果当前分支不是 `codex/valkey-scale-lab-loop`，切换到该分支。若工作区已有未提交变更，除非这些变更正是本 prompt 包文件，否则不要覆盖；写入 `artifacts/capability_matrix_loop/BOOTSTRAP_BLOCKED.md` 并停止。若 HEAD 与远端不一致，必须先同步到远端 HEAD；不要在脏树上开始 loop。

## 3. 既有 harness 必须先通过

在任何新 stage 开发前，先运行“previous harness verification”。最少包括：

```bash
python3 scripts/codex_gate.py precheck --all
python3 scripts/safety_scan.py
python3 -m compileall -q scripts src tests
python3 - <<'PY'
import json, subprocess, pathlib, sys
state = json.loads(pathlib.Path('codex/status/phase_state.json').read_text())
failed = []
for phase in state.get('completed_phases', []):
    p = subprocess.run(['python3', 'scripts/codex_gate.py', 'postcheck', '--phase', phase], text=True)
    if p.returncode != 0:
        failed.append(phase)
if failed:
    print('FAILED_PREVIOUS_POSTCHECKS', failed)
    sys.exit(1)
PY
pytest -q
```

如果某命令失败，不允许开始当前 stage。必须判断是环境问题、已有 harness/artifact 缺失、还是当前 prompt 包放置造成的问题，并把诊断写入 `artifacts/capability_matrix_loop/previous_harness_failure.md`。只有修复后全部通过才能继续。

## 4. 主 loop 状态机

从 `codex/capability_matrix_loop/state.json` 读取下一个未完成 stage；不存在则创建。stage 列表和标准见 `04_CAPABILITY_STAGE_PLAN.md`。每个 stage 严格走如下状态：

```text
START
  -> CONTEXT_REFRESH
  -> PREVIOUS_HARNESS_VERIFICATION
  -> REQUIREMENTS_AND_HARNESS_DESIGN_AGENT
  -> HARNESS_IMPLEMENT_AND_FREEZE
  -> WORKER_IMPLEMENTATION_AGENT
  -> REGRESSION_GUARD_AGENT
  -> CURRENT_STAGE_VALIDATION
  -> FIX_LOOP_IF_NEEDED
  -> FRESH_CONTEXT_REVIEW_AGENT
  -> STAGE_RESULT_AND_NEXT_CONTEXT
  -> COMMIT_AND_PUSH
  -> NEXT_STAGE
```

每个状态变更必须追加到：

```text
artifacts/capability_matrix_loop/stage_journal.jsonl
artifacts/capability_matrix_loop/<STAGE_ID>/state_transitions.jsonl
```

## 5. 当前 stage 的 harness 顺序

每个 stage 都必须按顺序执行：

1. 重读必要 MD，并写 `context_refresh.md`。
2. 跑 previous harness。
3. 拉起需求/设计子 agent，输出 `agents/requirements_harness_design.md`。
4. 实现当前 stage harness，至少包含：manifest entry、schema、negative tests、positive tests、真实证据校验、artifact 校验、报告/图表输入校验。
5. 冻结当前 stage harness，写 `harness_freeze.json`，记录文件路径和 sha256。
6. 拉起 worker 子 agent，只允许在冻结 harness 约束下实现功能。
7. 拉起 regression guard 子 agent，检查 worker 是否改坏旧 harness 或当前冻结 harness。
8. 跑当前 stage validation。失败则修实现，除非 harness 本身确有缺陷；若要改 harness，必须写 `artifacts/capability_matrix_loop/<STAGE_ID>/harness_exception.md`，由 review 子 agent 确认为“增强而非削弱”，然后重新冻结。
9. Fresh-context review 子 agent 只能基于仓库状态、diff、gate logs、artifacts、checksums 作判断。
10. PASS 后生成 `stage_result.json`、`next_stage_context.md`。
11. commit 并 push。commit message 使用 `<STAGE_ID>: <short objective>`。

## 6. 最终能力闭环目标

必须在真实 Valkey 集群 30/50/100 节点上，补齐并量化这些能力：

```text
cluster management: remove node, add node, reshard, rebalance, rolling restart
fault injection: process stop/restart, owned nodehost kill/restart, network partition
failover: latency, unavailable window, promotion, slot coverage recovery
split-brain: minority/majority partition, dual-primary indicator, duration or observed absence
workload windows: before/during/after recovery QPS, latency, error
stability: 30/60 min bounded soak and progressive extension hooks
reporting: schema-first summary, quantitative analysis, deterministic visual outputs
```

每个能力都必须连接四层证据：

```text
真实操作执行 -> 指标观测 -> 量化分析 -> 可视化/报告
```

缺失数据只能使用 `MISSING`、`SKIPPED_WITH_REASON`、`UNSUPPORTED_WITH_EVIDENCE` 或 `ABSENT_OBSERVED`，并附证据。目标能力不能通过 fake、静态文件、空图、零填充或 narrative 自证通过。

## 7. 执行

现在开始执行 CML00，然后持续执行 CML01...CML13，直到全部 stage PASS 并 push，或遇到真实不可修复的环境/资源阻塞。阻塞时必须提交完整诊断 artifact；未 PASS 的 stage 不得 commit 为完成。
