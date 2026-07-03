# DESIGN_BRIEF - P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER

## Fresh read confirmation

Read directly for this design:

- `AGENTS.md`
- `CODEX_STRICT_MATRIX_LOOP_START.md`
- `docs/codex/goal-loop-strict/prompts/DESIGN_SUBAGENT_PROMPT.md`
- `docs/codex/goal-loop-strict/templates/STAGE_DESIGN_TEMPLATE.md`
- `docs/codex/goal-loop-strict/00_INDEX.md`
- `docs/codex/goal-loop-strict/01_STRICT_GOAL_CONTRACT.md`
- `docs/codex/goal-loop-strict/02_STRICT_STAGE_MANIFEST.md`
- `docs/codex/goal-loop-strict/03_MAIN_SUBAGENT_LOOP_PROTOCOL.md`
- `docs/codex/goal-loop-strict/04_CONTEXT_LEDGER_PROTOCOL.md`
- `docs/codex/goal-loop-strict/05_FAIL_CLOSED_HARNESS_CONTRACT.md`
- `docs/codex/goal-loop-strict/06_COVERAGE_REGISTRY_SPEC.md`
- `docs/codex/goal-loop-strict/07_QUANTIFICATION_DATA_CONTRACT.md`
- `docs/codex/goal-loop-strict/08_MANAGEMENT_OPERATION_MATRIX_SPEC.md`
- `docs/codex/goal-loop-strict/09_FAULT_FAILOVER_MATRIX_SPEC.md`
- `docs/codex/goal-loop-strict/10_SCALE_EXECUTION_POLICY.md`
- `docs/codex/goal-loop-strict/11_ANALYSIS_VISUAL_REPORT_SPEC.md`
- `docs/codex/goal-loop-strict/12_AUDIT_COMMIT_NO_BYPASS_POLICY.md`
- `docs/codex/goal-loop-strict/stages/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER.md`
- `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md`
- `artifacts/goal_loop_strict/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER/CONTEXT_RELOAD.md`

## Stage objective

P28 must create the canonical strict coverage matrix and deterministic scenario plans for later strict stages. It must not execute Docker, live Valkey, workload clients, network faults, or >200 real runtime work. The registry is the scope ledger; later stages update coverage status only when their own evidence exists.

P28 pass criteria:

- Generate `artifacts/coverage/strict_coverage_registry.json`.
- Generate `artifacts/coverage/strict_required_matrix.csv`.
- Generate `artifacts/coverage/strict_scenario_plan.json`.
- Generate `artifacts/phases/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER/coverage_registry_report.json`.
- Generate `artifacts/phases/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER/phase_summary.json`.
- Generate `artifacts/phases/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER/quant_summary.json`.
- Enforce all required lifecycle, management, fault, and >200 dry-run coverage cells.
- Keep all real 50/100/200 rows at `status=PENDING`.
- Keep all >200 rows at `execution_mode=dry_run` and initial `status=PENDING` until P37 supplies no-runtime proof.
- Provide fail-closed `assert_coverage_registry.py --registry artifacts/coverage/strict_coverage_registry.json --require-all` support.

## Current repository findings

- `codex/phase_manifest.json` contains P28 with common strict gates and a `coverage_registry` gate, but the command is currently `python3 scripts/assert_coverage_registry.py --phase P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER`. The P28 stage document requires `python3 scripts/assert_coverage_registry.py --registry artifacts/coverage/strict_coverage_registry.json --require-all`.
- `scripts/assert_coverage_registry.py` is still bootstrap-light. It lacks a `--registry` argument, uses a hard-coded registry path, does not enforce complete required row counts, does not validate ID determinism, and does not validate status transitions beyond a few local checks.
- `schemas/artifact/strict_coverage_registry.schema.json` exists but is permissive. It does not require `status_reason` or `commit_sha`, does not constrain deterministic coverage ID format, and allows additional properties broadly.
- No `artifacts/coverage/` directory exists yet.
- No `artifacts/phases/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER/` directory exists yet.
- Existing config templates include `templates/configs/scale_50.yaml`, `templates/configs/scale_100.yaml`, `templates/configs/scale_200.yaml`, and `templates/configs/scale_1000_dryrun_optin.yaml`.
- `templates/configs/scale_200.yaml` still references `scale_profile.bounded_exception_phase: P21_FAILOVER_LATENCY_CURVE_200`; the scenario compiler can reference this config path but should not claim that the config is already strict-stage clean. Mark this as `待验证` for worker/review.
- `scripts/codex_gate.py` validates manifest gates, required phase artifacts, strict handoffs, review, audit, and gate log checksums. P28 global artifacts under `artifacts/coverage/` are not currently manifest-required phase artifacts, so the P28 coverage gate must independently assert them unless the worker strengthens manifest/postcheck handling.
- `scripts/assert_strict_stage_contract.py` already requires `CONTEXT_RELOAD.md` and `DESIGN_BRIEF.md` for strict stages.
- `scripts/assert_no_bypass.py` already rejects PASS-only gates, forbidden host-network mutation commands, 200-node downshift patterns, and real execution above 200.
- `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md` says P28 must materialize the strict coverage registry and deterministic scenario plan without claiming runtime coverage.

