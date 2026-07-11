role: design
agent_invocation: real_subagent
stage_id: H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
source_commit_before: 8f6b557f416ccc2941009ea9b5e4a0c3eaeb7bc4
source_commit_after: MISSING

# H05 Design: Management Matrix Exact-Scale Hardening

## Inputs Read

- `codex_goal_loop_m1_hardening_v2/prompts/DESIGN_SUBAGENT_PROMPT.md`
- `codex_goal_loop_m1_hardening_v2/AGENTS_M1H_V2.md`
- `codex_goal_loop_m1_hardening_v2/START_HERE.md`
- Core docs from `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md`, with H05-relevant emphasis on docs 02, 03, 04, 09, 10, 17, and 18.
- `codex_goal_loop_m1_hardening_v2/stages/H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING.md`
- `codex_goal_loop_m1_hardening_v2/docs/10_ACCEPTANCE_MATRIX.md`
- `codex_goal_loop_m1_hardening_v2/docs/17_COMMANDS_AND_GATES.md`
- `codex_goal_loop_m1_hardening_v2/docs/18_STAGE_EXIT_CONTRACT.md`
- `runs/m1-hardening/H04_COMMAND_AUDIT_REAL_PATH_HARDENING/handoff/NEXT_STAGE_INPUT.md`
- `runs/m1-hardening/H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING/handoff/CONTEXT_RELOAD.md`
- Current H05-related code and evidence surfaces: `scripts/m1h/assert_management_exact_scale.py`, `scripts/m1h/manifest.py`, `scripts/m1h/capability_gate.py`, `scripts/m1h/assert_stage_exit.py`, schemas under `schemas/artifact/management_*`, and representative P30/P31/P32 management artifacts.

## Current State

H05 enters from commit `8f6b557f416ccc2941009ea9b5e4a0c3eaeb7bc4`. The current manifest records `management_matrix.real_exact.{50,100,200}` as `BLOCKED_WITH_REASON`. That is directionally correct, but H05 still needs executable semantics that distinguish honest blocked claims from unsafe PASS claims.

Observed implementation risks:

- `assert_management_exact_scale.py` is a generic capability wrapper. It does not encode H05-specific management matrix semantics and will not by itself validate command-ref, topology-ref, workload-impact, and operation-result consistency.
- `scripts/m1h/manifest.py` references `evaluate_management_matrix_claim(...)`; the worker should ensure this function exists, is covered by tests, and feeds `diagnostics.management_h05_acceptance`.
- `assert_stage_exit.py` currently lists stage-specific gates only through H04. H05 must be added so `assert_stage_exit.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING` requires the H05 management gate artifact.
- The existing P30/P31/P32 artifacts include management matrix files, but current sample shape is not the full schema in `management_ops_matrix.schema.json` and must not pass merely because files are non-empty or because historical Valkey evidence exists.

## Required Claim Model

The manifest must continue to create exactly these required management claims:

- `management_matrix.real_exact.50`
- `management_matrix.real_exact.100`
- `management_matrix.real_exact.200`

Each claim must be either:

- `PASS` with `evidence_kind` in `REAL_EXACT_SCALE` or explicitly justified `M1_FORMAT_RECONSTRUCTED_FROM_REAL_RAW`, all H05 semantic checks true, and `diagnostics.management_h05_acceptance.accepted: true`; or
- `BLOCKED_WITH_REASON` with a non-empty reason, the exact missing fields/artifacts named in diagnostics, and no unsafe promotion to milestone PASS.

The H05 gate itself should exit 0 when all three claims are honest blocked claims or safe PASS claims. It should exit 1 for malformed blocked claims, unsafe PASS claims, fixture-only promotion, legacy-only promotion, cross-directory artifact splicing, or missing diagnostics. This matches the H04 pattern: hardening-loop PASS can prove fail-closed behavior even while milestone claims remain blocked.

## Exact Bundle Selection

Management evaluation should be bundle-based, not file-by-file across unrelated directories.

For each scale, group candidate artifacts by parent run directory. A promotable bundle must contain non-fixture, same-directory artifacts:

- `management_ops_matrix.json`
- `management_operation_results.jsonl`
- `management_topology_snapshots.jsonl`
- `management_workload_impact.json`
- `workload_windows.json`
- `management_command_log.jsonl`
- `valkey_e2e_evidence.json`

