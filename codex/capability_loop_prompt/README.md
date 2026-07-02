# Valkey Scale Lab Capability Matrix Loop Prompt Pack

用途：把 `valkey-scale-lab` 从已有 P00-P13 phase loop 延伸到“真实 Valkey 集群能力矩阵闭环”。

这个包不是替换现有 harness，而是要求 Codex 在当前仓库中追加一个 supplemental capability loop：每个 stage 先保证既有 P00-P13 harness 仍可通过，再为当前 stage 设计新 harness，冻结 harness，开发，实现验证，fresh-context review，最后 commit 并 push。

## 文件索引

| 文件 | 用途 |
|---|---|
| `MAIN_LOOP_PROMPT.md` | 粘贴到 Codex App 的启动 prompt |
| `00_REPOSITORY_CONTEXT.md` | 当前仓库上下文、已有 loop 与不可破坏约束 |
| `01_LOOP_ENGINEERING_PROTOCOL.md` | 主循环状态机、防遗忘文件、每 stage 必做动作 |
| `02_MULTI_AGENT_PROTOCOL.md` | 主 agent / 子 agent 分工、结构化交互协议 |
| `03_HARNESS_POLICY.md` | 既有 harness 保护、当前 stage harness 冻结、异常处理 |
| `04_CAPABILITY_STAGE_PLAN.md` | CML00-CML13 stage 目标、能力、验证标准 |
| `05_METRIC_ARTIFACT_REPORT_CONTRACT.md` | 指标、量化数据、分析、可视化 artifact 契约 |
| `06_SCALE_EXECUTION_POLICY.md` | 30/50/100 实跑与 200/500/1000 后续支持策略 |
| `07_TOKEN_EFFICIENCY_POLICY.md` | stage 内节省 token 与早失败策略 |
| `prompts/*.md` | 子 agent 专用 prompt 模板 |
| `templates/*.md` | stage 落盘文件模板 |
| `checklists/*.md` | 每 stage 执行前/执行后 checklist |

## 推荐放置位置

把整个目录复制到仓库根目录，例如：

```bash
mkdir -p codex/capability_loop_prompt
cp -R valkey_capability_loop_pack/* codex/capability_loop_prompt/
```

然后在 Codex App 中粘贴 `MAIN_LOOP_PROMPT.md` 的内容。Codex 主 agent 必须先读取本包全部核心 MD，再启动 loop。