## Scope boundaries

In scope for P28:

- Canonical required-row definitions for P28 registry generation.
- Deterministic coverage ID generation.
- Deterministic scenario-plan generation for later management, fault, full-flow, and >200 dry-run stages.
- CSV export of the required matrix.
- Registry schema strengthening.
- Coverage registry assertion strengthening.
- Status transition validation helper/CLI behavior.
- P28 phase summaries and coverage registry report.
- Unit/integration tests for generator, schema, assertion behavior, and manifest gate alignment.

Out of scope for P28:

- Running real 50/100/200 clusters.
- Marking any real row `PASS`.
- Marking >200 dry-run rows `DRY_RUN_PASS` before P37 no-runtime proof exists.
- Implementing P29 telemetry collection internals.
- Implementing P30-P36 management/fault/full-flow execution.
- Implementing P37 dry-run runtime inventory proof.
- Building final analysis/report visualizations for P38-P39.

## Implementation plan

1. Add a deterministic generator script, likely `scripts/build_strict_coverage_registry.py`.
   - Define constants from the strict specs:
     - real scales: `50`, `100`, `200`
     - dry-run targets: `201`, `250`, `300`, `500`, `1000`
     - lifecycle rows: `config_validate`, `resource_preflight`, `plan_cluster`, `create_cluster`, `meet_nodes`, `assign_slots`, `add_replica`, `baseline_workload`, `telemetry_collect`, `analysis_build`, `report_render`, `cleanup_verify`
     - management rows from `08_MANAGEMENT_OPERATION_MATRIX_SPEC.md`
     - fault rows from `09_FAULT_FAILOVER_MATRIX_SPEC.md`
     - dry-run rows from `06_COVERAGE_REGISTRY_SPEC.md`
   - Emit stable sorted rows by scale group, category order, and row order.
   - Use deterministic IDs exactly as `<scale>.<category>.<row_name>`, including examples such as `50.management.remove_replica`, `100.fault.network_delay`, `200.lifecycle.cleanup_verify`, and `500.dry_run.no_runtime_created_proof`.
   - Set real rows:
     - `execution_mode=real`
     - `status=PENDING`
     - `status_reason=Awaiting exact-scale real evidence from <stage_owner>`
     - empty `source_artifacts`, `validation_artifacts`, `metric_refs`
     - empty `cleanup_ref`, `review_ref`, `commit_sha`
   - Set >200 rows:
     - `execution_mode=dry_run`
     - `status=PENDING`
     - `status_reason=Awaiting P37 dry-run no-runtime proof`
     - no runtime artifact claims
   - Add provenance fields such as `registry_generated_by`, `source_spec_refs`, and `generated_at` while keeping deterministic content where feasible. If timestamps are included, record them but keep row ordering and IDs deterministic.

2. Compile scenario plans in the same script or a small helper module.
   - Emit `strict_scenario_plan.json` with sections:
     - `management_matrix` for 50/100/200, owned by P30/P31/P32.
     - `fault_failover_matrix` for 50/100/200, owned by P33/P34/P35.
     - `full_flow_e2e` for 50/100/200, owned by P36.
     - `dry_run_200_plus` for 201/250/300/500/1000, owned by P37.
   - Each scenario entry should include:
     - `scenario_id`
     - `stage_owner`
     - `node_count`
     - `execution_mode`
     - `config_path` or generated config artifact target
     - `resource_preflight_required`
     - `workload_profile`
     - `operation_sequence` or `fault_sequence`
     - `timeout_policy`
     - `cleanup_policy`
     - `expected_artifacts`
     - `coverage_ids`
     - `safety_constraints`
   - Use existing config paths for real 50/100/200: `templates/configs/scale_50.yaml`, `templates/configs/scale_100.yaml`, `templates/configs/scale_200.yaml`.
   - Use dry-run generated config/artifact targets for >200, not live config execution.

