# codex_goal_loop_m1

这是 milestone1 goal-loop 的主目录。主 agent 在每个 stage 开始时必须重新读取本目录下的协议、stage 文件和模板。

## 目录

```text
docs/       全局合同、协议、覆盖矩阵、harness 规范
prompts/    Codex App goal mode 和多 agent 提示词
stages/     每个 stage 的详细任务说明
templates/  context transfer 和审计产物模板
checklists/ 强制检查清单
```

## 重要原则

- 本 loop 不实现 ECS 多机 native runtime。
- 本 loop 不做长期稳定性 soak。
- 本 loop 专注本地至多 200 真实 Valkey 节点。
- 所有新增指标必须贯穿 schema / writer / reader / analyzer / renderer / fixture / gate。
- 所有报告必须由程序离线自动生成，中文展示，不依赖 LLM。
