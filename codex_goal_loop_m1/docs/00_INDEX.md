# 00_INDEX — milestone1 goal-loop 文档索引

主 agent 在每个 stage 开始时必须读取本索引，并按索引重新加载相关文档。

## 核心文档

1. `01_GOAL_CONTRACT.md`：目标合同。
2. `02_STAGE_MANIFEST.md`：stage 顺序和依赖。
3. `03_GLOBAL_COVERAGE_MATRIX.md`：全局覆盖矩阵。
4. `04_STRONG_HARNESS_LOOP_ENGINE.md`：强 harness loop 规则。
5. `05_MULTI_AGENT_STAGE_PROTOCOL.md`：多 agent 流程。
6. `06_CONTEXT_TRANSFER_PROTOCOL.md`：跨 stage 上下文传递。
7. `07_ARTIFACT_PLACEMENT_POLICY.md`：源码和运行产物分离。
8. `08_SCHEMA_ARTIFACT_CONTRACT.md`：schema 和 artifact 传播规则。
9. `09_NO_PARTIAL_IMPLEMENTATION_RULES.md`：禁止局部补丁。
10. `10_GIT_COMMIT_PUSH_PROTOCOL.md`：commit / push 规则。
11. `11_MILESTONE1_ACCEPTANCE.md`：最终验收标准。
12. `12_REPORT_ZH_OFFLINE_CONTRACT.md`：中文离线报告合同。
13. `13_RISK_REGISTER.md`：风险登记。
14. `14_STAGE_ENTRY_CHECKLIST.md`：stage 入口清单。
15. `15_STAGE_EXIT_CHECKLIST.md`：stage 出口清单。

## Stage 文件

- `stages/M1_S01_ENGINEERING_STRUCTURE_RUN_METADATA.md`
- `stages/M1_S02_CLUSTER_SETUP_TELEMETRY.md`
- `stages/M1_S03_COMMAND_AUDIT_LOG.md`
- `stages/M1_S04_MANAGEMENT_MATRIX_ENHANCEMENT.md`
- `stages/M1_S05_WORKLOAD_BENCHMARK.md`
- `stages/M1_S06_FAULT_FAILOVER_TIMELINE.md`
- `stages/M1_S07_SYSTEM_METRICS.md`
- `stages/M1_S08_ZH_OFFLINE_VISUAL_REPORT.md`
- `stages/M1_S09_MILESTONE1_ACCEPTANCE_GATE.md`

## Prompt 文件

- `prompts/GOAL_MODE_START_PROMPT.md`
- `prompts/MAIN_AGENT_STAGE_ENTRY_PROMPT.md`
- `prompts/DESIGN_SUBAGENT_PROMPT.md`
- `prompts/WORKER_SUBAGENT_PROMPT.md`
- `prompts/REVIEW_SUBAGENT_PROMPT.md`
- `prompts/COMMIT_AND_HANDOFF_PROMPT.md`

## 模板

- `templates/COVERAGE_MATRIX_TEMPLATE.md`
- `templates/STAGE_DESIGN_BRIEF_TEMPLATE.md`
- `templates/STAGE_WORKER_SUMMARY_TEMPLATE.md`
- `templates/STAGE_REVIEW_REPORT_TEMPLATE.md`
- `templates/STAGE_CONTEXT_RELOAD_TEMPLATE.md`
- `templates/STAGE_COMPLETION_TEMPLATE.md`
- `templates/GATE_RESULT_TEMPLATE.md`
- `templates/COMMIT_MESSAGE_TEMPLATE.md`
