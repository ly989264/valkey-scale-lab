# WORKER_SUMMARY — P22_FAULT_REPLICA_HOST_AZ_STOP

## Scope implemented

Implemented the P22 worker scope for replica, logical node-host, and virtual AZ stop faults. The P22 real gate now orchestrates P22-specific 6/10-node configs, resource-preflights the 30-node row, applies stops only through the project `fault apply`/`fault clear` API against owned Valkey processes/containers, records topology/workload/quant artifacts, and fails closed when real Docker setup cannot run.

## Changed files

| Path | Summary |
|---|---|
| `scripts/fault_safety_gate.py` | Added P22 controller, target selectors, owned grouped `node_stop` lifecycle, workload windows, topology snapshots, quant/evidence/cleanup aggregation, 30+ preflight skip handling, and failure-path artifact emission. |
| `scripts/assert_fault_matrix_coverage.py` | Added P22 checks for 6/10 real rows, conditional 30+ evidence/skips, replica role targeting, host/AZ label containment, no 200-node leakage, and no physical host/AZ/network mutation. |
| `scripts/assert_workload_impact.py` | Added P22 per-sample canonical window and comparison coverage checks. |
| `scripts/assert_quant_artifacts.py` | Added P22 event/metric/topology/fault row/evidence/quant count checks. |
| `src/valkey_scale_lab/runtime/docker_runtime.py` | Admitted exact P22 fault-matrix scenarios through the process runtime while preserving the 100-node cap and rejecting P22 200-node scenarios. |
| `templates/configs/p22_6.yaml` | Added 6-node multi-AZ, multi-logical-host P22 config. |
| `templates/configs/p22_10.yaml` | Added 10-node multi-AZ, multi-logical-host P22 config. |
| `templates/configs/p22_30.yaml` | Added 30-node resource-preflighted P22 config. |
| `tests/unit/test_goal_loop_assertions.py` | Added P22 assertion acceptance/rejection tests. |
| `tests/integration/test_docker_runtime_contract.py` | Added P22 scenario admission/routing tests. |
| `artifacts/harness_exception/P22_FAULT_REPLICA_HOST_AZ_STOP.md` | Documented locked-harness strengthening. |
| `codex/gate_lock.json` | Refreshed hashes for strengthened locked harness scripts. |

## Commands run

| Command | Result | Log/artifact path |
|---|---|---|
| `env PYTHONPYCACHEPREFIX=/tmp/vslab_p22_pycache python3 -m compileall -q scripts src` | PASS | terminal output |
| `python3 -m pytest -q tests/unit/test_goal_loop_assertions.py tests/integration/test_docker_runtime_contract.py` | PASS, 88 tests | terminal output |
| `python3 -m pytest -q tests/unit tests/integration` | PASS, 114 tests | terminal output |
| `python3 scripts/safety_scan.py` | PASS | terminal output |
| `python3 scripts/assert_goal_loop_stage.py --phase P22_FAULT_REPLICA_HOST_AZ_STOP` | PASS | terminal output |
| `env PYTHONPATH=src python3 -m valkey_scale_lab.cli config validate --config templates/configs/p22_6.yaml --out /tmp/p22_6_config_validation.json` | PASS | `/tmp/p22_6_config_validation.json` |
| `env PYTHONPATH=src python3 -m valkey_scale_lab.cli config validate --config templates/configs/p22_10.yaml --out /tmp/p22_10_config_validation.json` | PASS | `/tmp/p22_10_config_validation.json` |
| `env PYTHONPATH=src python3 -m valkey_scale_lab.cli config validate --config templates/configs/p22_30.yaml --out /tmp/p22_30_config_validation.json` | PASS | `/tmp/p22_30_config_validation.json` |
| `python3 scripts/codex_gate.py precheck --phase P22_FAULT_REPLICA_HOST_AZ_STOP` | PASS | terminal output |
| `python3 scripts/codex_gate.py run --phase P22_FAULT_REPLICA_HOST_AZ_STOP` | FAIL at real Docker gate in sandbox | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/gate_result.json` |

## Gates and assertions

| Gate/assertion | Result | Evidence path |
|---|---:|---|
| Harness precheck | PASS | terminal output |
| Safety scan | PASS | terminal output |
| Compile | PASS with `/tmp` pycache prefix; manifest compile also passed during `codex_gate run` | terminal output and gate result |
| Unit/integration tests | PASS | terminal output |
| Goal-loop stage assertion | PASS | terminal output |
| Real P22 fault safety gate | FAIL in current sandbox | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/gate_result.json` |
| P22 quant/fault/workload/cleanup assertions on generated real artifacts | FAIL because mandatory 6/10 Docker setup could not run | `artifacts/gates/P22_FAULT_REPLICA_HOST_AZ_STOP/gate_result.json` |

## Artifacts produced

| Artifact | Schema/check | Result |
|---|---|---:|
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/phase_summary.json` | phase summary schema | FAIL status, emitted |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/valkey_e2e_evidence.json` | valkey evidence schema | FAIL status, emitted |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/cleanup_report.json` | cleanup schema | FAIL status, emitted |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/fault_matrix_report.json` | fault matrix schema | emitted |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/fault_results.jsonl` | fault result schema | emitted with 30-node skipped rows only because 6/10 setup failed |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/fault_topology_snapshots.jsonl` | topology snapshot schema | emitted empty because real setup failed before topology |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/workload_impact_report.json` | workload impact schema | emitted empty because real setup failed before workload |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/events.jsonl` | event schema | emitted empty because real setup failed before events |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/metrics_timeseries.jsonl` | metric schema | emitted empty because real setup failed before metrics |
| `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/resource_preflight_30.json` | resource preflight evidence | FAIL due Docker socket/port restrictions |

## Quantitative evidence summary

No successful real P22 samples were collected in this sandbox. The wrapper failed closed and recorded:

- mandatory 6-node setup failed: `port 127.0.0.1:7600 is not available: [Errno 1] Operation not permitted`;
- mandatory 10-node setup failed: `port 127.0.0.1:7620 is not available: [Errno 1] Operation not permitted`;
- 30-node preflight failed because Docker socket access was denied and ports could not be bound in the sandbox.

## Cleanup summary

Aggregate cleanup report exists at `artifacts/phases/P22_FAULT_REPLICA_HOST_AZ_STOP/cleanup_report.json`. It reports `status: FAIL` because mandatory subrun setup failed before real state existed, but `resources_remaining` is empty.

## Deviations from design

The worker did not commit, push, mark complete, or run postcheck. Full real P22 evidence could not be produced in the sandbox because Docker socket and local port binding were unavailable. The main agent should rerun the real gate with approved Docker/port permissions.

## Remaining risks or `待验证`

- `待验证`: successful real 6/10-node P22 samples under an unrestricted Docker runtime.
- `待验证`: real 30-node P22 row when resource preflight passes.
- `待验证`: grouped host/AZ stop recovery behavior on live Valkey; failures should remain measured rows, not hidden.

## Review handoff notes

Review should focus on the P22 controller and strengthened assertions. The current failing run is expected in this sandbox and should not be treated as a passing stage; the next main-agent action is an escalated/approved Docker rerun of `python3 scripts/codex_gate.py run --phase P22_FAULT_REPLICA_HOST_AZ_STOP`.
