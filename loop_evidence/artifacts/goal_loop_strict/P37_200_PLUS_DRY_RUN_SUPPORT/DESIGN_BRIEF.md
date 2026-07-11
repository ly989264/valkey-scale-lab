# DESIGN_BRIEF — P37_200_PLUS_DRY_RUN_SUPPORT

## Fresh read confirmation

Read `docs/codex/goal-loop-strict/prompts/DESIGN_SUBAGENT_PROMPT.md` and the required strict docs listed by `docs/codex/goal-loop-strict/00_INDEX.md`, including `AGENTS.md`, `CODEX_START_HERE.md`, `CODEX_GOAL_LOOP_START.md`, `CODEX_STRICT_MATRIX_LOOP_START.md`, all goal-loop core docs, all strict-loop core docs, `docs/codex/goal-loop-strict/stages/P37_200_PLUS_DRY_RUN_SUPPORT.md`, and `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md`.

This design subagent stayed read-only except for writing this brief.

## Stage objective

Implement P37 dry-run-only support above 200 nodes for required targets `201`, `250`, `300`, `500`, and `1000`.

For each target, P37 must prove this sequence without creating runtime resources:

1. config validate
2. resource estimate
3. plan cluster
4. host/AZ placement schedule
5. port/directory collision check
6. artifact schema projection
7. report projection
8. no-runtime-created proof

Every >200 artifact must use `execution_mode=dry_run` and must not claim live Valkey, live endpoints, workloads, or real cluster creation.

## Current repository findings

- `codex/phase_manifest.json` already declares `P37_200_PLUS_DRY_RUN_SUPPORT` as automatic, `real_valkey_required=false`, `max_nodes=0`, `execution_mode=dry_run`, and `dry_run_target_nodes=[201,250,300,500,1000]`.
- P37 manifest gates are:
  - `python3 scripts/codex_gate.py precheck --phase P37_200_PLUS_DRY_RUN_SUPPORT`
  - `python3 scripts/safety_scan.py`
  - `python3 -m compileall -q scripts src`
  - `python3 -m pytest -q tests/unit tests/integration`
  - `python3 scripts/assert_strict_stage_contract.py --phase P37_200_PLUS_DRY_RUN_SUPPORT`
  - `python3 scripts/assert_no_bypass.py --phase P37_200_PLUS_DRY_RUN_SUPPORT`
  - `python3 scripts/assert_200_plus_dry_run.py --phase P37_200_PLUS_DRY_RUN_SUPPORT --min-targets 201,250,300,500,1000`
  - `python3 scripts/assert_coverage_registry.py --phase P37_200_PLUS_DRY_RUN_SUPPORT --category dry_run --require-all`