3. Export `strict_required_matrix.csv`.
   - Fixed column order:
     `coverage_id,scale,node_count,category,row_name,stage_owner,required,execution_mode,status,status_reason,source_artifacts,validation_artifacts,metric_refs,cleanup_ref,review_ref,commit_sha`
   - Encode arrays deterministically, preferably as `;`-joined strings or compact JSON strings with stable order.

4. Emit P28 phase artifacts.
   - `coverage_registry_report.json` should summarize:
     - total row count
     - counts by scale/category/stage_owner/status/execution_mode
     - expected row counts
     - generated artifact paths
     - schema validation status
     - no-real-runtime assertion
     - no >200 runtime assertion
     - coverage IDs sampled or listed by family
   - `phase_summary.json` should be `status=PASS` only after generation and assertion succeed. Runtime metrics should be listed under `missing_metrics` as `SKIPPED_WITH_REASON` with reasons because P28 is registry-only.
   - `quant_summary.json` should be `status=SKIPPED_WITH_REASON` or `PASS` only if the schema and local convention accept it; in either case `runtime_claims.real_valkey_claimed=false`, `management_runtime_claimed=false`, and `fault_runtime_claimed=false`.

5. Strengthen `scripts/assert_coverage_registry.py`.
   - Add `--registry` path support while keeping `--bootstrap-only`.
   - Add `--scenario-plan` and `--matrix-csv` optional args, defaulting to P28 artifact paths.
   - Add `--require-all` to enforce all 145 required P28 rows:
     - 36 real lifecycle rows
     - 33 real management rows
     - 36 real fault rows
     - 40 >200 dry-run rows
   - Add `--phase`, `--scale`, `--scales`, and `--category` filtering for later stages while still validating global registry shape first.
   - Add `--require-final-real-scales` for P38/P40 style checks:
     - all 50/100/200 real required rows must be `PASS`
     - no required real row may be `PENDING`, `MISSING`, `DRY_RUN_PASS`, `BLOCKED`, or `FAIL`
   - Add `--require-dry-run-200-plus` if P40 stage docs require it:
     - all >200 rows must be `DRY_RUN_PASS`
     - validation artifacts must include no-runtime-created proof
     - no >200 row may have `execution_mode=real`
   - Fail closed on duplicate IDs, malformed IDs, wrong node counts, wrong stage owners, missing fields, nulls, empty status reasons, real rows initially `PASS` without evidence, dry-run rows with `PASS`, and source/validation refs pointing outside the repository.

6. Implement status transition validation.
   - Either add a dedicated script such as `scripts/validate_strict_coverage_transition.py` or implement a mode in `assert_coverage_registry.py`, for example `--previous <path> --updated <path>`.
   - Allowed transitions:
     - real: `PENDING -> PASS|FAIL|BLOCKED|MISSING`
     - dry-run: `PENDING -> DRY_RUN_PASS|FAIL|BLOCKED|MISSING`
     - failed/blocked/missing rows may transition to a pass state only with new validation artifacts and review refs
     - pass states cannot silently regress without a reason
   - Forbidden transitions:
     - real row to `DRY_RUN_PASS`
     - dry-run row to `PASS`
     - any row to `PASS` without source and validation artifacts
     - any row to final status with missing `review_ref` when a later stage claims completion
     - any transition that changes `coverage_id`, `scale`, `node_count`, `category`, `row_name`, `stage_owner`, `required`, or `execution_mode`

7. Align P28 manifest gate support.
   - Update P28 gates in `codex/phase_manifest.json` so generation runs before assertion, for example:
     - `coverage_registry_generate`: `python3 scripts/build_strict_coverage_registry.py --out-dir artifacts/coverage --phase P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER`
     - `coverage_registry`: `python3 scripts/assert_coverage_registry.py --registry artifacts/coverage/strict_coverage_registry.json --require-all`
   - Keep common gates intact.
   - Consider adding P28 required artifacts for the phase-local report/schema only. If adding global `artifacts/coverage/*` as manifest-required artifacts, first strengthen `scripts/codex_gate.py` to allow explicit `artifacts/coverage/` global artifacts for strict registry stages, then update tests and lock. Otherwise rely on the coverage registry gate to validate global artifacts.