Do not combine a P30/P31/P32 matrix with a command log from another phase unless a row explicitly references that external path and the resolver verifies it. Historical full-flow files may inform diagnostics, but they must not silently complete a management claim.

## H05 Semantic Checks

The manifest should populate these checks for `management_matrix` and the gate should require them for PASS:

- `real_valkey_verified`: `valkey_e2e_evidence.json` has `status: PASS` and `real_valkey: true`.
- `exact_scale_observed`: `nodes_observed` equals the required scale exactly, not merely greater than or near it.
- `valkey_9_1_verified`: at least one reported Valkey version starts with `9.1.`.
- `management_matrix_present`: matrix artifact exists, is non-fixture, readable JSON, and schema-valid.
- `management_matrix_status_pass`: matrix status is `PASS`.
- `management_required_operations_present`: all 11 required operations are present: `create_cluster`, `meet_nodes`, `add_replica`, `remove_replica`, `remove_primary_drained_or_safe_replaced`, `remove_failed_node`, `reshard_slot_range`, `reshard_with_keys`, `rebalance_after_imbalance`, `rolling_restart_replica_first`, and `rolling_restart_primary_safe`.
- `operation_results_present`: result JSONL exists, is non-empty, schema-valid per row, and has one PASS row for every required operation.
- `operation_results_exact_scale`: every matrix row and result row has `scale == node_count == required scale`; phase/run/scenario identifiers are consistent within the bundle.
- `operation_semantics_present`: each operation row has numeric timing/convergence/error telemetry and operation-specific proof.
- `topology_refs_resolve`: before/after snapshot refs and topology diff refs resolve, snapshots have exact node count, slot assignment remains complete, `cluster_state` is `ok`, and no fail/pfail state remains after PASS.
- `workload_telemetry_present`: workload impact and workload windows exist, are schema-valid, status PASS where applicable, and contain numeric QPS, latency, timeout, redirection, and error metrics.
- `workload_refs_resolve`: every management operation has baseline, pre-event, event, recovery, post-recovery, and all-run window refs that resolve to numeric workload windows.
- `command_refs_resolve`: every operation has non-empty command refs resolving to command log rows; `command_count` matches resolved refs; command rows validate with C07 command-row semantics; referenced rows match the operation id and have output refs/hashes.
- `no_fixture_management_artifacts`: no source artifact used for PASS lives under `tests/fixtures`.

For real PASS, core fields must be numeric. `MISSING` may remain only for non-core values such as unavailable byte counts, and only when encoded as a structured object with field, reason, and impact. `SKIPPED_WITH_REASON` must not satisfy a required operation, command ref, workload metric, topology ref, or core timing/error metric.

## Operation-Specific PASS Rules

The generic checks above should be extended with operation-sensitive assertions:

- `create_cluster`: exact node count established, all slots assigned, primary/replica counts coherent, cluster state ok.
- `meet_nodes`: known node count reaches exact scale and remains stable after convergence.
- `add_replica`: replica count and replication relationships are observed.
- `remove_replica`, `remove_primary_drained_or_safe_replaced`, `remove_failed_node`: evidence must show the removal action and subsequent stable cluster state; no PASS from a no-op row.
- `reshard_slot_range`: moved slot count is positive, source and target ownership changes are proven, slot coverage remains complete.
- `reshard_with_keys`: moved key count is positive, moved keys are readable, target ownership is proven, and post-move write/read checks pass.
- `rebalance_after_imbalance`: imbalance after is less than or equal to imbalance before, with complete slot coverage and no cluster errors.
- `rolling_restart_replica_first` and `rolling_restart_primary_safe`: restart plan/results are present, every step converges, and final cluster state is ok with exact known nodes.

If an operation cannot prove these semantics from current artifacts, the claim must remain `BLOCKED_WITH_REASON` with the exact missing proof named.

## Command Reference Design

Reuse C07 parsing and row validation helpers rather than creating a weaker path. H05 should additionally enforce management-specific traceability:

- `management_command_log.jsonl` must be non-empty for any management PASS.
- Each matrix/result `command_log_refs` item must resolve to a command id in the selected command log. Accept a strict fragment form such as `management_command_log.jsonl#cmd-000123`; if backward-compatible bare ids are supported, they should resolve only within the same selected bundle.
- Referenced command rows must have `operation_id` equal to the operation row and must not contain placeholder argv tokens.
- Command output files must exist under the repo and hashes must verify.
- Retry, failure, and timeout counts in operation rows must match referenced command rows.

