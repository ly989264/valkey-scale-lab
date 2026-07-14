# 03 — Harness Policy

## 1. Harness 分层

新 capability loop 的 harness 必须叠在已有 P00-P13 harness 之上：

```text
+-----------------------------------------------+
| capability loop review/audit                  |
+-------------------------+---------------------+
                          |
                          v
+-----------------------------------------------+
| capability stage gate                          |
| manifest + schemas + negative tests + evidence|
+-------------------------+---------------------+
                          |
                          v
+-----------------------------------------------+
| existing P00-P13 harness                       |
| codex_gate.py + phase artifacts + audits       |
+-------------------------+---------------------+
                          |
                          v
+-----------------------------------------------+
| real Valkey runtime + probes + artifacts       |
+-----------------------------------------------+
```

## 2. Previous harness 保护

每个 stage 开始和结束都要运行 previous harness verification。任何失败都阻塞当前 stage。

禁止改动或削弱：

```text
codex/phase_manifest.json
codex/gate_lock.json
scripts/codex_gate.py
scripts/valkey_e2e_gate.py
scripts/fault_safety_gate.py
scripts/fault_failover_gate.py
docs/codex/**/*
templates/audit/**/*
schemas/artifact/* used by existing P00-P13
.github/workflows/codex-gates.yml
```

若这些文件确有 bug，只能用 existing AGENTS.md 的 harness exception 规则；默认不要触碰。

## 3. 当前 stage harness 要求

每个 stage 的新 harness 必须包含：

1. **Manifest entry**：stage id、目标、required artifacts、commands、timeout、scale profile。
2. **Schema**：所有 JSON/JSONL artifact 有 schema；不能只靠 Python dict 检查。
3. **Negative tests**：缺 artifact、fake evidence、空 metrics、MISSING 误当 PASS、skip 误当 PASS、旧 artifact 复用、cleanup 缺失都必须失败。
4. **Positive tests**：最小真实或可证明路径能 PASS。
5. **Real Valkey evidence check**：30/50/100 closure stage 必须验证真实 live endpoint、Valkey 9.1.x、cluster state、data path、slot coverage。
6. **Metric linkage check**：操作/故障事件必须能连接到 metrics window、analysis summary、visual report。
7. **Cleanup check**：owned resources 必须清理或失败。
8. **No-host-mutation check**：fault stage 必须验证没有 host firewall/route/interface/global network mutation。

## 4. Harness freeze

当前 stage harness 设计完成后，主 agent 必须计算文件 sha256：

```bash
python3 - <<'PY'
import hashlib, json, pathlib
files = [
  # fill with current stage harness files
]
out = []
for f in files:
    p = pathlib.Path(f)
    out.append({"path": f, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
pathlib.Path('artifacts/capability_matrix_loop/<STAGE_ID>/harness/harness_freeze.json').write_text(
    json.dumps({"schema_version": "v1", "stage_id": "<STAGE_ID>", "files": out}, indent=2) + "\n"
)
PY
```

Worker 之后不得修改这些文件。

## 5. Harness exception

只有在 harness 本身错误时才允许修改冻结 harness。流程：

```text
failure observed
  -> classify as harness_defect
  -> write harness_exception.md
  -> Regression Guard reviews
  -> patch harness only to strengthen/preserve requirement
  -> regenerate harness_freeze.json
  -> rerun previous harness
  -> rerun current stage gate
```

`harness_exception.md` 必须包含：

```markdown
# Harness Exception

- stage_id:
- failing command:
- original harness file:
- defect:
- why this is not weakening:
- before behavior:
- after behavior:
- reviewer decision:
```

## 6. “不准规避”的具体判定

以下都算规避：

1. 把 required gate 改 optional。
2. 把真实 Valkey gate 改 fake/unit test。
3. 把 `FAIL` 改成 `SKIPPED_WITH_REASON` 来过 stage。
4. 把 required artifact 从 manifest/schema 中删除。
5. 把 missing metric 填 0。
6. 图表没有数据源 checksum 但标 PASS。
7. 复用旧 stage artifact 冒充当前 stage fresh run。
8. 关闭 cleanup 检查。
9. 放宽 30/50/100 节点数量检查。
