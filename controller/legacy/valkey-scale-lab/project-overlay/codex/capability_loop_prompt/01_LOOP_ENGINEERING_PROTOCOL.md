# 01 — Loop Engineering Protocol

## 1. 目标

本协议解决的问题是：长 loop 容易遗忘约束、跑偏、用 narrative 代替证据、用改 harness 规避失败。解决方式是把每个 stage 的上下文、状态、约束、子 agent 输入输出、验证结果全部落盘，并用主 agent 驱动固定状态机。

## 2. 固定状态机

每个 stage 必须完整经过：

```text
+-------------------+
| START             |
+---------+---------+
          |
          v
+-------------------+
| CONTEXT_REFRESH   |
+---------+---------+
          |
          v
+-----------------------------+
| PREVIOUS_HARNESS_VERIFICATION|
+---------+-------------------+
          |
          v
+--------------------------------------+
| REQUIREMENTS_AND_HARNESS_DESIGN_AGENT|
+---------+----------------------------+
          |
          v
+-----------------------------+
| HARNESS_IMPLEMENT_AND_FREEZE|
+---------+-------------------+
          |
          v
+-----------------------------+
| WORKER_IMPLEMENTATION_AGENT |
+---------+-------------------+
          |
          v
+-----------------------------+
| REGRESSION_GUARD_AGENT      |
+---------+-------------------+
          |
          v
+-----------------------------+
| CURRENT_STAGE_VALIDATION    |
+---------+-------------------+
          |
          v
+-----------------------------+
| FIX_LOOP_IF_NEEDED          |
+---------+-------------------+
          |
          v
+-----------------------------+
| FRESH_CONTEXT_REVIEW_AGENT  |
+---------+-------------------+
          |
          v
+-----------------------------+
| STAGE_RESULT_AND_NEXT_CONTEXT|
+---------+-------------------+
          |
          v
+-----------------------------+
| COMMIT_AND_PUSH             |
+---------+-------------------+
          |
          v
+-----------------------------+
| NEXT_STAGE                  |
+-----------------------------+
```

## 3. 必须落盘的文件

每个 stage 根目录：

```text
artifacts/capability_matrix_loop/<STAGE_ID>/
  context_refresh.md
  constraints_snapshot.json
  stage_objective.md
  state_transitions.jsonl
  commands.md
  agents/
    requirements_harness_design.prompt.md
    requirements_harness_design.response.md
    worker.prompt.md
    worker.response.md
    regression_guard.prompt.md
    regression_guard.response.md
    review.prompt.md
    review.response.md
  harness/
    harness_plan.md
    harness_files.json
    harness_freeze.json
    harness_exception.md       # only when needed
  validation/
    previous_harness.log
    current_stage_gate.log
    current_stage_gate_result.json
    regression_guard_result.json
    failed_runs.jsonl
  reports/
    quantitative_summary.json
    report_index.json
  stage_result.json
  next_stage_context.md
```

全局文件：

```text
codex/capability_matrix_loop/state.json
codex/capability_matrix_loop/stage_manifest.json
artifacts/capability_matrix_loop/stage_journal.jsonl
artifacts/capability_matrix_loop/session_context.md
```

## 4. context refresh 规则

每个 stage 开始都必须重新读取：

```text
AGENTS.md
CODEX_START_HERE.md
codex/status/phase_state.json
docs/codex/02_PHASES.md
docs/codex/03_HARNESS_AND_GATES.md
docs/codex/04_AUDITOR.md
docs/codex/05_ARTIFACTS.md
docs/codex/06_FAULT_ISOLATION.md
docs/codex/07_SCALE_POLICY.md
codex/capability_loop_prompt/*.md
codex/capability_matrix_loop/state.json
codex/capability_matrix_loop/stage_manifest.json
artifacts/capability_matrix_loop/<PREVIOUS_STAGE>/next_stage_context.md
```

不要把全部内容粘入对话；写成短摘要与 sha256：

```json
{
  "stage_id": "CML02_CLUSTER_MANAGEMENT_REAL_OPS",
  "read_files": [
    {"path": "AGENTS.md", "sha256": "...", "summary": "..."}
  ],
  "active_constraints": ["no host network mutation", "default max nodes 100", "no fake evidence"]
}
```

## 5. previous harness verification

每个 stage 的前置条件是 previous harness 通过。推荐命令：

```bash
python3 scripts/codex_gate.py precheck --all
python3 scripts/safety_scan.py
python3 -m compileall -q scripts src tests
python3 - <<'PY'
import json, subprocess, pathlib, sys
state = json.loads(pathlib.Path('codex/status/phase_state.json').read_text())
failed = []
for phase in state.get('completed_phases', []):
    r = subprocess.run(['python3', 'scripts/codex_gate.py', 'postcheck', '--phase', phase])
    if r.returncode != 0:
        failed.append(phase)
if failed:
    print('FAILED_PREVIOUS_POSTCHECKS', failed)
    sys.exit(1)
PY
pytest -q
```

结果写入：

```text
artifacts/capability_matrix_loop/<STAGE_ID>/validation/previous_harness.log
```

## 6. stage result schema 要求

`stage_result.json` 至少包含：

```json
{
  "schema_version": "v1",
  "artifact_type": "capability_loop_stage_result",
  "stage_id": "CML02_CLUSTER_MANAGEMENT_REAL_OPS",
  "status": "PASS",
  "created_at": "...",
  "git": {
    "branch": "codex/valkey-scale-lab-loop",
    "head_before": "...",
    "head_after": "...",
    "pushed": true
  },
  "previous_harness": {
    "status": "PASS",
    "commands": []
  },
  "current_harness": {
    "status": "PASS",
    "freeze_sha256": "...",
    "negative_tests_passed": true
  },
  "real_valkey_evidence": {
    "required": true,
    "scale_rungs": [30],
    "evidence_paths": []
  },
  "capability_matrix_delta": [],
  "audit": {
    "decision": "PASS",
    "path": "audit/capability_matrix_loop/CML02_CLUSTER_MANAGEMENT_REAL_OPS/AUDIT.md"
  }
}
```

## 7. fix loop 规则

验证失败时，先分类：

```text
implementation_bug
artifact_schema_bug
real_runtime_failure
resource_preflight_failure
harness_defect
flaky_test_or_timeout
```

默认修实现。只有 `harness_defect` 可以改 harness，且必须满足：

1. 写 `harness_exception.md`，说明原 harness 为什么错误。
2. regression guard 子 agent 确认改动是增强或保持要求，不是削弱。
3. 修改后重新生成 `harness_freeze.json`。
4. 重新跑 previous harness 和 current stage validation。

## 8. commit/push 规则

只有 stage PASS 后才能：

```bash
git status --short
git diff --stat
git add <intentional files>
git commit -m "<STAGE_ID>: <short objective>"
git push origin codex/valkey-scale-lab-loop
```

commit 前必须写入 `stage_result.json`。commit 后更新 `codex/capability_matrix_loop/state.json`，再 commit/push 状态变更；或者把状态变更纳入同一个 commit。不要提交失败 stage 的“完成状态”。