An empty legacy `management_command_log.jsonl` invalidates a management PASS even if other artifacts are present.

## Gate Implementation

Replace the generic wrapper behavior for `scripts/m1h/assert_management_exact_scale.py` with a H05-specific evaluator, modeled after `assert_command_audit_real.py`.

Expected behavior:

- Read `runs/m1-hardening/evidence_manifest.json`.
- For scales 50, 100, and 200, require the claim to exist.
- For `PASS` claims, require promotable evidence kind, all H05 semantic checks true, `diagnostics.management_h05_acceptance.accepted: true`, no fixture paths, no legacy-only sources, all required management artifacts cited, and no missing core metric.
- For `BLOCKED_WITH_REASON` claims, require a non-empty reason plus `diagnostics.management_h05_acceptance.accepted: false` and non-empty diagnostic reasons. Also ensure the claim is not blocked while all PASS semantics are true.
- Write `runs/m1-hardening/H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING/artifacts/gates/assert_management_exact_scale.json`.
- Set the gate result `status` to `PASS` when all checked claims are either safe PASS or honest blocked. Put the milestone-facing state in an extra field such as `management_claim_status: PASS|BLOCKED_WITH_REASON`.
- Set gate result `status` to `FAIL` if any unsafe PASS, vague blocked claim, missing claim, or malformed diagnostics are found.

The gate artifact should include:

- `checked_claim_count: 3`
- `passed_claims`
- `blocked_claims` with scale, claim id, reason, and first diagnostic reasons
- `required_operations`
- `required_artifact_names`
- `semantic_checks_required`

## Manifest Builder Changes

Implement `evaluate_management_matrix_claim(root, scale, paths, evidence)` in `scripts/m1h/manifest.py`.

Design shape:

- choose best candidate bundle by number of true checks, preferring non-fixture same-directory bundles;
- validate JSON schemas using the existing lightweight schema validator;
- parse JSONL strictly and report line-level reasons;
- build indexes for operation results, snapshots, workload windows, workload impact operations, and command rows;
- add `management_h05_acceptance` diagnostics before `semantic_checks` are flattened into the claim;
- update `_evidence_kind` so management claims become `REAL_EXACT_SCALE` only when H05 diagnostics are accepted;
- update `_blocked_reason` so management blocked reasons include the H05 diagnostics.

Do not hand-edit `runs/m1-hardening/evidence_manifest.json`; regenerate it through `build_evidence_manifest.py`.

## Stage Exit Changes

Update `scripts/m1h/assert_stage_exit.py` so H05 requires these gate results:

- `build_evidence_manifest`
- `assert_evidence_taxonomy`
- `assert_management_exact_scale`
- `assert_no_fixture_fallback`
- `assert_no_legacy_m1_pass`
- `assert_no_simulated_subagents`

The final stage exit command remains:

```text
python3 scripts/m1h/assert_stage_exit.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
```

## Required Commands

Run and capture gate result JSON for:

```text
python3 scripts/m1h/build_evidence_manifest.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
python3 scripts/m1h/assert_management_exact_scale.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
python3 scripts/m1h/assert_stage_exit.py --stage H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING
```

Also run common non-JSON commands:

```text
python3 -m compileall -q scripts src tests
python3 -m pytest -q tests/unit tests/integration
```

## Test Plan

Add focused tests for:

- PASS claims with fixture management artifacts fail.
- PASS claims with legacy Valkey evidence but missing M1 management artifacts fail.
- PASS claims with missing command refs, empty command log, unresolved topology refs, or weak workload windows fail.
- Honest `BLOCKED_WITH_REASON` management claims with H05 diagnostics make `assert_management_exact_scale.py` exit 0 and write a PASS gate result.
- Missing diagnostics on blocked claims fail.
- `assert_stage_exit.py` requires the H05 management gate artifact.
- Manifest generation records H05 diagnostics for all 50/100/200 management claims.

## Worker Notes

Keep changes narrowly scoped to the H05 gate family, manifest evaluation, stage-exit requirements, and tests. Do not weaken C07 command validation to make current artifacts pass. It is acceptable, and likely expected, for current 50/100/200 management claims to remain blocked if current artifacts lack full M1-format matrix fields or command traceability.
