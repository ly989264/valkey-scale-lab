# 03_HARNESS_POLICY.md — harness 硬覆盖策略

## 1. previous harness baseline

每个 stage 开始后必须先运行 baseline。除非当前 stage manifest 明确说明某个命令仅在 real-gate stage 才运行，否则 baseline 默认包括：

```bash
python3 scripts/codex_gate.py precheck --all
python3 scripts/safety_scan.py
python3 -m compileall -q src scripts tests
python3 -m pytest -q tests/ci/test_postcheck_compatibility.py
python3 -m pytest -q tests/unit tests/ci/test_github_coverage_gates.py
python3 -m pytest -q tests/config tests/planner
python3 -m pytest -q tests/integration tests/fault tests/failover tests/orchestrator
python3 -m pytest -q tests/analysis tests/report tests/stability tests/scale
```

如果本地已有 GitHub workflow 定义更严格的命令，也必须同时满足 workflow 中的命令。

## 2. 当前 stage harness 类型

每个 stage 必须至少新增或强化一种 harness。优先级：

1. schema validation
2. artifact validation
3. committed artifact compatibility
4. CLI contract tests
5. fake deterministic tests
6. real Valkey e2e gate
7. report/visualization golden tests
8. fresh-context audit tests
9. CI coverage tests

## 3. artifact-first 约束

所有分析与报告必须从 machine-readable artifact 读取，不得直接从 Markdown 报告反推结果。

如果数据缺失，artifact 必须显式编码：

```json
{"status": "MISSING", "value": null, "reason": "..."}
```

或：

```json
{"status": "SKIPPED_WITH_REASON", "reason": "..."}
```

## 4. real Valkey 证据边界

真实 Valkey gate 必须至少验证：

1. `real_valkey: true`
2. Valkey version prefix 符合 `9.1.`
3. 观测节点数达到 stage 要求
4. `cluster_state_observed: ok` 或明确的 failover/partition 预期状态
5. data-path 证明：SET/GET 或等价业务路径
6. cleanup PASS
7. schema validation PASS

1000+ 默认不允许真实自动运行。1000+ 只能 dry-run/resource/planner，除非用户另开明确任务并提供资源与安全确认。

## 5. 反规避检查

anti-regression guardian 必须检查：

```bash
git diff -- tests scripts schemas .github codex artifacts/gates artifacts/phases
```

以下情况默认 BLOCKED：

1. 删除已有 passing test。
2. 把 required 改为 optional。
3. 把 `real_valkey_required` 改为 false。
4. 把 gate status 手写 PASS。
5. 降低 min-nodes。
6. 删除 schema 字段或放宽 enum。
7. 把失败改成 skipped 且无明确 reason 与 reviewer approval。
8. 修改历史 artifact 让结果看起来通过，但没有重新运行对应 gate 或没有记录原因。

## 6. stage 完成验证

每个 stage 完成前必须至少运行：

```bash
python3 scripts/codex_gate.py precheck --all
python3 scripts/safety_scan.py
python3 -m compileall -q src scripts tests
python3 -m pytest -q <stage-specific-tests>
python3 -m pytest -q tests/ci
```

如果 stage 修改了现有 phase artifact 或 gate 结果，还必须运行对应 postcheck 或新增 audit postcheck。
