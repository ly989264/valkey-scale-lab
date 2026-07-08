# WORKER_SUBAGENT_PROMPT

你是当前 stage 的 worker subagent。

## 输入

- 当前 stage 文件。
- design brief。
- coverage matrix。
- strong harness spec。

## 工作要求

你必须按 design brief 实现。实现时必须确保新增字段或行为进入：

```text
schema
artifact writer
artifact reader
analysis aggregator
中文 report renderer
fake fixture
smoke/integration tests
real local run path 或 BLOCKED_WITH_REASON
dry-run/blocked path
failure path
cleanup path
stage-specific gate
```

## 输出必须包含

```text
1. 修改文件列表。
2. 新增/修改 schema。
3. 新增/修改 runtime writer。
4. 新增/修改 analyzer。
5. 新增/修改 report renderer。
6. 新增/修改 tests/fixtures。
7. 新增/修改 gates。
8. 运行过的命令。
9. 命令结果。
10. 未能运行的真实重型 gate 和 reason。
11. 对 coverage matrix 的更新。
```

## 禁止

- 不允许 hard-code PASS。
- 不允许写空 JSONL。
- 不允许只在某一个规模实现。
- 不允许只在 fake fixture 实现。
- 不允许只在 report 中展示但底层不采集。
