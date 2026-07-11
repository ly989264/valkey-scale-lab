# L01 Anti-Regression Report

Status: PASS

Base ref: `9d660aa2c87136e8578e7bf1efd96fbcfdc97951`

Head ref: `WORKTREE`

Findings: none.

Checks performed:

- Protected harness controls were not weakened.
- P14 remains opt-in dry-run only and was not executed.
- No historical P00-P13 gate, phase, or audit artifacts were modified to hide findings.
- Generated Python bytecode was restored and is absent from the final tracked diff.
- The legacy manifest SHA allowlist is exact and excludes P14; unallowlisted manifest hash drift is blocking.
- Real Valkey evidence now requires observed `9.1.x` version data.
