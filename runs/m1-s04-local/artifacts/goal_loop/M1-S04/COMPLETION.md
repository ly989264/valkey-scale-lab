# M1-S04 Completion

Stage: M1-S04 管理操作矩阵增强

Decision: COMPLETE_WITH_REAL_GATE_BLOCKED

## Completed Work

- Added the M1 management operation matrix artifact contract for all required operations: create cluster, meet nodes, add replica, remove replica, remove primary safe replace, remove failed node, reshard slot range, reshard with keys, rebalance, rolling restart replica-first, and rolling restart primary-safe.
- Propagated new fields through schema, writer, fixtures, reader, analysis aggregator, Chinese report renderer, assertion gate, and docs-stage coverage artifacts.
- Added topology diff artifacts and schema validation for `management_topology_diffs.jsonl`.
- Added workload-impact, cleanup, topology snapshot/diff, command-ref, reshard/rebalance, and rolling-restart refs to matrix and operation result rows.
- Wired the legacy real P04 gate path to emit M1-S04 contract artifacts without fake destructive-operation PASS evidence.
- Wired the strict P30/P31/P32 management writer to emit topology diffs and attach setup command evidence or structured noop/missing reasons.
- Maintained M1-S04 coverage matrix across execution shape, scale rung, functional path, data path, and outcome class.

## Gates

- `PYTHONPATH=src python3 -m pytest -q tests/artifacts/test_management_matrix.py tests/analysis/test_analysis_summary.py tests/report/test_report_rendering.py tests/integration/test_docker_runtime_contract.py` -> PASS, 78 tests.
- `PYTHONPATH=src python3 scripts/assert_management_matrix_m1.py --fixtures tests/fixtures/management_matrix` -> PASS.
- `PYTHONPATH=src python3 scripts/assert_management_matrix_m1.py --artifacts-dir runs/m1-s04-local/artifacts --analysis runs/m1-s04-local/artifacts/analysis_summary.json --report-index runs/m1-s04-local/reports/report_index.json` -> PASS.
- `PYTHONPATH=src python3 -m pytest -q tests/unit tests/integration` -> PASS, 219 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/vslab-pyc python3 -m compileall -q scripts src` -> PASS.
- `git diff --check` -> PASS.
- Schema validation for `management_ops_matrix.json`, `management_operation_results.jsonl`, and `management_topology_diffs.jsonl` -> PASS.

## Real Heavy Gate

The real P04 Valkey management gate was attempted and remains blocked by the local sandbox:

```text
ERROR: gate scenario: port 127.0.0.1:7000 is not available: [Errno 1] Operation not permitted
```

Evidence is recorded in `real_heavy_gate_blocked.json` and `valkey_e2e_evidence_p04.json`. The stage does not claim a fake real PASS.

## Harness Postcheck

- `python3 scripts/codex_gate.py postcheck --phase M1-S04` -> BLOCKED_WITH_REASON: `unknown phase: M1-S04`.
- `python3 scripts/codex_gate.py mark-complete --phase M1-S04` -> BLOCKED_WITH_REASON: `unknown phase: M1-S04`.

The M1 stage-specific gates and review are authoritative for this milestone loop because the legacy phase gate has not been extended with M1-S04 phase IDs.

## Review

Fresh review subagent wrote `REVIEW.md`.

Decision: PASS
