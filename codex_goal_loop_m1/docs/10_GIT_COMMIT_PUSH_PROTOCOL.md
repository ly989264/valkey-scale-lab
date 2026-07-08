# 10_GIT_COMMIT_PUSH_PROTOCOL — Git commit / push 协议

## 每个 stage 的 Git 流程

1. stage 开始时记录 `git status` 和 `git rev-parse HEAD`。
2. 完成实现和 gates。
3. review subagent 给出 `PASS`。
4. 主 agent 检查 diff，只包含当前 stage 范围。
5. commit。
6. push 当前分支。
7. 写 `COMPLETION.md` 和 `CONTEXT_RELOAD.md`。
8. 进入下一 stage。

## Commit message 格式

```text
<M1-SXX>: <short summary>

- Implemented: ...
- Harness: ...
- Coverage: ...
- Reports: ...
- Review: PASS
```

## 不允许

- review FAIL 后 commit。
- gates FAIL 后 commit。
- 未 push 就进入下一 stage。
- 在同一 commit 混入多个 stage 的无关改动。
- 改写历史 commit。
- 伪造 push 成功。

## push 失败处理

如果 push 失败：

```text
stage_status: BLOCKED_WITH_REASON
reason: push failed
next_action: user intervention required
```

不得进入下一 stage。
