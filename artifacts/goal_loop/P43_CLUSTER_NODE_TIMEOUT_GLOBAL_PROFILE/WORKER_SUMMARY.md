# WORKER_SUMMARY — P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE

## Scope implemented

Implemented global/profile/CLI controlled `cluster-node-timeout` with default `30000` ms, propagated timeout provenance through config validation, planner, resource preflight, runtime node specs/state, generated `valkey.conf`, generated-config manifests, real Valkey evidence, P43 aggregate artifacts, and the explicit failover RTO timeout matrix runner.

## Changed files

| Path | Summary |
|---|---|
| `config/valkey_scale_lab_global.yaml` | Added global `cluster.cluster_node_timeout_ms`, timeout matrix, and correctness/failover/management profiles. |
| `src/valkey_scale_lab/cluster_timeout.py` | New central timeout defaults, merge/source helpers, validation, node fields, and `valkey.conf` provenance lines. |
| `src/valkey_scale_lab/config/validation.py` | Added profile-aware timeout merge, validation-report fields, semantic checks, and config source evidence. |
| `src/valkey_scale_lab/runtime/docker_runtime.py` | Removed hidden phase timeout overrides, generated `cluster-node-timeout 30000` plus source comments, added runtime/run-state/artifact timeout fields, and enabled P43 10/30/50/100/200 runtime paths. |
| `src/valkey_scale_lab/planner/plan.py`, `src/valkey_scale_lab/resource.py`, `src/valkey_scale_lab/cli.py` | Added timeout evidence to plans/preflight and CLI override flags. |
| `scripts/valkey_e2e_gate.py`, `scripts/fault_failover_gate.py` | Added timeout evidence fields; failover default now `30000` with explicit `--timeout-config-ms` matrix override. |
| `scripts/failover_rto_timeout_matrix.py`, `scripts/p43_cluster_timeout_artifacts.py` | Added explicit timeout matrix runner and P43 aggregate artifact builder. |
| `scripts/assert_cluster_timeout_config.py`, `scripts/assert_no_hidden_timeout_override.py`, `scripts/assert_timeout_matrix_artifacts.py` | Added fail-closed P43 harness assertions. |
| `schemas/config/run_config.schema.json`, `schemas/artifact/effective_cluster_timeout.schema.json`, `schemas/artifact/timeout_matrix_report.schema.json` | Added schema coverage for timeout config/artifacts. |
| `codex/phase_manifest.json` | Added non-automatic P43 stage gates and required artifacts. |
| `tests/unit/test_cluster_timeout.py` and existing unit/integration/failover tests | Added/updated merge, invalid value, generated config, runtime, and legacy timeout expectations. |
| `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/*` | Produced P43 validation, plan, preflight, generated config manifest, 10/30/50/100/200 real evidence, projection, matrix, quant, analysis, report, cleanup, and summary artifacts. |

## Commands run

| Command | Result | Log/artifact path |
|---|---|---|
| `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 -m compileall -q src scripts` | PASS | terminal |
| `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 -m pytest -q tests/unit/test_cluster_timeout.py tests/unit/test_server_profile.py tests/unit/test_p13_process_bootstrap_batching.py tests/unit/test_nodehost_density.py tests/config/test_config_validation.py tests/planner/test_planner.py tests/integration/test_docker_runtime_contract.py tests/failover/test_failover_contract.py` | PASS, 118 tests | terminal |
| `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 scripts/safety_scan.py` | PASS | terminal |
| `PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 scripts/valkey_e2e_gate.py ... scale_10 ...` | PASS, 10 real nodes | `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/valkey_e2e_evidence.json` |
| `PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 scripts/valkey_e2e_gate.py ... scale_30 ...` | PASS, 30 real nodes | `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/valkey_e2e_evidence_30.json` |
| `PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 scripts/valkey_e2e_gate.py ... scale_50 ...` | PASS, 50 real nodes | `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/valkey_e2e_evidence_50.json` |
| `PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 scripts/valkey_e2e_gate.py ... scale_100 ...` | PASS, 100 real nodes | `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/valkey_e2e_evidence_100.json` |
| `PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 scripts/valkey_e2e_gate.py ... scale_200 ...` | PASS, 200 real nodes | `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/valkey_e2e_evidence_200.json` |
| `PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 scripts/p43_cluster_timeout_artifacts.py` | PASS | `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/phase_summary.json` |
| `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 scripts/assert_cluster_timeout_config.py --phase P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE` | PASS | terminal |
| `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 scripts/assert_no_hidden_timeout_override.py --phase P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE` | PASS | terminal |
| `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 scripts/assert_timeout_matrix_artifacts.py --phase P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE` | PASS | terminal |
| `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 scripts/validate_json_schema.py ...` | PASS for config validation, cluster plan, effective timeout, timeout matrix, and 200-node evidence | terminal |

## Gates and assertions

| Gate/assertion | Result | Evidence path |
|---|---:|---|
| Focused tests | PASS | terminal, 118 passed |
| Safety scan | PASS | terminal |
| Real Valkey 10/30/50/100/200 timeout evidence | PASS | `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/valkey_e2e_evidence*.json` |
| P43 artifact builder | PASS | `artifacts/phases/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE/phase_summary.json` |
| Timeout config assertion | PASS | terminal |
| Hidden override assertion | PASS | terminal |
| Timeout matrix assertion | PASS | terminal |

## Artifacts produced

| Artifact | Schema/check | Result |
|---|---|---:|
| `effective_cluster_timeout.json` | `schemas/artifact/effective_cluster_timeout.schema.json` | PASS |
| `timeout_matrix_report.json` | `schemas/artifact/timeout_matrix_report.schema.json` | PASS, `NOT_RUN_WITH_REASON` row because no full matrix cell was selected |
| `config_validation_report.json` | `schemas/artifact/config_validation_report.schema.json` | PASS |
| `cluster_plan.json` | `schemas/artifact/cluster_plan.schema.json` | PASS |
| `valkey_e2e_evidence_200.json` | `schemas/artifact/valkey_e2e_evidence.schema.json` | PASS |
| `phase_summary.json`, `coverage_ledger.json`, `quant_summary.json`, `analysis_summary.json`, `report_index.json` | P43 builder and assertions | PASS |

## Quantitative evidence summary

All real scale evidence rows for 10, 30, 50, 100, and 200 nodes report `effective_cluster_node_timeout_ms: 30000`. `generated_valkey_configs_manifest.json` proves generated configs include `cluster-node-timeout 30000` and `vslab cluster-node-timeout-source source=global`. Greater-than-200 coverage is `dry_run_gt_200_projection.json` only and does not claim real Valkey execution.

## Cleanup summary

Each real Valkey gate ran its cleanup step. Final P43 aggregate artifacts report cleanup and coverage as PASS; no P43 owned Docker resources were left by the evidence runs.

## Deviations from design

The full timeout matrix was not automatically executed. The runner is implemented and validates selected cells, while the default P43 matrix artifact records `NOT_RUN_WITH_REASON` rather than invented metrics, matching the stage rule that the full large matrix must not run by default.

## Remaining risks or `待验证`

- Full failover RTO matrix cells with non-30000 timeouts remain selectable but were not executed in this worker run.
- Review should inspect whether P43 should update `codex/gate_lock.json`; I did not weaken or hand-edit lock/state files.

## Review handoff notes

Review should focus on hidden legacy timeout removal, P43 real evidence fields, generated config provenance, and exact 10/30/50/100/200 coverage. No commit, push, postcheck, or mark-complete was performed by the worker.
