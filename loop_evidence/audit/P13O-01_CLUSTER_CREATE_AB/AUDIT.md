# Audit — P13O-01_CLUSTER_CREATE_AB

Decision: PASS
Fresh Context: YES
Auditor: fresh-context-codex-reviewer
Audit Time: 2026-06-29T11:31:36Z

Gate Result: artifacts/gates/P13O-01_CLUSTER_CREATE_AB/gate_result.json
Observed Gate Result SHA256: 23771065c4d093e8c2c2c1653821e6d76acc9ebc0062f0824b2ff9a609218c6a

## Scope inspected

- `AGENTS.md`
- `CODEX_START_HERE.md`
- `docs/codex/04_AUDITOR.md`
- `docs/codex/05_P13_OPTIMIZATION_LOOP.md`
- `templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md`
- `templates/audit/AUDIT_TEMPLATE.md`
- `templates/audit/audit_decision.template.json`
- `codex/p13_optimization_manifest.json`
- `codex/status/p13_optimization_state.json`
- `artifacts/harness_exception/P13O-01_CLUSTER_CREATE_AB.md`
- phase source changes in `scripts/p13_optimization_gate.py`, `src/valkey_scale_lab/runtime/docker_runtime.py`, and `tests/integration/test_docker_runtime_contract.py`
- gate result and stdout/stderr logs
- required artifacts and schemas
- cleanup evidence
- real Valkey evidence for default 50/100 and manual 50

## Gate findings

| Gate | Expected | Observed | Evidence |
|---|---:|---:|---|
| p13o_cluster_create_tests | PASS | PASS | command matched manifest; stdout/stderr SHA256 matched gate_result.json |
| resource_preflight_50 | PASS | PASS | command matched manifest; stdout/stderr SHA256 matched gate_result.json |
| scale_50_default_real_gate | PASS | PASS | `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_50.json` |
| resource_preflight_100 | PASS | PASS | command matched manifest; stdout/stderr SHA256 matched gate_result.json |
| scale_100_default_real_gate | PASS | PASS | `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json` |
| scale_50_manual_strategy_real_gate | PASS | PASS | `artifacts/phases/P13O_CLUSTER_CREATE_AB/valkey_e2e_evidence_manual_scale_50.json` |
| default_cleanup_report_check | PASS | PASS | `artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report.json` |
| manual_cleanup_report_check | PASS | PASS | `artifacts/phases/P13O_CLUSTER_CREATE_AB/cleanup_report.json` |
| p13o_cluster_create_artifact_check | PASS | PASS | `artifacts/gates/P13O-01_CLUSTER_CREATE_AB/stdout/p13o_cluster_create_artifact_check.log` |

All nine manifest gates are present in `gate_result.json`, all are required, all exited 0, and all recorded commands exactly match `codex/p13_optimization_manifest.json`.

## Artifact findings

| Artifact | Schema | Observed | Evidence |
|---|---|---:|---|
| `artifacts/phases/P13O_CLUSTER_CREATE_AB/p13_cluster_create_strategy_comparison.json` | `schemas/artifact/p13_cluster_create_strategy_comparison.schema.json` | valid | status PASS; default strategy `valkey_cli_cluster_create_primaries`; manual strategy opt-in |
| `artifacts/phases/P13O_CLUSTER_CREATE_AB/phase_summary.json` | `schemas/artifact/p13_optimization_phase_summary.schema.json` | valid | status PASS; errors `[]` |
| `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_50.json` | wrapper evidence | valid for audit | real_valkey true; 50 nodes; data path PASS |
| `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json` | wrapper evidence | valid for audit | real_valkey true; 100 nodes; data path PASS |
| `artifacts/phases/P13O_CLUSTER_CREATE_AB/valkey_e2e_evidence_manual_scale_50.json` | wrapper evidence | valid for audit | real_valkey true; 50 nodes; data path PASS |

## Safety findings

- Host network mutation: absent
- Global firewall mutation: absent
- Sudo default path: absent
- Cleanup logic: verified
- Default node cap <= 100: verified
- P14 execution: absent
- nodes.conf fast-bootstrap: absent; normal Valkey `cluster-config-file nodes.conf` config entries are present, but no preseeded fast-bootstrap path was used

The comparison artifact records `nodes_conf_fast_bootstrap_used: false`, `host_network_mutation: false`, `p14_executed: false`, and `default_max_nodes: 100`. Source inspection found the manual strategy is selected only by `VSLAB_CLUSTER_CREATE_STRATEGY=manual_tree_meet_parallel_slots`; default remains `valkey_cli_cluster_create_primaries`.

## Real Valkey findings

Required for this phase: YES
Evidence file: default 50/100 and manual 50 evidence listed above
Valkey version observed: 9.1.0
Independent live probe: PASS via `scripts/valkey_e2e_gate.py` evidence; endpoints were subsequently cleaned up

Default 50-node evidence reports `real_valkey: true`, `nodes_observed: 50`, role counts 25 primary / 25 replica, data path PASS, `valkey_version_prefix_required: 9.1.`, and per-probe version 9.1.0. Default 100-node evidence reports 100 nodes, 50 primary / 50 replica, data path PASS, and version 9.1.0. Manual strategy evidence reports 50 nodes, 25 primary / 25 replica, data path PASS, and version 9.1.0.

## Risks and follow-ups

| Risk | Severity | Required before next phase? | Notes |
|---|---|---:|---|
| Manual strategy has 50-node proof only | low | no | Manifest requires manual 50-node proof while preserving default 50/100 gates; comparison marks manual 100 as `SKIPPED_WITH_REASON` and keeps default unchanged. |

## Final rationale

P13O-01 has sufficient repository evidence to pass: every manifest gate ran and passed, command text and log hashes match, required artifacts validate, real Valkey 9.1.0 evidence exists for default 50/100 and manual 50, cleanup reports are PASS with no remaining resources, and safety/default constraints remain intact. The harness exception documents a strengthening change that adds phase gates, schemas, and explicit opt-in strategy support without changing the safe default.
