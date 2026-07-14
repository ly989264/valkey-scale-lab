# 00_OPERATING_CONTRACT.md — 不可违反的运行契约

## 1. 总目标

补强 `valkey-scale-lab` 的审计能力、harness 覆盖、量化指标采集和可视化展示，最终形成覆盖 fake 测试、小真实 Valkey 集群、大真实 Valkey 集群的全链路、多阶段验证体系。

覆盖范围必须逐步扩展到：

```text
cluster build → management ops → workload → observability → fault injection → failover → stability/soak → cleanup → quantitative analysis → visualization
```

## 2. harness-first 硬约束

每个 stage 必须遵守：

```text
previous harness PASS
        ↓
设计当前 stage harness
        ↓
运行当前 stage harness，确认它能捕获目标缺口
        ↓
实现功能
        ↓
运行 previous + current + integration validation
        ↓
review / anti-regression / verification PASS
        ↓
commit + push
```

严禁：

1. 为了让验证通过而删除、放宽、跳过、重命名或降级已有无问题 harness。
2. 把真实 Valkey 证据伪造成 fake 证据。
3. 用报告层补数据，绕过 artifact source-of-truth。
4. 缺失指标时编造数值。缺失必须显式编码为 `MISSING`、`SKIPPED_WITH_REASON` 或 `NO_BASELINE_YET`。
5. 未 push 就把 stage 标记为完成。
6. 在 stage 中忘记重新读取 loop 文档。

## 3. 允许修改 harness 的唯一条件

只有当 harness 本身存在明确 bug、过时契约或路径错误时才可修改。修改必须满足全部条件：

1. 写入 `artifacts/loop_engineering/stages/<STAGE_ID>/harness_change_request.md`。
2. 说明原 harness 的问题、影响范围、为什么不是规避失败。
3. review 子 agent 与 anti-regression guardian 都必须给出 `APPROVED`。
4. 修改后必须增加等价或更强覆盖，不能减少覆盖面。
5. `git diff` 中所有测试/脚本/CI/schema 变更必须在 stage report 中解释。

## 4. 多 agent 角色

每个 stage 至少需要以下 agent 输出。若 Codex App 有真实 subagent/task 能力，必须使用；若没有，主 agent 必须用隔离上下文模拟，并把每个角色输出独立落盘，不能跳过角色。

| agent | 职责 | 输出路径 |
|---|---|---|
| requirements_analyst | 分析 stage 目标、已有代码、缺口、验收标准 | `subagents/requirements_analyst.json` |
| harness_architect | 设计当前 stage harness、测试范围、schema、CI/CLI gate | `subagents/harness_architect.json` |
| risk_auditor | 识别跑偏风险、资源风险、真实/假证据边界 | `subagents/risk_auditor.json` |
| implementation_worker | 按设计实现，禁止自行放宽 harness | `subagents/implementation_worker.json` |
| review_agent | review 代码与设计一致性、边界条件、回归风险 | `subagents/review_agent.json` |
| validation_agent | 独立运行验证命令并判定结果 | `subagents/validation_agent.json` |
| anti_regression_guardian | 检查是否通过修改无问题 harness 规避问题 | `subagents/anti_regression_guardian.json` |

## 5. 强结构化交互

所有 agent 输出必须是 JSON，至少包含：

```json
{
  "stage_id": "L00_LOOP_ENGINE_HARNESS_BOOTSTRAP",
  "agent_role": "requirements_analyst",
  "context_files_read": [],
  "findings": [],
  "proposed_harness": [],
  "implementation_plan": [],
  "acceptance_criteria": [],
  "risks": [],
  "forbidden_shortcuts": [],
  "commands_to_run": [],
  "verdict": "APPROVED|CHANGES_REQUESTED|BLOCKED",
  "notes": ""
}
```

主 agent 必须读取这些 JSON，再决定是否进入下一步。

## 6. 文件记忆要求

每个 stage 必须创建：

```text
artifacts/loop_engineering/stages/<STAGE_ID>/
  stage_state.json
  read_context.md
  previous_harness_result.json
  stage_design.md
  current_harness_plan.json
  commands.jsonl
  subagents/*.json
  validation_result.json
  anti_regression_report.md
  stage_result.json
```

不得只把状态留在聊天上下文中。

## 7. commit 与 push 契约

stage 完成时必须执行：

```bash
git status --short
git add <changed files>
git commit -m "<STAGE_ID>: <short summary>"
git push origin HEAD:codex/valkey-scale-lab-loop
```

push 后记录：

```bash
git rev-parse HEAD
git log -1 --oneline
```

并写入 `stage_result.json`。
