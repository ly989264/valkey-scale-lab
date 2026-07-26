# Repository Entry Point

This repository has one active product root and one immutable historical
archive:

- project/ 只包含产品、产品测试和 Milestone Checks。
- .github/milestone-loop/ 包含当前启用的自动化控制面。
- loop_evidence/ 仍然是不可修改的历史归档。
- 控制面不能向 project/ 注入运行状态、prompt 或 controller policy。

## GitHub Access

- GitHub 读写操作优先使用已连接的 GitHub Connector，`gh` 仅作为 Connector
  覆盖不足时的 fallback。
- Codex sandbox 中的 `gh auth status` 可能无法访问宿主机 Keychain。不能仅凭
  sandbox 内的认证失败判断用户宿主终端的 GitHub 登录已经失效；需要用户在
  正常宿主终端复核，或使用 GitHub Connector 验证实际访问能力。

## Interactive Codex Changes And Publishing

- 修改 machine-readable 字段或契约时，必须全仓检查其直接 producer、
  consumer 和 validator。最小修改是完成目标所需的最少完整修改，可以包含
  必要的直接 consumer 和聚焦测试，但不能引入无关功能、抽象或重构。若需要
  新增通用框架、迁移机制、命令或 workflow，必须先停止并向用户说明。
- 创建或更新 GitHub Issue/PR 前，必须按仓库当前 coordinator 的约定核对
  metadata、labels 和 changed paths；不得把 GitHub Actions 当作首次格式校验。
- 成功创建 PR 后，必须显式调用 `$explain-diff-for-human-review`，以该 PR 的
  `base...head` 为比较范围，并只在当前 Codex 任务中向用户展示结果；除非用户
  明确要求，不得自动发布 PR comment。
