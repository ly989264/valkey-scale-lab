# 04_STRONG_HARNESS_LOOP_ENGINE — 强 harness loop 规则

## 基本原则

本 loop 采用强 harness。强 harness 的目标不是“让测试更容易通过”，而是防止：

- 局部补丁。
- fake real。
- 空 artifact。
- 指标只在某一规模出现。
- stage 没完成就 commit。
- report 只读一部分字段。
- context compact 后丢失约束。

## 每个 stage 必跑的基础 gates

主 agent 必须在每个 stage 结束前运行或创建等价 gate：

```text
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
```

如果仓库已有更严格 gate，优先执行已有 gate。

## 每个 stage 必须新增或更新的 stage-specific gates

每个 stage 必须有至少一个 stage-specific assertion，检查本 stage 的核心目标。例如：

```text
assert_run_metadata_contract
assert_setup_timeline_coverage
assert_command_log_nonempty_and_schema
assert_management_matrix_enhanced
assert_workload_benchmark_contract
assert_fault_timeline_contract
assert_system_metrics_contract
assert_zh_report_offline_contract
assert_milestone1_acceptance
```

脚本名不强制一致，但必须能自动运行，且 review 中必须列出命令和结果。

## 真实重型运行策略

如果 Codex App 环境不能运行真实 Docker/Valkey/200 节点：

1. 不得伪造真实运行 PASS。
2. 必须输出 `BLOCKED_WITH_REASON` artifact。
3. 必须仍然完成 code path、schema、fixtures、reader、renderer、gate。
4. 如果 stage 的本质必须真实运行验证，stage 不能标记为 complete，只能标记为 implementation-ready blocked。
5. 主 agent 不得跨过 blocked stage 继续下一 stage，除非用户明确允许。

## 反绕过规则

任何脚本或测试中出现以下模式，review 必须重点检查：

```text
if true: pass
return PASS without checking artifact
empty JSONL accepted
hard-coded status PASS
only checks file exists but not content
ignores stderr/exit code
except Exception: pass
skips all real paths without reason
uses report as metric source instead of artifact source
```

## Gate result 格式

每个 stage 的 gate result 必须包含：

```text
stage_id
run_id
git_sha_before
git_sha_after
commands_run
commands_blocked
status
failures
coverage_matrix_ref
review_ref
commit_sha
pushed_branch
```