- `artifacts/coverage/strict_coverage_registry.json` contains 40 P37 dry-run rows, currently `PENDING`, for the five targets and eight required dry-run row names.
- `artifacts/coverage/strict_scenario_plan.json` already contains dry-run scenarios for all five targets and references generated configs under `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/generated_configs/scale_<N>_dry_run.yaml`.
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/` and `artifacts/gates/P37_200_PLUS_DRY_RUN_SUPPORT/` have no files at design time.
- `artifacts/goal_loop_strict/P37_200_PLUS_DRY_RUN_SUPPORT/CONTEXT_RELOAD.md` exists; this brief is the next required handoff.
- `scripts/assert_200_plus_dry_run.py` currently checks only aggregate target presence, `execution_mode=dry_run` in `dry_run_results.jsonl`, target >200, and aggregate `no_runtime_created_proof.json` status/zero runtime. It does not yet verify the full per-target sequence, per-target plan/report artifacts, no endpoint/workload claims, or coverage linkage.
- `scripts/assert_coverage_registry.py` requires dry-run rows to use `DRY_RUN_PASS`, and `--require-all` validates the full 145-row registry plus scenario plan/CSV. With `--phase P37_200_PLUS_DRY_RUN_SUPPORT --category dry_run --require-all`, P37 will fail until all 40 P37 rows are updated from `PENDING` to `DRY_RUN_PASS` with validation artifacts and review refs.
- `schemas/artifact/no_runtime_created_proof.schema.json` exists and requires aggregate `execution_mode=dry_run`, `runtime_resources_created=false`, `before_inventory`, and `after_inventory`.
- `schemas/artifact/strict_generic_report.schema.json` is permissive and is currently used for P37 target/result/resource/placement/report artifacts.
- `src/valkey_scale_lab/config/validation.py` rejects configs above `safety.default_max_nodes=100` unless `safety.allow_1000_nodes=true`; special dry-run validation for 201/250/300/500 is not evident. This is a P37 hotspot.
- `src/valkey_scale_lab/planner/plan.py` supports `--dry-run` and marks plan nodes dry-run, but `validate_semantics` still rejects >100 unless opt-in/exception semantics allow it. It also only explicitly forbids non-dry-run at `node_count >= 1000`, so P37 should strengthen the guard for all `node_count > 200`.
- `src/valkey_scale_lab/resource.py` supports `resource preflight --dry-run`, but uses Docker availability and other runtime checks even for dry-run. P37 should ensure the required artifact is a dry-run resource estimate, not a real-run preflight claim. Whether to reuse this code directly is 待验证.
- `templates/configs/scale_1000_dryrun_optin.yaml` exists for 1000 only. No committed templates for 201/250/300/500 were found.
- `scripts/safety_scan.py` rejects non-1000 template configs above 100 unless they are the existing exact-200 exception, so P37 generated configs should remain under `artifacts/phases/.../generated_configs/`, or the safety scan must be strengthened carefully if any committed template is added.

## Scope boundaries

- In scope: P37 dry-run-only target generation, planning, resource estimates, placement schedules, collision checks, schema/report projections, no-runtime proof, P37 artifacts, P37 coverage ledger/registry transitions, and P37 gates/tests.
- Out of scope: new real Valkey runs, new workload execution, management/fault behavior changes for P30-P36, P38 analysis beyond report projections required by P37, P39 visual rendering, and P40 final audit closeout.
- Do not raise `default_max_nodes` above `100`.
- Do not make P37 a 200-node bounded real exception.
- Do not treat >200 dry-run artifacts as real evidence.

## Implementation plan

1. Add a P37 dry-run artifact generator, preferably `scripts/p37_200_plus_dry_run_artifacts.py`, invoked by a new required manifest gate or by strengthening the existing P37 gate sequence if the worker chooses to update the manifest/gate lock safely.
2. Generate deterministic configs for `201`, `250`, `300`, `500`, and `1000` under `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/generated_configs/scale_<N>_dry_run.yaml`.
3. Add or adjust config validation semantics so these generated configs validate only when all are true:
   - `node_count > 200`
   - `runtime.dry_run=true`
   - `workload.enabled=false`
   - `scale_profile.dry_run_only=true`
   - `scale_profile.p37_dry_run_target=true` or equivalent explicit P37 marker
   - `safety.require_sandbox_network=true`
   - `safety.forbid_host_network_mutation=true`
   - no real runtime opt-in is implied
4. Strengthen planner/resource guards so any `node_count > 200` with `dry_run=false` fails closed, including 201/250/300/500, not only 1000. The dry-run plan should include `runtime.dry_run=true`, `constraints.no_execution=true`, `constraints.dry_run=true`, collision booleans, host/AZ balance data, and deterministic node/port/directory assignments.
5. For each target, run or call the package APIs for validation/plan/resource estimate and write:
   - `config_validation_<N>.json`
   - `resource_estimate_<N>.json`
   - `dry_run_plan_<N>.json`
   - `placement_schedule_<N>.json`
   - `collision_check_<N>.json`
   - `artifact_schema_projection_<N>.json`
   - `report_projection_<N>.json`
   - `no_runtime_created_proof_<N>.json`
6. Record aggregate `no_runtime_created_proof.json` by taking before/after inventory of owned project resources only. At minimum include owned Docker containers, networks, volumes if Docker is available, plus owned runtime directories/state files under deterministic P37 paths. Docker unavailable should be encoded as an inventory collection status with reason, not as runtime proof failure, as long as no runtime creation is attempted. 待验证: current gate expectations around Docker inventory when Docker is absent.
7. Write the required aggregate artifacts:
   - `phase_summary.json`
   - `dry_run_targets.json`
   - `dry_run_results.jsonl`
   - `resource_estimates.json`
   - `placement_schedules.json`
   - `no_runtime_created_proof.json`
   - `report_projection_index.json`
   - `coverage_ledger.json`
   - `quant_summary.json`
8. Update `artifacts/coverage/strict_coverage_registry.json` and `artifacts/coverage/strict_required_matrix.csv` only for P37 rows, preserving row order and immutable fields. Set each P37 row to `DRY_RUN_PASS` with validation artifacts including no-runtime proof, source/report artifacts as dry-run projections, `review_ref=artifacts/goal_loop_strict/P37_200_PLUS_DRY_RUN_SUPPORT/REVIEW.md`, and `commit_sha` as `PENDING_STAGE_COMMIT` until completion or another deterministic pre-commit placeholder accepted by existing gates. 待验证: whether postcheck/review expects a real commit SHA before commit; current schema allows any string.
9. Do not change P28 scenario plan row definitions unless a path mismatch blocks P37; if changed, keep it deterministic and covered by `assert_coverage_registry.py --require-all`.

## Exact files likely to change

Likely source/harness files:

- `src/valkey_scale_lab/config/validation.py`
- `src/valkey_scale_lab/planner/plan.py`
- `src/valkey_scale_lab/resource.py`
- `src/valkey_scale_lab/cli.py` only if adding a first-class `dry-run` or projection subcommand is chosen
- `scripts/p37_200_plus_dry_run_artifacts.py` or equivalent new P37 generator
- `scripts/assert_200_plus_dry_run.py`
- `scripts/assert_no_bypass.py` if additional >200 runtime checks are needed
- `scripts/assert_coverage_registry.py` only if current P37 selection/final dry-run semantics are insufficient
- `codex/phase_manifest.json` if adding a generator gate or extra schema-specific P37 gates
- `codex/gate_lock.json` if locked harness files change

Likely tests:

- `tests/unit/test_goal_loop_assertions.py`
- `tests/unit/test_strict_coverage_registry.py`
- `tests/config/test_config_validation.py`
- `tests/planner/test_planner.py`
- New focused unit test file such as `tests/unit/test_p37_200_plus_dry_run.py`

Likely generated artifacts:

- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/**`
- `artifacts/coverage/strict_coverage_registry.json`
- `artifacts/coverage/strict_required_matrix.csv`
- `artifacts/goal_loop_strict/P37_200_PLUS_DRY_RUN_SUPPORT/WORKER_SUMMARY.md`
- `artifacts/goal_loop_strict/P37_200_PLUS_DRY_RUN_SUPPORT/REVIEW.md`
- `audit/P37_200_PLUS_DRY_RUN_SUPPORT/AUDIT.md`
- `audit/P37_200_PLUS_DRY_RUN_SUPPORT/audit_decision.json`
- `artifacts/gates/P37_200_PLUS_DRY_RUN_SUPPORT/gate_result.json` and logs