8. Update locked harness hashes transparently if locked files change.
   - Likely locked changes: `codex/phase_manifest.json`, `scripts/assert_coverage_registry.py`, `schemas/artifact/strict_coverage_registry.schema.json`, and possibly `scripts/codex_gate.py`.
   - Because `codex/gate_lock.json` is a harness control, update hashes only for intentional strengthening changes and cite the reason in `WORKER_SUMMARY.md`, `REVIEW.md`, and audit files. If the main agent treats this as a harness defect under `AGENTS.md`, also write `artifacts/harness_exception/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER.md`.

## Harness plan

- Keep P28 non-runtime: `real_valkey_required=false`, `max_nodes=0`, no Docker commands, no Valkey probes, no fault commands.
- Add the generator gate before the registry assertion gate in the P28 manifest.
- Strengthen the registry assertion so `--require-all` validates the global artifacts regardless of whether postcheck sees them as phase artifacts.
- Ensure `assert_no_bypass.py` still passes:
  - no `echo PASS`
  - no `printf PASS`
  - no `sudo`
  - no host network mutation tokens
  - no real execution above 200
- Ensure `assert_strict_stage_contract.py` still passes for P28 and all strict stages.
- The worker should not run `mark-complete`, commit, or push; main handles those after review and postcheck.

## Schema and artifact plan

Likely schema changes:

- Update `schemas/artifact/strict_coverage_registry.schema.json`.
  - Require top-level metadata: `schema_version`, `artifact_type`, `stage_id`, `created_at`, `producer`, `source_spec_refs`, `summary`, `rows`.
  - Require per-row fields from the strict spec: `coverage_id`, `scale`, `node_count`, `category`, `row_name`, `stage_owner`, `required`, `execution_mode`, `status`, `status_reason`, `source_artifacts`, `validation_artifacts`, `metric_refs`, `cleanup_ref`, `review_ref`, `commit_sha`.
  - Restrict statuses to `PENDING`, `PASS`, `FAIL`, `BLOCKED`, `DRY_RUN_PASS`, `MISSING`.
  - Restrict `execution_mode` to `real` or `dry_run`.
  - Add a practical coverage ID regex covering numeric scales and deterministic row names.

- Add `schemas/artifact/strict_scenario_plan.schema.json`.
  - Require `schema_version`, `artifact_type=strict_scenario_plan`, `stage_id`, `created_at`, `producer`, `scenarios`.
  - Require scenario fields listed in the P28 stage contract.
  - Forbid `execution_mode=real` when `node_count > 200`.

- Optional but recommended: add `schemas/artifact/strict_coverage_registry_report.schema.json`.
  - Stronger than `strict_generic_report.schema.json` for `coverage_registry_report.json`.
  - Require row counts, expected counts, generated artifacts, validation results, and runtime claim booleans.

Required generated artifacts:

- `artifacts/coverage/strict_coverage_registry.json`
- `artifacts/coverage/strict_required_matrix.csv`
- `artifacts/coverage/strict_scenario_plan.json`
- `artifacts/phases/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER/coverage_registry_report.json`
- `artifacts/phases/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER/phase_summary.json`
- `artifacts/phases/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER/quant_summary.json`

## Coverage IDs targeted

P28 targets creation and validation of all required IDs, but does not satisfy runtime coverage.

Expected required row totals:

- Real lifecycle: 3 scales x 12 rows = 36.
- Real management: 3 scales x 11 rows = 33.
- Real fault: 3 scales x 12 rows = 36.
- >200 dry-run: 5 targets x 8 rows = 40.
- Total: 145 rows.

Real lifecycle ID families:

- `50.lifecycle.config_validate` through `50.lifecycle.cleanup_verify`
- `100.lifecycle.config_validate` through `100.lifecycle.cleanup_verify`
- `200.lifecycle.config_validate` through `200.lifecycle.cleanup_verify`

Real management ID families:

