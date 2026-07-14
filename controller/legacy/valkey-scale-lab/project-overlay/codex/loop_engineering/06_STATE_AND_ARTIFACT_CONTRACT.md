# 06_STATE_AND_ARTIFACT_CONTRACT.md — 状态与产物契约

## 1. 目录布局

```text
codex/loop_engineering/
  README.md
  INSTALL_AND_START.md
  START_MAIN_LOOP.md
  00_OPERATING_CONTRACT.md
  01_STAGE_LOOP_PROTOCOL.md
  02_AGENT_PROTOCOL.md
  03_HARNESS_POLICY.md
  04_STAGE_MANIFEST.md
  05_VALIDATION_COMMANDS.md
  06_STATE_AND_ARTIFACT_CONTRACT.md
  templates/

artifacts/loop_engineering/
  global_loop_state.json
  startup/
    commands.jsonl
    startup_blocker.md
  stages/
    <STAGE_ID>/
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
  reports/
  real_gates/
  dryrun/
  final_audit/
```

## 2. global_loop_state.json

```json
{
  "schema_version": "v1",
  "project": "valkey-scale-lab",
  "branch": "codex/valkey-scale-lab-loop",
  "last_updated_at": "",
  "current_stage": "",
  "stages": [
    {
      "stage_id": "L00_LOOP_ENGINE_HARNESS_BOOTSTRAP",
      "status": "PASS|IN_PROGRESS|BLOCKED|NOT_STARTED",
      "commit_sha": "",
      "pushed": true,
      "result_path": "artifacts/loop_engineering/stages/L00_LOOP_ENGINE_HARNESS_BOOTSTRAP/stage_result.json"
    }
  ],
  "blockers": [],
  "latest_report_index": ""
}
```

## 3. commands.jsonl

每条命令一行 JSON：

```json
{"started_at":"","finished_at":"","cwd":"","command":["python3","-m","pytest","-q","tests/audit"],"exit_code":0,"stdout_tail":"","stderr_tail":"","status":"PASS"}
```

不得只在聊天上下文里描述命令结果。

## 4. stage_state.json

```json
{
  "schema_version": "v1",
  "stage_id": "",
  "status": "IN_PROGRESS",
  "phase": "READ_CONTEXT|PREVIOUS_HARNESS|DESIGN|HARNESS|IMPLEMENT|REVIEW|VALIDATE|COMMIT|PUSH|PASS|BLOCKED",
  "started_at": "",
  "updated_at": "",
  "branch": "codex/valkey-scale-lab-loop",
  "base_head": "",
  "current_head": "",
  "constraints": [],
  "blockers": [],
  "files_touched": []
}
```

## 5. stage_result.json

```json
{
  "schema_version": "v1",
  "stage_id": "",
  "status": "PASS",
  "completed_at": "",
  "commit_sha": "",
  "pushed": true,
  "previous_harness_passed": true,
  "current_harness_passed": true,
  "subagent_verdicts": {
    "requirements_analyst": "APPROVED",
    "harness_architect": "APPROVED",
    "risk_auditor": "APPROVED",
    "implementation_worker": "APPROVED",
    "review_agent": "APPROVED",
    "validation_agent": "APPROVED",
    "anti_regression_guardian": "APPROVED"
  },
  "commands_log": "",
  "artifacts": [],
  "metrics_added": [],
  "visualizations_added": [],
  "real_valkey_gates": [],
  "fake_gates": [],
  "known_missing_metrics": [],
  "risks_remaining": []
}
```

## 6. 敏感信息处理

不得提交：

1. 真实 token、SSH key、cookie。
2. 私有机器路径中包含用户名的敏感路径，除非脱敏。
3. Docker daemon 私密配置。

如果日志中含敏感信息，只提交 tail 摘要或脱敏版本。
