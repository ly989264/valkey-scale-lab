# 10_ACCEPTANCE_MATRIX.md

## Milestone1 hardening acceptance matrix

| Capability | Required exact scales for milestone PASS | Acceptable evidence for PASS |
|---|---:|---|
| setup telemetry | 30, 50, 100, 200 | M1-format `setup_telemetry.json` with numeric core metrics |
| command audit | 50, 100, 200 plus setup 30 | command log + audit summary with required command kinds |
| management matrix | 50, 100, 200 | M1-format matrix/results/diffs/workload impact/command refs |
| workload benchmark | 30, 50, 100, 200 | benchmark windows across required profiles/windows/metrics |
| fault/failover timeline | 50, 100, 200 and one small smoke | real timeline events/report/failover samples, no fake/PARTIAL as real |
| system metrics | 30, 50, 100, 200 | system metrics windows covering setup, management, workload, fault where applicable, cleanup |
| Chinese offline report | every accepted exact-scale run | generated from accepted M1-format inputs; no fixture-only source for final PASS |
| cleanup | every exact-scale run | clean resources_remaining and command-audited cleanup |

## PASS rule

Milestone PASS requires all required exact-scale claims to PASS. If any required exact-scale claim is missing because the environment cannot run it, milestone status must be `BLOCKED_WITH_REASON`.

## No partial promotion

The following cannot promote a capability to PASS:

- only fixture coverage;
- only one small real run;
- only legacy `valkey_e2e_evidence.json`;
- only report output;
- core metric skipped;
- non-empty JSONL without semantic checks.
