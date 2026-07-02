# 00 — Repository Context

## 当前上下文定位

仓库：`ly989264/valkey-scale-lab`

目标分支：`codex/valkey-scale-lab-loop`

该仓库已经有一个严格的 Codex phase loop：P00-P13 完成基础架构、配置、planner、真实 Valkey runtime、管理操作、workload、metrics、fault sandbox、failover/split-brain、reporting、多 host、soak、10/30 与 50/100 scale ladder。下一阶段不是删除或替换这些阶段，而是在它们之上追加 capability matrix loop。

## 已有控制面

必须优先遵守仓库内已有文件：

```text
AGENTS.md
CODEX_START_HERE.md
codex/phase_manifest.json
codex/gate_lock.json
codex/status/phase_state.json
docs/codex/02_PHASES.md
docs/codex/03_HARNESS_AND_GATES.md
docs/codex/04_AUDITOR.md
docs/codex/05_ARTIFACTS.md
docs/codex/06_FAULT_ISOLATION.md
docs/codex/07_SCALE_POLICY.md
```

其中既有规则的核心含义：

1. P03 之后每个 capability 必须有真实 Valkey e2e proof。
2. fake test 可以辅助，但不能作为真实 evidence。
3. gate result 不是完成条件；postcheck 还要校验 artifact、schema、audit、真实证据、log checksum。
4. fault injection 只能作用于 owned Docker/container namespace、owned container 或显式 sandbox proxy，禁止 host firewall/route/interface/global network 修改。
5. 默认自动规模上限是 100 节点；1000 节点只能 opt-in dry-run/resource-check。

## 新 loop 的落盘位置建议

新 loop 不应修改已有 locked harness。建议新增：

```text
codex/capability_matrix_loop/
  stage_manifest.json
  state.json
  README.md
  schemas/
  templates/
  harness_lock.json
artifacts/capability_matrix_loop/
  stage_journal.jsonl
  <STAGE_ID>/...
audit/capability_matrix_loop/
  <STAGE_ID>/AUDIT.md
  <STAGE_ID>/audit_decision.json
```

新 harness runner 可以放在以下任一安全位置：

```text
tools/capability_matrix_gate.py
src/valkey_scale_lab/capability_loop/gate.py
python3 -m valkey_scale_lab.cli capability gate ...
```

选择时必须尽量复用现有 schema validator、artifact writer、probe wrapper，不要复制大段逻辑。

## 不可做事项

1. 不要改 `codex/gate_lock.json` 来隐藏变更。
2. 不要把 `SKIPPED_WITH_REASON` 当作目标能力 PASS。
3. 不要用 fake cluster、static JSON 或旧 artifact 让新 stage 通过。
4. 不要为了通过当前 stage 删除、放宽或改写 previous harness。
5. 不要默认执行 200/500/1000 真实集群。
6. 不要引入 host-level network mutation。
