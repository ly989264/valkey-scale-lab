# MAIN_AGENT_STAGE_ENTRY_PROMPT

用于每个 stage 开始时主 agent 的自检。

你是 milestone1 loop 的主 agent。现在开始一个新的 stage。

必须先执行：

1. 读取 `codex_goal_loop_m1/docs/00_INDEX.md`。
2. 读取所有核心 docs。
3. 读取当前 stage 文件。
4. 读取上一 stage handoff，如果存在。
5. 读取仓库 `AGENTS.md`，如果存在。
6. 记录 `git status` 和当前 HEAD。
7. 建立本 stage coverage matrix 草稿。
8. 启动 design subagent。

禁止直接写代码。