- `50.management.create_cluster`
- `50.management.meet_nodes`
- `50.management.add_replica`
- `50.management.remove_replica`
- `50.management.remove_primary_drained_or_safe_replaced`
- `50.management.remove_failed_node`
- `50.management.reshard_slot_range`
- `50.management.reshard_with_keys`
- `50.management.rebalance_after_imbalance`
- `50.management.rolling_restart_replica_first`
- `50.management.rolling_restart_primary_safe`
- Same row names for `100.management.*` and `200.management.*`.

Real fault ID families:

- `50.fault.primary_stop_failover`
- `50.fault.replica_stop`
- `50.fault.node_host_stop`
- `50.fault.az_stop`
- `50.fault.network_delay`
- `50.fault.network_loss`
- `50.fault.network_flap`
- `50.fault.network_partition`
- `50.fault.minority_partition`
- `50.fault.majority_partition`
- `50.fault.split_brain_window_detection`
- `50.fault.fault_period_workload_impact`
- Same row names for `100.fault.*` and `200.fault.*`.

Dry-run ID families:

- `201.dry_run.config_validate_dry_run`
- `201.dry_run.resource_preflight_dry_run`
- `201.dry_run.plan_cluster_dry_run`
- `201.dry_run.placement_schedule_dry_run`
- `201.dry_run.port_directory_collision_check_dry_run`
- `201.dry_run.artifact_schema_projection_dry_run`
- `201.dry_run.no_runtime_created_proof`
- `201.dry_run.report_projection_dry_run`
- Same row names for `250.dry_run.*`, `300.dry_run.*`, `500.dry_run.*`, and `1000.dry_run.*`.

Stage owner mapping:

- Management 50/100/200 rows: P30/P31/P32.
- Fault 50/100/200 rows: P33/P34/P35.
- Full-flow lifecycle rows at 50/100/200: P36, with telemetry/analysis/report/cleanup lifecycle sub-rows also referenced by P29/P38/P39/P40 in scenario metadata where appropriate.
- >200 dry-run rows: P37.
- Final verification/final pass checks: P38/P39/P40 consume registry status but should not own initial row creation.

## Test and gate plan

Focused development commands:

```bash
python3 scripts/build_strict_coverage_registry.py --out-dir artifacts/coverage --phase P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER
python3 scripts/assert_coverage_registry.py --registry artifacts/coverage/strict_coverage_registry.json --require-all
python3 scripts/validate_json_schema.py --schema schemas/artifact/strict_coverage_registry.schema.json --instance artifacts/coverage/strict_coverage_registry.json
python3 scripts/validate_json_schema.py --schema schemas/artifact/strict_scenario_plan.schema.json --instance artifacts/coverage/strict_scenario_plan.json
python3 scripts/validate_json_schema.py --schema schemas/artifact/phase_summary.schema.json --instance artifacts/phases/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER/phase_summary.json
python3 scripts/validate_json_schema.py --schema schemas/artifact/quant_summary.schema.json --instance artifacts/phases/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER/quant_summary.json
```

Unit/integration tests to add or update:

- `tests/unit/test_strict_coverage_registry.py`
  - generator emits exactly 145 rows
  - all IDs deterministic and unique
  - real rows start `PENDING`
  - >200 rows use `execution_mode=dry_run`
  - no row above 200 uses `execution_mode=real`
  - CSV row count matches registry row count
  - scenario plan maps every row to at least one later-stage scenario
  - transition validation rejects real `DRY_RUN_PASS`, dry-run `PASS`, `PASS` without evidence, duplicate IDs, and changed immutable fields

- `tests/integration/test_goal_loop_manifest.py`
  - P28 manifest has generator gate before coverage assertion gate
  - P28 coverage assertion command includes `--registry artifacts/coverage/strict_coverage_registry.json --require-all`
  - bootstrap-only coverage assertion still passes

- Existing `tests/unit/test_goal_loop_assertions.py`
  - Add targeted tests for the strengthened assertion, likely using temp registry fixtures to avoid relying only on committed generated artifacts.

Full P28 gate sequence for the main agent after worker implementation:

```bash
python3 scripts/codex_gate.py precheck --phase P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER
python3 scripts/codex_gate.py run --phase P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER
python3 scripts/assert_coverage_registry.py --registry artifacts/coverage/strict_coverage_registry.json --require-all
python3 scripts/assert_strict_stage_contract.py --phase P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER
python3 scripts/assert_no_bypass.py --phase P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER
```

After worker summary and review pass, main should run:

