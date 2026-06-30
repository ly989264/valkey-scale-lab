# valkey-scale-lab loop-engineering 审计能力补强包

本目录是给 Codex App 主 agent 使用的持久化 loop 控制文件包。它不替代现有 `AGENTS.md`、`CODEX_START_HERE.md`、`codex/phase_manifest.json` 或 `scripts/codex_gate.py`，而是在现有 harness 上叠加更严格的审计、状态落盘、多 agent 协作和多 stage 验证约束。

## 放置位置

必须放在仓库根目录的：

```text
codex/loop_engineering/
```

运行期间生成的 loop 状态、子 agent 输出、命令日志和 stage 证据必须放在：

```text
artifacts/loop_engineering/
```

`codex/loop_engineering/` 是源控制内的 loop 规范；`artifacts/loop_engineering/` 是每轮执行的持久化记忆和审计证据。两者都应随 stage commit 入库，除非包含机器本地敏感信息；敏感信息必须脱敏或摘要化。

## 启动文件

Codex App 启动时只需要给主 agent 一个很短的 prompt：

```text
你是 valkey-scale-lab 的 MAIN_LOOP_CONTROLLER。先同步并确认当前本地代码严格位于 origin/codex/valkey-scale-lab-loop，然后读取并执行 codex/loop_engineering/START_MAIN_LOOP.md。不得跳过其中任何读档、harness、子 agent、验证、commit、push 步骤。
```

完整操作见 `INSTALL_AND_START.md`。

## 核心原则

1. 每个 stage 开始都必须重新读取项目与 loop 文档，防止上下文遗忘。
2. 每个 stage 必须先确认此前 harness 全通过，再设计当前 stage harness，再实现，再验证。
3. 任何失败都必须修复实现或补充证据，不得通过放宽已有 harness 规避。
4. 每个 stage 必须形成结构化文件证据，并在全部验证通过后 commit + push。
5. 主 agent 负责 loop 状态机；需求、harness、实现、review、验证、反规避必须由不同子 agent 或等价隔离上下文完成。
