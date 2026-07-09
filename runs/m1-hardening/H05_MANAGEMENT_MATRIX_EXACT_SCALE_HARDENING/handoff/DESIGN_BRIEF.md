role: design
agent_invocation: real_subagent
stage_id: H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
source_commit_before: 8f6b557f416ccc2941009ea9b5e4a0c3eaeb7bc4
source_commit_after: MISSING

# H05 Design Brief

## Decision

Implement H05 as a fail-closed management matrix semantic gate. The stage should pass the hardening loop only when every 50/100/200 management claim is either a fully validated real exact-scale PASS or an explicit `BLOCKED_WITH_REASON` with H05 diagnostics. Current artifacts should not be promoted unless they satisfy the full M1 management contract.

## Key Requirements

- Required claims: `management_matrix.real_exact.50`, `.100`, `.200`.
- Required operations: `create_cluster`, `meet_nodes`, `add_replica`, `remove_replica`, `remove_primary_drained_or_safe_replaced`, `remove_failed_node`, `reshard_slot_range`, `reshard_with_keys`, `rebalance_after_imbalance`, `rolling_restart_replica_first`, `rolling_restart_primary_safe`.
- Required same-run artifact bundle for PASS: `management_ops_matrix.json`, `management_operation_results.jsonl`, `management_topology_snapshots.jsonl`, `management_workload_impact.json`, `workload_windows.json`, `management_command_log.jsonl`, and `valkey_e2e_evidence.json`.
- Exact scale must be exact equality against 50, 100, or 200 nodes, with real Valkey and Valkey 9.1.x evidence.
- No fixture path, legacy-only Valkey evidence, non-empty file check, empty management command log, unresolved ref, or skipped core metric may satisfy PASS.

## Implementation Shape

1. Add `evaluate_management_matrix_claim(...)` in `scripts/m1h/manifest.py`.
2. Make management manifest diagnostics populate `diagnostics.management_h05_acceptance`.
3. Return `REAL_EXACT_SCALE` for management only when H05 diagnostics are accepted.
4. Replace `scripts/m1h/assert_management_exact_scale.py` with a H05-specific evaluator modeled after `assert_command_audit_real.py`.
5. Add H05 to `scripts/m1h/assert_stage_exit.py` required gate results.
6. Add unit/integration tests for unsafe PASS, honest blocked claims, missing diagnostics, ref resolution, command traceability, and H05 stage-exit requirements.

## PASS Semantics

For a management claim to PASS:

- manifest claim status is `PASS`;
- evidence kind is promotable;
- all required H05 semantic checks are true;
- `management_h05_acceptance.accepted` is true;
- all source artifacts are non-fixture and in a coherent run bundle;
- matrix and result rows are schema-valid and exact-scale;
- each required operation has PASS result semantics and operation-specific proof;
- topology refs resolve and prove stable cluster state, complete slots, exact known nodes, and no fail/pfail residue;
- workload refs resolve and contain numeric QPS, latency, timeout, redirection, and error metrics;
- command refs resolve to C07-valid command rows with output hashes, matching operation ids, no placeholder argv, and consistent retry/failure/timeout/error counts.

For a blocked claim to be accepted by the H05 hardening gate:

- manifest claim status is `BLOCKED_WITH_REASON`;
- claim reason is non-empty;
- `management_h05_acceptance.accepted` is false;
- diagnostic reasons name missing artifacts, fields, refs, or semantics;
- the claim is not otherwise promotable.

## Gate Commands

```text
python3 -m compileall -q scripts src tests
python3 -m pytest -q tests/unit tests/integration
python3 scripts/m1h/build_evidence_manifest.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
python3 scripts/m1h/assert_management_exact_scale.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
python3 scripts/m1h/assert_stage_exit.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
```

Expected H05 management gate result path:

```text
runs/m1-hardening/H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING/artifacts/gates/assert_management_exact_scale.json
```

## Critical Review Points

- Do not weaken C07 command validation.
- Do not splice management artifacts across directories unless refs explicitly prove it.
- Do not accept the current P30/P31/P32 files unless schema and semantic checks pass.
- Do not hand-edit `runs/m1-hardening/evidence_manifest.json`; regenerate it.
- Ensure `assert_stage_exit.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING` actually requires the H05 gate result.
