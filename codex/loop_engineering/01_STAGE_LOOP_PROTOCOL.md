# 01_STAGE_LOOP_PROTOCOL.md — 单个 stage 的严格执行流程

下面流程对每个 stage 都必须完整执行。

## Phase A — 重新读档与状态恢复

1. 重新读取 `START_MAIN_LOOP.md` 中列出的全部文档。
2. 读取 `04_STAGE_MANIFEST.md` 中当前 stage 的定义。
3. 写入 `read_context.md`。
4. 初始化或更新 `stage_state.json`：

```json
{
  "stage_id": "",
  "status": "IN_PROGRESS",
  "phase": "READ_CONTEXT",
  "started_at": "",
  "branch": "codex/valkey-scale-lab-loop",
  "base_head": "",
  "constraints": [],
  "blockers": [],
  "files_touched": []
}
```

## Phase B — previous harness 必须先通过

运行 `03_HARNESS_POLICY.md` 中的 previous harness baseline。输出写入：

```text
previous_harness_result.json
commands.jsonl
```

如果 previous harness 失败：

1. 先判断失败是否由环境不可用导致。
2. 如果是代码/测试失败，先修复已有代码，不得继续设计当前 stage harness。
3. 不得通过删除、跳过或放宽已有 harness 解决。
4. 修复后重新运行 previous harness，直到 PASS。

## Phase C — 需求分析 / harness 设计 / 风险审计子 agent

并行或顺序拉起：

1. `requirements_analyst`
2. `harness_architect`
3. `risk_auditor`

每个子 agent 必须读取 stage manifest 和相关代码。输出 JSON 写入 `subagents/`。

主 agent 汇总后写入：

```text
stage_design.md
current_harness_plan.json
```

`current_harness_plan.json` 必须明确：

```json
{
  "stage_id": "",
  "new_tests": [],
  "new_schemas": [],
  "new_cli_gates": [],
  "new_artifact_checks": [],
  "expected_initial_failures": [],
  "acceptance_criteria": []
}
```

## Phase D — 当前 stage harness 先开发

先实现当前 stage 的 harness，包括但不限于：

1. unit tests
2. integration tests
3. CLI gate tests
4. schema validation
5. artifact validation
6. committed artifact compatibility tests
7. fresh-context audit checks
8. real Valkey gate wrapper 或 dry-run gate wrapper

实现 harness 后必须运行当前 stage harness。若它已经通过，必须由 `harness_architect` 或 `review_agent` 说明原因：

- 目标能力已存在；或
- harness 设计太弱，需要补强。

不能因为当前 harness 一开始通过就直接认为 stage 完成。

## Phase E — worker 实现

拉起 `implementation_worker`。worker 只能基于 `stage_design.md` 与 `current_harness_plan.json` 实现。

worker 禁止自行修改已有无问题 harness；如必须修改，走 `00_OPERATING_CONTRACT.md` 的 harness change request 流程。

## Phase F — review / validation / anti-regression

拉起：

1. `review_agent`
2. `validation_agent`
3. `anti_regression_guardian`

要求：

- `review_agent` 检查设计一致性、边界条件、schema/CLI/报告层是否符合 artifact-first。
- `validation_agent` 运行 `05_VALIDATION_COMMANDS.md` 中适用于本 stage 的命令。
- `anti_regression_guardian` 检查 git diff，确认没有通过削弱 harness 过关。

任何一个 agent 输出 `CHANGES_REQUESTED` 或 `BLOCKED`，必须回到 Phase E 或 Phase D 修复。

## Phase G — stage 结果落盘

写入 `validation_result.json`、`anti_regression_report.md`、`stage_result.json`。

`stage_result.json` 必须包含：

```json
{
  "stage_id": "",
  "status": "PASS",
  "completed_at": "",
  "commit_sha": "",
  "pushed": true,
  "previous_harness_passed": true,
  "current_harness_passed": true,
  "real_valkey_gates": [],
  "fake_gates": [],
  "artifacts": [],
  "metrics_added": [],
  "visualizations_added": [],
  "known_missing_metrics": []
}
```

## Phase H — commit + push

只有在 Phase G 以前全部 PASS 后才允许 commit：

```bash
git status --short
git add .
git commit -m "<STAGE_ID>: <summary>"
git push origin HEAD:codex/valkey-scale-lab-loop
```

push 成功后更新 `global_loop_state.json`。
