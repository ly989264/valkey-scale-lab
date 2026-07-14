# 02 — Multi-Agent Protocol

## 1. 角色分工

主 agent 只负责控制 loop、维护状态、调度子 agent、执行命令、整合结果。主 agent 不得把 worker 的自评当成 PASS。

子 agent：

| 角色 | 解决什么问题 | 主要输出 |
|---|---|---|
| Requirements + Harness Architect | 把当前 stage 目标转成可验证 harness | harness plan、schema、negative/positive tests、真实证据标准 |
| Worker | 在冻结 harness 下实现功能 | 代码、artifact writer、CLI、runtime changes、测试 |
| Regression Guard | 防止改坏旧 harness 或冻结 harness | diff 审查、locked file 检查、harness freeze 对比 |
| Fresh-Context Reviewer | 独立审计当前 stage 是否可 PASS | AUDIT.md、audit_decision.json |
| Scale/Cost Guard | 对 30/50/100 与未来 200/500/1000 做资源/时间约束审查 | scale profile、preflight、timeout 建议 |

如果 Codex App 不支持真正的子 agent，就用同一会话模拟隔离 agent：每个模拟 agent 必须只读取主 agent 给出的 input packet 和指定文件，输出必须落盘到 `artifacts/capability_matrix_loop/<STAGE_ID>/agents/`，主 agent 再继续。

## 2. 子 agent 输入包

每次启动子 agent 前，主 agent 写入：

```json
{
  "schema_version": "v1",
  "stage_id": "CML04_NETWORK_PARTITION_AND_AZ_FAULTS",
  "role": "requirements_harness_architect",
  "input_context_paths": [
    "artifacts/capability_matrix_loop/CML04_NETWORK_PARTITION_AND_AZ_FAULTS/context_refresh.md",
    "codex/capability_loop_prompt/04_CAPABILITY_STAGE_PLAN.md"
  ],
  "must_not_modify": [
    "codex/phase_manifest.json",
    "codex/gate_lock.json",
    "scripts/codex_gate.py",
    "docs/codex/**/*",
    "frozen harness files from harness_freeze.json"
  ],
  "required_outputs": [
    "agents/requirements_harness_design.response.md"
  ],
  "question": "Design the harness for this stage."
}
```

## 3. 子 agent 输出格式

每个子 agent 必须用如下结构回复，并落盘：

```markdown
# Agent Response

## Identity
- role: requirements_harness_architect
- stage_id: CML04_NETWORK_PARTITION_AND_AZ_FAULTS
- fresh_context: YES

## Inputs Read
| path | sha256 | used_for |
|---|---:|---|

## Findings
- ...

## Proposed Changes
| file | action | reason | harness_or_impl |
|---|---|---|---|

## Validation Plan
```bash
...
```

## Risks
| risk | mitigation | blocks_stage |
|---|---|---|

## Machine Summary
```json
{
  "decision": "PROCEED",
  "stage_id": "CML04_NETWORK_PARTITION_AND_AZ_FAULTS",
  "role": "requirements_harness_architect",
  "harness_files": [],
  "implementation_files": [],
  "required_artifacts": [],
  "validation_commands": []
}
```
```

## 4. 主 agent 接受子 agent 输出的标准

主 agent 必须拒绝以下输出：

1. 没有列出读取文件与 sha256。
2. 把 fake/static evidence 当作真实证据。
3. 建议修改 previous harness 来绕过失败。
4. 没有 negative test。
5. 没有 artifact/schema 校验。
6. 没有 cleanup 校验。
7. 对 30/50/100 真实规模目标没有明确 gate 或 closure stage。

## 5. agent 间禁止事项

1. Worker 不得编辑 `agents/requirements_harness_design.response.md`。
2. Worker 不得编辑已冻结 harness，除非主 agent 已创建 `harness_exception.md` 并被 Regression Guard 批准。
3. Reviewer 不得使用 worker narrative 作为唯一证据。
4. Reviewer 必须实际检查 gate logs、artifacts、checksums、git diff。
