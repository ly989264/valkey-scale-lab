# COMMIT_AND_HANDOFF_PROMPT

仅当 review subagent 最终 PASS 且 gates PASS 时使用。

## 步骤

1. 确认 `git status`。
2. 确认 diff 只包含当前 stage 合理范围。
3. 写 `COMPLETION.md`。
4. 写 `CONTEXT_RELOAD.md`。
5. commit。
6. push 当前分支。
7. 确认 push 成功。
8. 进入下一 stage。

## commit message

```text
<M1-SXX>: <stage title>

Implemented:
- ...

Harness:
- ...

Coverage:
- ...

Review:
- PASS
```

如果 push 失败：

```text
stage_status: BLOCKED_WITH_REASON
reason: push failed
```

不得进入下一 stage。
