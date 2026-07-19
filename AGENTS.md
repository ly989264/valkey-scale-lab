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
