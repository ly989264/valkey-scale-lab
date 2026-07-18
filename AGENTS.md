# Repository Entry Point

This repository has one active product root and one immutable historical
archive:

- project/ 只包含产品、产品测试和 Milestone Checks。
- .github/milestone-loop/ 包含当前启用的自动化控制面。
- loop_evidence/ 仍然是不可修改的历史归档。
- 控制面不能向 project/ 注入运行状态、prompt 或 controller policy。