```bash
python3 scripts/codex_gate.py postcheck --phase P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER
python3 scripts/codex_gate.py mark-complete --phase P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER
```

## Safety constraints

- Do not run Docker or live Valkey for P28.
- Do not start containers, workloads, proxy processes, or network faults.
- Do not mutate host networking, firewall, routes, interfaces, PF, nftables, iptables, or OS services.
- Do not use `sudo`.
- Do not mark any real 50/100/200 row as `PASS`.
- Do not mark >200 rows as `DRY_RUN_PASS` until P37 records no-runtime proof.
- Do not permit any >200 row or scenario with `execution_mode=real`.
- Do not use `0`, `null`, empty strings, `NaN`, `Infinity`, or omitted fields as missing evidence placeholders.
- Do not weaken strict gate checks to make generated artifacts pass.
- If locked harness files are changed, update lock hashes only as part of transparent strengthening and prove lock enforcement still works.

## Blocked conditions

P28 must block if any of these occur:

- A required lifecycle, management, fault, or dry-run row cannot be represented with a deterministic coverage ID.
- Registry output is non-deterministic across repeated generation except for explicitly recorded generation timestamps.
- Any real required row starts as `PASS` or `DRY_RUN_PASS`.
- Any >200 row or scenario permits real execution.
- Scenario plans omit resource preflight, workload profile, timeout policy, cleanup policy, expected artifacts, or coverage IDs.
- `assert_coverage_registry.py --registry artifacts/coverage/strict_coverage_registry.json --require-all` cannot fail closed for missing or malformed artifacts.
- Manifest gate commands cannot be aligned without weakening locked harness checks.
- Schema validation would require allowing null or placeholder values for required fields.

## Risks

- Category ambiguity: strict docs list `telemetry`, `analysis`, `report`, and `cleanup` as coverage dimensions, but required row examples place `cleanup_verify` under `lifecycle`. The safer P28 choice is to emit the required `scale.lifecycle.*`, `scale.management.*`, `scale.fault.*`, and `scale.dry_run.*` IDs exactly, then include subdomain metadata for telemetry/analysis/report/cleanup consumers.
- Manifest artifact path policy: `scripts/codex_gate.py` currently requires manifest `required_artifacts` to live under `artifacts/phases/`. If global `artifacts/coverage/*` artifacts are added to manifest required artifacts, `codex_gate.py` must be strengthened deliberately and lock hashes updated.
- `strict_coverage_registry.schema.json` is shared by later `coverage_ledger.json` artifacts. Tightening it too aggressively may force P30-P37 to emit full global registry shape for per-stage ledgers. Consider adding a `registry_kind` or schema shape that supports both full registry and per-stage ledger, or add a separate ledger schema if needed.
- Generated timestamps can create noisy diffs. Prefer stable row content and deterministic ordering; include timestamps only in top-level metadata if existing artifact conventions require them.
- Existing `scale_200.yaml` has older P21 scale profile metadata. P28 should not rewrite runtime config unless necessary, but the scenario report should flag it for P32/P35/P36 verification.

## 待验证

- 待验证: Whether P28 should add `artifacts/coverage/*` to `codex/phase_manifest.json` required artifacts by strengthening `scripts/codex_gate.py`, or leave them enforced solely by the coverage registry gate.
- 待验证: Whether `quant_summary.json` for P28 should use `status=SKIPPED_WITH_REASON` because no runtime quantification is performed, or `status=PASS` because the registry quantification artifact itself was generated. In either case, runtime claim booleans must be false and skipped runtime data must carry reasons.
- 待验证: Whether strict docs expect `analysis_build`, `report_render`, and `cleanup_verify` IDs to remain under `lifecycle` exactly, or whether additional `analysis`, `report`, and `cleanup` category rows should be added. Do not add extra rows unless the worker confirms this will not confuse later `--require-all` totals.
- 待验证: Whether `strict_coverage_registry.schema.json` should remain the schema for both global registry and later per-stage `coverage_ledger.json`, or whether P28 should introduce a separate `strict_coverage_ledger.schema.json`.
- 待验证: Whether P28 should update `templates/configs/scale_200.yaml` metadata from P21 to strict-stage ownership, or leave runtime config cleanup for the exact real 200-node stages.
- 待验证: Whether the current lock update practice requires `artifacts/harness_exception/P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER.md` for any P28 harness file changes, even when those changes are direct stage requirements.
