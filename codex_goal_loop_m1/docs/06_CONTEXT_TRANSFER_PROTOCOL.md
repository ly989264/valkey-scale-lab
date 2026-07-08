# 06_CONTEXT_TRANSFER_PROTOCOL — 上下文传递协议

## 目的

Codex 的上下文可能 compact。为了防止跨 stage 信息丢失，每个 stage 必须写结构化 handoff 文档。

## 必须写入的文件

每个 stage 完成或 blocked 时，必须写：

```text
runs/<run_id>/artifacts/goal_loop/<stage_id>/CONTEXT_RELOAD.md
runs/<run_id>/artifacts/goal_loop/<stage_id>/DESIGN_BRIEF.md
runs/<run_id>/artifacts/goal_loop/<stage_id>/WORKER_SUMMARY.md
runs/<run_id>/artifacts/goal_loop/<stage_id>/REVIEW.md
runs/<run_id>/artifacts/goal_loop/<stage_id>/COMPLETION.md
runs/<run_id>/artifacts/goal_loop/<stage_id>/coverage_matrix.md
```

如果 M1-S01 之前还没有 run 目录规范，M1-S01 必须先建立，随后补写本 stage 文件。

## CONTEXT_RELOAD.md 必须包含

```text
stage_id
stage_status
git_sha_before
git_sha_after
commit_sha
pushed_branch
files_changed
schemas_changed
artifacts_changed
tests_added
gates_run
gates_blocked
coverage_matrix_summary
open_risks
next_stage_instructions
```

## 跨 stage 读取规则

主 agent 进入下一 stage 时必须读取：

- 当前 stage 文件。
- 上一个 stage 的 `CONTEXT_RELOAD.md`。
- 上一个 stage 的 `REVIEW.md`。
- 上一个 stage 的 `COMPLETION.md`。
- 全局 docs。
- 当前仓库 `AGENTS.md`，如果存在。

## 信息污染防护

不允许在 handoff 中写含糊内容：

```text
done
looks good
maybe later
TODO
N/A
should be okay
```

所有未完成项必须写成：

```text
BLOCKED_WITH_REASON
SKIPPED_WITH_REASON
UNSUPPORTED_WITH_REASON
MISSING_WITH_REASON
```