## Harness plan

- Strengthen `scripts/assert_200_plus_dry_run.py` to fail closed unless each required target has all sequence steps marked `PASS` or `DRY_RUN_PASS` with `execution_mode=dry_run`.
- Require `dry_run_results.jsonl` to contain exactly one or one-per-step deterministic result set per required target, with fields for:
  - `target_nodes`
  - `execution_mode`
  - `dry_run`
  - `sequence_steps`
  - `config_validation_ref`
  - `resource_estimate_ref`
  - `plan_ref`
  - `placement_schedule_ref`
  - `collision_check_ref`
  - `artifact_schema_projection_ref`
  - `report_projection_ref`
  - `no_runtime_created_proof_ref`
  - `runtime_resources_created=false`
  - `live_valkey_claimed=false`
  - `workload_executed=false`
- Require aggregate and per-target no-runtime proof refs to exist and prove zero created owned resources.
- Require no field in P37 artifacts to claim `real_valkey=true`, `probe_result=PASS` for a live >200 cluster, live endpoints, or workload operations.
- If a generator gate is added, update manifest and lock transparently and keep `assert_no_bypass.py` passing.
- Run `python3 scripts/assert_coverage_registry.py --previous <pre-P37-registry> --updated artifacts/coverage/strict_coverage_registry.json` if the worker captures a previous copy; this is recommended but 待验证 because no pre-P37 copy path currently exists.

