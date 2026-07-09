role: worker
agent_invocation: real_subagent
stage_id: H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
source_commit_before: 8f6b557f416ccc2941009ea9b5e4a0c3eaeb7bc4
source_commit_after: MISSING

# H05 Worker Notes

Worker result: RISKS_REMAIN

## Sources Read

- `codex_goal_loop_m1_hardening_v2/prompts/WORKER_SUBAGENT_PROMPT.md`
- `codex_goal_loop_m1_hardening_v2/AGENTS_M1H_V2.md`
- `codex_goal_loop_m1_hardening_v2/stages/H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING.md`
- `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md` through `19_FINAL_HANDOFF_CONTRACT.md`
- Relevant contracts: `C04_EXACT_SCALE_REQUIREMENTS.md`, `C07_COMMAND_AUDIT_CONTRACT.md`, `C12_NO_SIMULATED_SUBAGENT_CONTRACT.md`
- `runs/m1-hardening/H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING/handoff/CONTEXT_RELOAD.md`
- `runs/m1-hardening/H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING/handoff/DESIGN_BRIEF.md`
- Current uncommitted diffs in `scripts/m1h/manifest.py`, `scripts/m1h/assert_management_exact_scale.py`, `scripts/m1h/assert_stage_exit.py`, `tests/m1h/test_gate_framework.py`, and `runs/m1-hardening/evidence_manifest.json`

## Checks Run

- `PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider tests/m1h/test_gate_framework.py -k 'management_matrix or h05_stage_exit'`
  - Result: 5 passed, 40 deselected.
- Read-only gate artifact summary under `runs/m1-hardening/H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING/artifacts/gates/`
  - Existing gate artifacts are PASS.
  - `assert_management_exact_scale.json` has PASS with 3 blocked management claims.
- Read-only `validate_stage_exit(...)`
  - Violations: 0.
  - Blocked: worker artifact, review artifact, worker summary, and review handoff were missing before this worker wrote its owned files.

## Current Evidence State

The current manifest honestly keeps:

- `management_matrix.real_exact.50`: `BLOCKED_WITH_REASON`, `LEGACY_EVIDENCE_ONLY`, H05 accepted false.
- `management_matrix.real_exact.100`: `BLOCKED_WITH_REASON`, `LEGACY_EVIDENCE_ONLY`, H05 accepted false.
- `management_matrix.real_exact.200`: `BLOCKED_WITH_REASON`, `LEGACY_EVIDENCE_ONLY`, H05 accepted false.

The blocking reason currently centers on file-level `management_command_log.jsonl` refs rather than command-id fragments. This is a good fail-closed direction for the existing repository artifacts.

## Remaining H05 Risks

Risk 1: Management command rows are not validated to C07 strength before H05 PASS.

`scripts/m1h/manifest.py` parses `management_command_log.jsonl` with `_read_command_jsonl_strict`, but `_management_command_ref_reasons` only checks that referenced command ids exist. It does not apply `_command_row_reasons`, `_output_hash_reasons`, `_placeholder_command_reasons`, or operation-id matching to management rows. The new positive test fixture can PASS with command rows that omit most C07 fields and output hashes. This conflicts with the H05 design brief and `C07_COMMAND_AUDIT_CONTRACT.md`.

Risk 2: Topology refs only prove labels, not topology semantics.

`_management_topology_ref_reasons` accepts a topology snapshot if the referenced label exists. It does not require exact known node count, complete slots, `cluster_state: ok`, role data, or absence of fail/pfail residue. The positive test uses empty `nodes: []` snapshots and still expects PASS.

Risk 3: Workload impact refs only prove references, not QPS/latency/error impact telemetry.

`_management_workload_reasons` requires `management_workload_impact.json` status PASS and resolvable `workload_windows` ids. It does not require numeric QPS, latency, timeout, redirection, or error metrics for the fault-period/operation-period impact contract. The positive test uses window status only.

Risk 4: Operation results do not enforce exact known node counts.

`_management_result_reasons` requires `cluster_known_nodes_before` and `cluster_known_nodes_after` fields, but does not compare them to the exact scale. A result row with present but wrong known-node values can still satisfy `operation_semantics_present`.

Risk 5: The H05 gate can PASS honest blocked claims, but its unsafe-PASS detection inherits the manifest's weak semantics.

`assert_management_exact_scale.py` correctly rejects non-promotable kinds, fixture sources, and failed manifest checks. However, if the manifest promotes a weak bundle to `REAL_EXACT_SCALE`, the gate does not independently re-open source artifacts to catch weak command/topology/workload semantics.

## Suggested Fix Scope

- Reuse existing C07 row validators for `management_command_log.jsonl` in H05 management evaluation, including output-hash checks and placeholder command rejection.
- Require command refs to match command rows for the same `operation_id`.
- Strengthen topology snapshot validation to require exact-scale node evidence, slot coverage, ok cluster state, and no fail/pfail markers.
- Strengthen workload validation to require numeric QPS, latency, timeout/redirection/error fields in each referenced operation window.
- Add negative tests for each weak PASS case above so the positive fixture cannot remain a minimal shell.

