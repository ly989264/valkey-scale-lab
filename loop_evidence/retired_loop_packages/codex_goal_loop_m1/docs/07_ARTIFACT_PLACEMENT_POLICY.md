# 07_ARTIFACT_PLACEMENT_POLICY — 文件产物分离规则

## 目标

从 M1-S01 开始，新增运行产物必须和源码分离。

## 建议目录

源码和模板：

```text
src/
scripts/
schemas/
templates/
tests/
docs/
codex_goal_loop_m1/
```

运行产物：

```text
runs/<run_id>/artifacts/
runs/<run_id>/logs/
runs/<run_id>/reports/
runs/<run_id>/state/
```

## 不允许

- 新增真实运行结果直接写进 `artifacts/phases/...` 作为默认路径。
- 继续把大规模 JSONL、日志、报告混入源码目录。
- 报告读取源码目录中的旧 artifact 作为当前 run 结果。
- 只把部分 stage 改到 `runs/`，其他 stage 继续写老路径。

## 兼容要求

如果现有代码仍依赖旧路径：

1. 增加兼容映射。
2. 明确旧路径为 legacy。
3. 新 run 默认写 `runs/<run_id>/...`。
4. analysis/report 优先读取 run manifest。
5. regression test 覆盖新旧路径兼容，但不能让旧路径成为默认。

## 当前 stage 即时整理原则

每个 stage 新增的 artifact 必须在当前 stage 内：

- 选择正确目录。
- 更新 schema。
- 更新 writer。
- 更新 reader。
- 更新 cleanup。
- 更新 report index。
- 更新 test fixture。
- 更新 gate。

不得留到后续 stage 集中整理。