## Schema and artifact plan

Existing manifest-required artifacts:

- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/phase_summary.json`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/dry_run_targets.json`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/dry_run_results.jsonl`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/resource_estimates.json`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/placement_schedules.json`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/no_runtime_created_proof.json`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/report_projection_index.json`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/coverage_ledger.json`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/quant_summary.json`

Recommended per-target supporting artifacts:

- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/generated_configs/scale_201_dry_run.yaml`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/generated_configs/scale_250_dry_run.yaml`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/generated_configs/scale_300_dry_run.yaml`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/generated_configs/scale_500_dry_run.yaml`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/generated_configs/scale_1000_dry_run.yaml`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/config_validation_<N>.json`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/resource_estimate_<N>.json`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/dry_run_plan_<N>.json`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/placement_schedule_<N>.json`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/collision_check_<N>.json`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/artifact_schema_projection_<N>.json`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/report_projection_<N>.json`
- `artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/no_runtime_created_proof_<N>.json`

New or strengthened schemas:

- Existing `schemas/artifact/no_runtime_created_proof.schema.json` may need additional required fields for `targets`, `inventory_scope`, `created_resources`, `deleted_resources`, `live_valkey_claimed=false`, and `workload_executed=false`.
- Existing `schemas/artifact/strict_generic_report.schema.json` is permissive; consider adding dedicated schemas for `dry_run_targets`, `dry_run_result`, `resource_estimates`, `placement_schedules`, and `report_projection_index` only if this can be done without broad churn. At minimum, `assert_200_plus_dry_run.py` must enforce structure.

## Coverage IDs targeted

For each target `201`, `250`, `300`, `500`, and `1000`, P37 targets these eight rows:

- `<target>.dry_run.config_validate_dry_run`
- `<target>.dry_run.resource_preflight_dry_run`
- `<target>.dry_run.plan_cluster_dry_run`
- `<target>.dry_run.placement_schedule_dry_run`
- `<target>.dry_run.port_directory_collision_check_dry_run`
- `<target>.dry_run.artifact_schema_projection_dry_run`
- `<target>.dry_run.no_runtime_created_proof`
- `<target>.dry_run.report_projection_dry_run`

All 40 rows must end as `DRY_RUN_PASS`, never `PASS`.

## Test and gate plan

Run during worker implementation:

```bash
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
python3 scripts/assert_strict_stage_contract.py --phase P37_200_PLUS_DRY_RUN_SUPPORT
python3 scripts/assert_no_bypass.py --phase P37_200_PLUS_DRY_RUN_SUPPORT
python3 scripts/assert_200_plus_dry_run.py --phase P37_200_PLUS_DRY_RUN_SUPPORT --min-targets 201,250,300,500,1000
python3 scripts/assert_coverage_registry.py --phase P37_200_PLUS_DRY_RUN_SUPPORT --category dry_run --require-all
```

Stage gates:

```bash
python3 scripts/codex_gate.py precheck --phase P37_200_PLUS_DRY_RUN_SUPPORT
python3 scripts/codex_gate.py run --phase P37_200_PLUS_DRY_RUN_SUPPORT
python3 scripts/codex_gate.py postcheck --phase P37_200_PLUS_DRY_RUN_SUPPORT
```

After review passes, main agent only:

```bash
python3 scripts/codex_gate.py mark-complete --phase P37_200_PLUS_DRY_RUN_SUPPORT
```

Focused tests to add:

- Config validation accepts P37-marked dry-run configs for `201/250/300/500/1000`.
- Config validation rejects any >200 config with `runtime.dry_run=false`.
- Planner produces dry-run-only plans for all required targets and rejects real >200 plans.
- P37 artifact generator writes all aggregate/per-target artifacts and does not call runtime creation.
- `assert_200_plus_dry_run.py` rejects missing target, non-dry-run mode, live Valkey claim, workload claim, missing sequence step, missing no-runtime proof, and any `runtime_resources_created=true`.
- Coverage registry transition test rejects P37 rows set to `PASS` instead of `DRY_RUN_PASS`.

## Safety constraints

- No real containers, networks, volumes, Valkey endpoints, or workloads above 200 nodes.
- No host firewall, route, interface, PF, nftables, iptables, or global OS network mutation.
- No `sudo` network path.
- Runtime inventory must be scoped to owned Valkey Scale Lab resources using deterministic project labels/names/paths.
- Generated configs must keep `default_max_nodes=100`; P37 dry-run support must not become a new real-execution default.
- `1000` remains dry-run-only; P37 must not run P14 opt-in real or real-like behavior.
- Missing dry-run measurements must use `MISSING`, `SKIPPED_WITH_REASON`, or `UNSUPPORTED_WITH_REASON` with reasons. Do not use `null`, empty strings, `NaN`, `undefined`, or fake zeroes.

## Blocked conditions

Block P37 if any of these occur:

- Any required target is missing.
- Any target has `execution_mode != dry_run`.
- Any >200 target starts a real container, creates a real Valkey cluster, probes live >200 endpoints as success evidence, or runs a workload.
- Aggregate or per-target no-runtime proof is missing, malformed, or shows created owned runtime resources.
- Coverage registry marks >200 rows as `PASS` or real execution instead of `DRY_RUN_PASS`.
- Report projection omits dry-run marking or presents projections as real evidence.
- A harness change would weaken safety, bypass detection, review requirements, or locked file integrity.

## Risks

- Current config/planner semantics appear 1000-specific and may not cleanly support 201/250/300/500 dry-run without a new explicit P37 dry-run profile marker.
- Current `assert_200_plus_dry_run.py` is too weak to prove the full required dry-run sequence; leaving it unchanged risks false completion.
- Docker inventory commands may fail on machines without Docker. The no-runtime proof should distinguish "inventory unavailable with reason" from "resources created", but the gate must remain fail-closed on actual creation.
- Updating `artifacts/coverage/strict_coverage_registry.json` in-place after prior stages requires preserving all non-P37 rows and row order exactly.
- `commit_sha` cannot be known before commit; current schemas allow a placeholder, but review/postcheck expectations are 待验证.

## 待验证

- Whether P37 should add a manifest generator gate or produce artifacts before `codex_gate.py run` through the worker; the manifest currently has no artifact-generation gate.
- Whether existing `resource preflight --dry-run` is acceptable for P37 or should be separated into a pure resource-estimate projection to avoid Docker availability becoming a dry-run blocker.
- Whether strengthened `no_runtime_created_proof.schema.json` should require per-target proofs or remain aggregate with per-target supporting artifacts enforced by `assert_200_plus_dry_run.py`.
- Whether `assert_coverage_registry.py --phase P37_200_PLUS_DRY_RUN_SUPPORT --category dry_run --require-all` intentionally requires all 145 registry rows and scenario plan/CSV on every P37 run; current code does.
- Whether postcheck/review requires final `commit_sha` values in coverage rows before the stage commit exists; current schema and assertion only require a string.
