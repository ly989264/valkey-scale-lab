# START_MAIN_LOOP.md — MAIN_LOOP_CONTROLLER 启动入口

你是 `MAIN_LOOP_CONTROLLER`。你的职责不是直接写完所有功能，而是严格驱动一个可恢复、可审计、harness-first、多 agent 的 stage loop。

## 1. 启动自检

先执行并记录以下命令，输出写入 `artifacts/loop_engineering/startup/commands.jsonl`：

```bash
git status --short
git remote -v
git fetch origin
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git rev-parse origin/codex/valkey-scale-lab-loop
```

约束：

1. 当前分支必须是 `codex/valkey-scale-lab-loop`。
2. 当前代码必须与 `origin/codex/valkey-scale-lab-loop` 严格同步，或是该远端分支的线性后代。
3. 不得在未记录原因时覆盖工作树中已有变更。
4. 如发现 blocker，写入 `artifacts/loop_engineering/startup/startup_blocker.md` 并停止本轮。

## 2. 每次循环开始必须重新读档

每个 stage 开始前，必须重新读取以下文件；不得依赖记忆：

```text
README.md
AGENTS.md
CODEX_START_HERE.md
codex/phase_manifest.json
.github/workflows/*.yml
codex/loop_engineering/README.md
codex/loop_engineering/00_OPERATING_CONTRACT.md
codex/loop_engineering/01_STAGE_LOOP_PROTOCOL.md
codex/loop_engineering/02_AGENT_PROTOCOL.md
codex/loop_engineering/03_HARNESS_POLICY.md
codex/loop_engineering/04_STAGE_MANIFEST.md
codex/loop_engineering/05_VALIDATION_COMMANDS.md
codex/loop_engineering/06_STATE_AND_ARTIFACT_CONTRACT.md
artifacts/loop_engineering/global_loop_state.json    # 如果存在
artifacts/loop_engineering/stages/*/stage_result.json # 如果存在
```

读档后，写入：

```text
artifacts/loop_engineering/stages/<STAGE_ID>/read_context.md
```

其中必须列出本 stage 实际读取的文件、摘要、发现的约束、与当前 stage 有关的风险。

## 3. 选择下一个 stage

读取 `04_STAGE_MANIFEST.md` 和 `artifacts/loop_engineering/global_loop_state.json`。

选择第一个未完成 stage。若不存在 global state，则从 `L00_LOOP_ENGINE_HARNESS_BOOTSTRAP` 开始。

## 4. 执行 stage

对选中的 stage，严格执行 `01_STAGE_LOOP_PROTOCOL.md`。

任何 stage 完成条件都包括：

1. previous harness 全通过。
2. 当前 stage harness 已先设计并落盘。
3. 当前 stage 实现已完成。
4. 当前 stage 验证全通过。
5. anti-regression guardian 确认没有通过修改无问题 harness 来规避失败。
6. `stage_result.json` 状态为 `PASS`。
7. 已 commit。
8. 已 push 到 `origin/codex/valkey-scale-lab-loop`。

## 5. 循环继续条件

一个 stage 完成并 push 后，立即进入下一个 stage 的启动读档流程。不要依赖上一轮上下文。

如果运行环境或资源不足以执行某个 real Valkey stage，不得把该 stage 标记为完成；必须把 blocker、资源检测结果、未完成项写入 stage artifact。
