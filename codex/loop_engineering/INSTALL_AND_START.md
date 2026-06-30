# 安装与启动方式

## 0. 前提

本包必须用于本地仓库，且本地仓库必须与远端分支严格同步：

```text
https://github.com/ly989264/valkey-scale-lab/commits/codex/valkey-scale-lab-loop/
```

目标分支固定为：

```text
codex/valkey-scale-lab-loop
```

## 1. 推荐放置方式

在本地执行：

```bash
cd /path/to/valkey-scale-lab

git fetch origin
git checkout codex/valkey-scale-lab-loop

# 必须先确认工作树干净；如果这里有输出，先手动处理，不要继续。
git status --short

# 只有工作树干净时才执行，确保本地与远端严格同步。
git reset --hard origin/codex/valkey-scale-lab-loop

test -f AGENTS.md
test -f CODEX_START_HERE.md
test -f codex/phase_manifest.json
test -f scripts/codex_gate.py

mkdir -p codex/loop_engineering
# 将本包中的 codex/loop_engineering/* 复制到仓库同名目录。

git add codex/loop_engineering
git commit -m "Add loop-engineering audit control pack"
git push origin HEAD:codex/valkey-scale-lab-loop
```

这样做的目的：Codex App 打开该分支后，主 agent 能直接从仓库文件中恢复完整 loop 规范，而不是依赖一次性长 prompt。

## 2. Codex App 启动 prompt

在 Codex App 中打开该仓库与分支，然后提交以下 prompt：

```text
你是 valkey-scale-lab 的 MAIN_LOOP_CONTROLLER。先同步并确认当前本地代码严格位于 origin/codex/valkey-scale-lab-loop，然后读取并执行 codex/loop_engineering/START_MAIN_LOOP.md。不得跳过其中任何读档、harness、子 agent、验证、commit、push 步骤。
```

## 3. 不推荐方式

不推荐只把这些内容粘贴成一次性长 prompt。长 prompt 在多 stage 循环中容易遗忘、截断或被后续上下文污染。本包的设计前提是：loop 规范在 `codex/loop_engineering/` 中持久存在，执行状态在 `artifacts/loop_engineering/` 中持久存在。

## 4. Codex 启动后的第一件事

主 agent 启动后必须先执行 `START_MAIN_LOOP.md` 中的“启动自检”，包括：

```bash
git status --short
git remote -v
git fetch origin
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git rev-parse origin/codex/valkey-scale-lab-loop
```

如果当前 HEAD 不是 `origin/codex/valkey-scale-lab-loop` 的后代或工作树含未知变更，主 agent 必须先记录到 `artifacts/loop_engineering/startup_blocker.md`，不要直接覆盖未知变更。
