# Audit - P13O-05_PERF_REGRESSION_BUDGET

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-06-29T12:46:04Z

Gate Result: artifacts/gates/P13O-05_PERF_REGRESSION_BUDGET/gate_result.json
Observed Gate Result SHA256: b4c2adcae10ceebd0f53a114d41ee304792e82d5b9468516834f339957058985

## Scope inspected

- `AGENTS.md`, `CODEX_START_HERE.md`
- `codex/phase_manifest.json`
- `codex/p13_optimization_manifest.json`
- `codex/status/p13_optimization_state.json`
- `codex/status/phase_state.json`
- `docs/codex/02_PHASES.md`
- `docs/codex/04_AUDITOR.md`
- `docs/codex/05_P13_OPTIMIZATION_LOOP.md`
- `templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md`
- P13O-05 gate result, stdout logs, and stderr logs
- P13O-05 required artifacts and schemas
- Refreshed P13 scale_50/scale_100 preflight, timing, evidence, state, rung, ladder, and cleanup artifacts
- Relevant diffs for `codex/p13_optimization_manifest.json`, `scripts/p13_optimization_gate.py`, `schemas/artifact/p13_startup_optimization_comparison.schema.json`, `tests/unit/test_p13_perf_budget.py`, and `artifacts/harness_exception/P13O-05_PERF_REGRESSION_BUDGET.md`

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| p13o_perf_budget_tests | PASS | PASS | `artifacts/gates/P13O-05_PERF_REGRESSION_BUDGET/stdout/p13o_perf_budget_tests.log` |
| resource_preflight_50 | PASS | PASS | `artifacts/gates/P13O-05_PERF_REGRESSION_BUDGET/stdout/resource_preflight_50.log` |
| scale_50_default_real_gate | PASS | PASS | `artifacts/gates/P13O-05_PERF_REGRESSION_BUDGET/stdout/scale_50_default_real_gate.log` |
| resource_preflight_100 | PASS | PASS | `artifacts/gates/P13O-05_PERF_REGRESSION_BUDGET/stdout/resource_preflight_100.log` |
| scale_100_default_real_gate | PASS | PASS | `artifacts/gates/P13O-05_PERF_REGRESSION_BUDGET/stdout/scale_100_default_real_gate.log` |
| cleanup_report_50_check | PASS | PASS | `artifacts/gates/P13O-05_PERF_REGRESSION_BUDGET/stdout/cleanup_report_50_check.log` |
| cleanup_report_100_check | PASS | PASS | `artifacts/gates/P13O-05_PERF_REGRESSION_BUDGET/stdout/cleanup_report_100_check.log` |
| p13o_perf_budget_artifact_check | PASS | PASS | `artifacts/gates/P13O-05_PERF_REGRESSION_BUDGET/stdout/p13o_perf_budget_artifact_check.log` |

All eight manifest gates are present in order. The command strings in `gate_result.json` exactly match `codex/p13_optimization_manifest.json`. The recorded P13O manifest SHA256 matches the current manifest. Every stdout and stderr path exists, and every SHA256 in `gate_result.json` matches the file content.

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P13O_PERF_REGRESSION_BUDGET/p13_startup_optimization_comparison.json` | `schemas/artifact/p13_startup_optimization_comparison.schema.json` | valid | status PASS, budget_mode warning |
| `artifacts/phases/P13O_PERF_REGRESSION_BUDGET/phase_summary.json` | `schemas/artifact/p13_optimization_phase_summary.schema.json` | valid | status PASS |
| `artifacts/gates/P13O-05_PERF_REGRESSION_BUDGET/gate_result.json` | `schemas/artifact/p13_optimization_gate_result.schema.json` | valid | status PASS |
| `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_50.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | valid | 50 live probes |
| `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | valid | 100 live probes |
| `artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json` | `schemas/artifact/p13_timing_breakdown.schema.json` | valid | status PASS |
| `artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_100.json` | `schemas/artifact/p13_timing_breakdown.schema.json` | valid | status PASS |
| `artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report_scale_50.json` | `schemas/artifact/cleanup_report.schema.json` | valid | no resources remaining |
| `artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report_scale_100.json` | `schemas/artifact/cleanup_report.schema.json` | valid | no resources remaining |
| `artifacts/phases/P13_SCALE_LADDER_50_100/resource_preflight_50.json` | `schemas/artifact/resource_preflight.schema.json` | valid | node cap PASS |
| `artifacts/phases/P13_SCALE_LADDER_50_100/resource_preflight_100.json` | `schemas/artifact/resource_preflight.schema.json` | valid | node cap PASS |

`p13_startup_optimization_comparison.json` records machine-readable budget thresholds and results for real gate duration, wrapper probe, cleanup, and unattributed time for both scale rungs. Default mode is `warning`; `strict_env_var` is `VSLAB_STRICT_PERF_BUDGET`; `strict_enabled` is false for this run. Unit coverage verifies default warning behavior, strict failure behavior, missing metric failure, and strict env opt-in.

## Safety findings

- Host network mutation: absent in inspected P13O-05 diffs and artifacts.
- Global firewall mutation: absent in inspected P13O-05 diffs and artifacts.
- Sudo default path: absent in inspected P13O-05 diffs and artifacts.
- Cleanup logic: verified through scale-specific cleanup reports and cleanup gates.
- Default node cap <= 100: verified in P13O manifest, resource preflight artifacts, and comparison safety constraints.
- P14 execution: absent. No P14 gate/artifact directory was found, `codex/status/phase_state.json` does not mark P14 complete, and the comparison artifact records `p14_executed: false`.

The protected harness change is documented in `artifacts/harness_exception/P13O-05_PERF_REGRESSION_BUDGET.md`. The inspected patch strengthens P13O-05 by adding required gates, schema, artifact validation, and tests; no weakening of safety or real-evidence requirements was observed.

## Real Valkey findings

Required for this phase: YES
Evidence files: `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_50.json`, `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json`
Valkey version observed: `9.1.0`
Independent live probe evidence: PASS

The scale_50 evidence has `real_valkey: true`, `nodes_observed: 50`, `probe_result: PASS`, `data_path_result: PASS`, `cluster_state_observed: ok`, 25 primaries, 25 replicas, no fail/pfail/handshake nodes, and all probes record `PONG`, `version: 9.1.0`, `cluster_known_nodes: 50`, and `cluster_state: ok`.

The scale_100 evidence has `real_valkey: true`, `nodes_observed: 100`, `probe_result: PASS`, `data_path_result: PASS`, `cluster_state_observed: ok`, 50 primaries, 50 replicas, no fail/pfail/handshake nodes, and all probes record `PONG`, `version: 9.1.0`, `cluster_known_nodes: 100`, and `cluster_state: ok`.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| None identified | low | no | Evidence required by P13O-05 is present and machine-valid. |

## Final rationale

The repository evidence supports PASS. Every P13O-05 manifest gate ran and passed with exact command matches and matching log hashes. Required P13O-05 artifacts exist and validate. Refreshed P13 50/100-node artifacts validate and prove live Valkey 9.1.x clusters with data-path proof, full membership, correct role counts, and cleanup success. The budget artifact is machine-readable, defaults to warning mode, and documents strict opt-in support through `VSLAB_STRICT_PERF_BUDGET=1`. Safety constraints remain intact, and P14 was not run.
