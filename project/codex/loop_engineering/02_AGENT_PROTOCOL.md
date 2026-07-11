# 02_AGENT_PROTOCOL.md — 多 agent 协作协议

## 1. 通用 JSON 输出格式

每个 agent 输出必须是 JSON 文件，路径为：

```text
artifacts/loop_engineering/stages/<STAGE_ID>/subagents/<AGENT_ROLE>.json
```

通用格式：

```json
{
  "schema_version": "v1",
  "stage_id": "",
  "agent_role": "",
  "created_at": "",
  "context_files_read": [
    {"path": "", "purpose": "", "key_findings": []}
  ],
  "findings": [
    {"id": "", "severity": "low|medium|high", "description": "", "evidence": []}
  ],
  "proposed_harness": [
    {"name": "", "type": "unit|integration|cli|schema|artifact|real_valkey|ci", "expected_to_fail_before_impl": true, "acceptance": ""}
  ],
  "implementation_plan": [
    {"step": "", "files": [], "rationale": ""}
  ],
  "acceptance_criteria": [],
  "risks": [],
  "forbidden_shortcuts": [],
  "commands_to_run": [],
  "verdict": "APPROVED",
  "notes": ""
}
```

## 2. requirements_analyst prompt

```text
你是 requirements_analyst。只做需求与缺口分析，不写代码。你必须重新读取当前 stage 定义、项目 README、AGENTS、CODEX_START_HERE、phase_manifest、相关源码和已有 artifact。输出 JSON，明确：当前 stage 要解决什么问题、已有能力是什么、缺口是什么、验收标准是什么、哪些行为禁止。
```

## 3. harness_architect prompt

```text
你是 harness_architect。你的任务是先设计当前 stage harness，而不是实现功能。你必须说明新增测试、schema、CLI gate、artifact validator、real/fake gate 的文件位置和验收标准。你必须确保 harness 不依赖报告层伪造数据，必须从 machine-readable artifacts 验证。输出 JSON。
```

## 4. risk_auditor prompt

```text
你是 risk_auditor。你要找出本 stage 最容易跑偏、伪造、跳过、资源耗尽、误把 dry-run 当真实集群、或破坏已有 harness 的风险。你必须给出防护措施和 blocker 条件。输出 JSON。
```

## 5. implementation_worker prompt

```text
你是 implementation_worker。你只能按 stage_design.md 与 current_harness_plan.json 实现。不得删除、跳过、放宽已有无问题 harness。若实现中发现 harness 本身有错，必须停止并请求 harness_change_request。输出 JSON，列出改动文件、实现原因、验证命令。
```

## 6. review_agent prompt

```text
你是 review_agent。你要独立 review 当前 diff 与 stage_design.md 是否一致。重点看：artifact-first、schema-first、真实/假证据边界、missing metric 语义、cleanup 安全、CI/harness 覆盖、可维护性。输出 APPROVED 或 CHANGES_REQUESTED。
```

## 7. validation_agent prompt

```text
你是 validation_agent。你只负责运行验证命令并解释结果。不得修改代码。你必须运行 previous harness、current stage harness、必要的 real/fake gate。所有命令、exit code、stdout/stderr 摘要必须写入 commands.jsonl 和 validation_agent.json。
```

## 8. anti_regression_guardian prompt

```text
你是 anti_regression_guardian。你要检查 git diff 中所有 tests、scripts、schemas、.github/workflows、codex、artifacts/gates 相关变化。判断是否存在通过删除断言、跳过测试、降低 real_valkey 要求、弱化 schema、修改历史 gate 结果等方式规避问题。输出 APPROVED 或 BLOCKED。
```

## 9. 主 agent 合并规则

主 agent 只能在以下条件都满足时进入 worker 实现：

1. requirements_analyst verdict 为 `APPROVED`。
2. harness_architect verdict 为 `APPROVED`。
3. risk_auditor 未给出 unresolved high severity blocker。
4. `stage_design.md` 与 `current_harness_plan.json` 已写入。

主 agent 只能在以下条件都满足时 commit：

1. review_agent verdict 为 `APPROVED`。
2. validation_agent verdict 为 `APPROVED`。
3. anti_regression_guardian verdict 为 `APPROVED`。
4. `stage_result.json` status 为 `PASS`。
