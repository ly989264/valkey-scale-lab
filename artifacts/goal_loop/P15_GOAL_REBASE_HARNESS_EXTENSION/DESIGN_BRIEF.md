# DESIGN_BRIEF — P15_GOAL_REBASE_HARNESS_EXTENSION

## Objective

Extend the existing Codex phase harness so the automatic goal loop discovers and enforces stages P15-P26 without claiming new Valkey management or fault runtime behavior in P15. P15 should append the stage manifest entries, add schema families and fail-closed assertion scripts, wire goal-loop handoff/audit checks, and produce only P15 harness-scaffolding artifacts.

## Repository findings

- `codex/phase_manifest.json` currently stops at `automatic_stop_after: P13_SCALE_LADDER_50_100` and contains P00-P14 only. P14 is present, non-automatic, `max_nodes: 1000`, and `real_valkey_required: false`.
- `scripts/codex_gate.py` currently hard-codes `automatic_stop_after == P13_SCALE_LADDER_50_100`, rejects any automatic phase with `max_nodes > 100`, and requires every automatic phase with an ID lexically >= `P03` to set `real_valkey_required: true`. P15 and P21 need explicit preserved-policy exceptions: P15 is harness-only with no real Valkey, and P21 is the user-required 200-node bounded exception.
- `scripts/codex_gate.py` required artifacts are restricted to `artifacts/phases/...`, so goal-loop Markdown handoff files under `artifacts/goal_loop/...` should be checked by a new assertion/handoff check rather than placed in `required_artifacts`.
- `scripts/codex_gate.py postcheck` validates legacy audit paths only: `audit/<PHASE_ID>/AUDIT.md` and `audit/<PHASE_ID>/audit_decision.json`. P15 should preserve that and add goal-loop `REVIEW.md` requirements either in `codex_gate.py` postcheck or in `assert_goal_loop_stage.py` with a post-review mode.
- Existing `schemas/artifact/event.schema.json` and `metric_sample.schema.json` are older and permissive compared with `06_QUANTIFICATION_SPEC.md`. To avoid breaking old committed artifacts, P15 should add canonical goal-loop schemas for future P15-P26 manifest entries instead of tightening old P00-P14 schemas in place.
- `scripts/schema_validator.py` supports a deliberate JSON Schema subset: no `$ref`, `oneOf`, `anyOf`, conditionals, or custom formats. New schemas should use only `type`, `required`, `properties`, `additionalProperties`, `enum`, `const`, `pattern`, `minimum`, `maximum`, `minItems`, `items`, and similar supported keywords. Cross-field checks belong in assertion scripts.
- `codex/gate_lock.json` locks `codex/phase_manifest.json`, existing scripts, schemas, templates, docs, and workflow files. P15 will necessarily change locked files and add new harness-control files, so the worker must update the lock transparently after strengthening checks.
- `docs/codex/02_PHASES.md` currently documents P00-P14 only. `docs/codex/04_AUDITOR.md` and `templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md` know only the legacy audit artifacts and should be updated to require the goal-loop review artifact for P15-P26.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `codex/phase_manifest.json` | Modify | Set `automatic_stop_after` to P26 and append P15-P26 entries with gates, artifacts, audit paths, max-node limits, and real-Valkey flags. |
| `scripts/codex_gate.py` | Modify | Replace hard-coded P13 stop with manifest policy allowing P26, add explicit P15 no-real-Valkey exception and P21 200-node exception, and optionally enforce goal-loop review/handoff checks during postcheck. |
| `scripts/assert_goal_loop_stage.py` | Add | Validate P15-P26 discovery, ordering, stage docs, handoff files, manifest gates/artifacts, P14 boundary, P21 bounded exception, and no recursive run/postcheck gates. |
| `scripts/assert_quant_artifacts.py` | Add | Validate common phase artifacts, canonical JSONL line-by-line schemas, missing-data semantics, workload windows, Valkey evidence/cleanup presence for real stages. |
| `scripts/assert_management_ops_coverage.py` | Add | Validate P17-P19 operation rows, status taxonomy, required timing/convergence/workload fields, and no PASS on skipped/unsupported rows. |
| `scripts/assert_failover_latency_curve.py` | Add | Validate P20/P21 raw samples, rung set, minimum sample counts, timestamp fields, derived curve backing, 200-node exactness, and workload refs. |
| `scripts/assert_fault_matrix_coverage.py` | Add | Validate P22/P23/P24 fault rows, safe implementation paths, target scope, topology/fault result refs, and cleanup/workload refs. |
| `scripts/assert_workload_impact.py` | Add | Validate canonical baseline/pre_event/event/recovery/post_recovery/all_run windows and required QPS/latency/error metrics or explicit missing reasons. |
| `scripts/assert_split_brain_report.py` | Add | Validate detector execution, missing-detector reasons, conflicting slot/node/key fields, and `split_brain_window_ms=0` only when detectors ran. |
| `scripts/goal_loop_harness_artifacts.py` | Add | Emit P15 `phase_summary.json` and `quant_summary.json` from harness metadata only, without runtime claims. |
| `schemas/artifact/quant_summary.schema.json` | Add | Schema for common quantitative summary and missing-data inventory. |
| `schemas/artifact/workload_windows.schema.json` | Add | Canonical workload window artifact schema from `06_QUANTIFICATION_SPEC.md`. |
| `schemas/artifact/management_ops_matrix.schema.json` | Add | Matrix-level management operation rows and status semantics. |
| `schemas/artifact/management_operation_result.schema.json` | Add | JSONL line schema for individual management operation results. |
| `schemas/artifact/failover_latency_curve.schema.json` | Add | Curve artifact schema with raw-sample-derived series metadata. |
| `schemas/artifact/failover_latency_sample.schema.json` | Add | JSONL line schema for raw failover samples. |
| `schemas/artifact/fault_matrix_report.schema.json` | Add | Cross-fault matrix report schema. |
| `schemas/artifact/fault_result.schema.json` | Add | JSONL line schema for individual fault result rows. |
| `schemas/artifact/network_fault_report.schema.json` | Add | Delay/loss/flap report schema and safe implementation path fields. |
| `schemas/artifact/partition_report.schema.json` | Add | Minority/majority partition group and traffic policy schema. |
| `schemas/artifact/split_brain_report.schema.json` | Add | Detector and split-brain window schema. |
| `schemas/artifact/workload_impact_report.schema.json` | Add | Per-operation/fault workload impact comparison schema. |
| `schemas/artifact/workload_impact_cross_stage.schema.json` | Add | P25 cross-stage workload impact comparison schema. |
| `schemas/artifact/goal_loop_event.schema.json` | Add | Canonical P16-P26 `events.jsonl` line schema, leaving older `event.schema.json` intact. |
| `schemas/artifact/goal_loop_metric_sample.schema.json` | Add | Canonical P16-P26 `metrics_timeseries.jsonl` line schema, leaving older `metric_sample.schema.json` intact. |
| `docs/codex/02_PHASES.md` | Modify | Add P15-P26 summaries, pass criteria, and P21/P14 boundaries. |
| `docs/codex/04_AUDITOR.md` | Modify | Add P15-P26 goal-loop review inputs and the requirement to inspect `artifacts/goal_loop/<STAGE_ID>/REVIEW.md`. |
| `templates/audit/FRESH_CONTEXT_AUDIT_PROMPT.md` | Modify | Require goal-loop review/handoff artifacts for P15-P26 fresh-context audits. |
| `.github/workflows/codex-gates.yml` | Modify if needed | Add new goal-loop assertion/precheck coverage to CI if `precheck --all` is not sufficient. |
| `tests/unit/test_goal_loop_assertions.py` | Add | Unit tests for new assertion scripts and status taxonomy. |
| `tests/integration/test_goal_loop_manifest.py` | Add | Manifest and harness integration tests for P15-P26 discovery, gates, artifacts, and P14/P21 policy. |
| `tests/integration/test_goal_loop_postcheck.py` | Add | Postcheck/audit/handoff tests using temporary fixtures. |
| `codex/gate_lock.json` | Modify | Refresh locked hashes after controlled harness changes and include new scripts/schemas/docs/templates/workflow files. |

## Implementation plan

1. Update harness policy before relying on the new manifest: allow `automatic_stop_after: P26_FINAL_REPORT_REGRESSION`; exempt only `P15_GOAL_REBASE_HARNESS_EXTENSION` from the automatic P03+ real-Valkey rule; allow only `P21_FAILOVER_LATENCY_CURVE_200` to be automatic with `max_nodes: 200`; keep default max nodes exactly 100 and keep P14 non-automatic.
2. Append P15-P26 manifest entries in the order from `02_STAGE_MANIFEST.md`. P15 should be `fake_only_allowed: true`, `real_valkey_required: false`, `max_nodes: 0`; P16-P20 and P22-P26 should be real-Valkey stages capped at their documented max; P21 should be real-Valkey, automatic, `max_nodes: 200`, with explicit resource-preflight and 200-node assertions.
3. Add the schema files listed above using only the local validator subset. Use schemas for structure and assertion scripts for row/rung/window/detector semantics.
4. Add assertion scripts that fail closed on missing files, malformed JSON/JSONL, empty samples, unknown statuses, omitted missing reasons, unsafe implementation paths, or fake/downshifted evidence.
5. Add a P15 artifact writer gate that emits only `artifacts/phases/P15_GOAL_REBASE_HARNESS_EXTENSION/phase_summary.json` and `quant_summary.json`, explicitly stating that P15 is harness-only and has no runtime Valkey evidence claim.
6. Update docs/audit templates so a fresh review of P15-P26 must inspect goal-loop artifacts as well as legacy audit artifacts.
7. Add focused unit/integration tests, run the P15 required gates, then refresh `codex/gate_lock.json` after the strengthened harness passes.

## Harness, schema, and gate plan

Manifest gates should avoid recursive `codex_gate.py run` or `postcheck` commands inside `codex_gate.py run`. The outer stage sequence still runs `precheck`, `run`, and `postcheck`; the manifest gate list should include executable checks such as:

- `harness_precheck`: `python3 scripts/codex_gate.py precheck --phase <STAGE_ID>`
- `safety_static_scan`: `python3 scripts/safety_scan.py`
- `scripts_compile`: `python3 -m compileall -q scripts src`
- `unit_integration_tests`: `python3 -m pytest -q tests/unit tests/integration`
- `goal_loop_stage_assertion`: `python3 scripts/assert_goal_loop_stage.py --phase <STAGE_ID>`
- stage-specific assertion scripts listed below
- stage-specific real wrapper gate for P16-P26 using `scripts/valkey_e2e_gate.py`, `scripts/fault_safety_gate.py`, or `scripts/fault_failover_gate.py` as appropriate

P15 manifest entry:

- Artifacts: `phase_summary.json` with `phase_summary.schema.json`; `quant_summary.json` with `quant_summary.schema.json`.
- Gates: common checks plus `python3 scripts/goal_loop_harness_artifacts.py --phase P15_GOAL_REBASE_HARNESS_EXTENSION`.
- No `valkey_e2e_evidence.json`, no cleanup report, no real Valkey gate.

P16 manifest entry:

- Artifacts: common real artifacts: `phase_summary.json`, `valkey_e2e_evidence.json`, `cleanup_report.json`, `events.jsonl`, `metrics_timeseries.jsonl`, `workload_windows.json`, `quant_summary.json`.
- Gates: common checks, `assert_quant_artifacts.py`, and a real `valkey_e2e_gate.py` telemetry scenario.

P17-P19 manifest entries:

- Include the common real artifacts plus management artifacts from each stage doc.
- P17/P18 use `management_ops_matrix.json`, `management_operation_results.jsonl`, `management_workload_impact.json`, `management_topology_snapshots.jsonl`, `management_command_log.jsonl`; P18 also adds `reshard_slot_movements.jsonl` and `rebalance_summary.json`; P19 adds `rolling_restart_plan.json` and `rolling_restart_results.jsonl`.
- Gates: common checks, `assert_quant_artifacts.py`, `assert_management_ops_coverage.py`, `assert_workload_impact.py`, and a real `valkey_e2e_gate.py` management scenario.

P20-P21 manifest entries:

- P20 artifacts: common real artifacts plus `failover_latency_samples.jsonl`, `failover_latency_curve.json`, `fault_matrix_report.json`, `workload_impact_report.json`.
- P21 artifacts: common real artifacts plus `resource_preflight_200.json`, `failover_latency_samples_200.jsonl`, `failover_latency_curve_200.json`, `failover_latency_curve_combined_30_50_100_200.json`, `workload_impact_report.json`.
- Gates: common checks, `assert_failover_latency_curve.py`, `assert_workload_impact.py`, cleanup assertion, and `fault_failover_gate.py`/real wrapper gates. P21 must fail/block on failed preflight, not pass with dry-run or 100-node downshift.

P22-P24 manifest entries:

- P22 artifacts: common real artifacts plus `fault_matrix_report.json`, `fault_results.jsonl`, `fault_topology_snapshots.jsonl`, `workload_impact_report.json`.
- P23 artifacts: common real artifacts plus `network_fault_report.json`, `fault_results.jsonl`, `workload_impact_report.json`, `network_fault_command_log.jsonl`.
- P24 artifacts: common real artifacts plus `partition_report.json`, `split_brain_report.json`, `fault_results.jsonl`, `fault_topology_snapshots.jsonl`, `workload_impact_report.json`.
- Gates: common checks, `assert_fault_matrix_coverage.py`, `assert_workload_impact.py`, `assert_split_brain_report.py` for P24, `fault_safety_gate.py` where network safety is involved, and real fault/failover wrappers.

P25-P26 manifest entries:

- P25 artifacts: `phase_summary.json`, `valkey_e2e_evidence.json` or explicit source-real-evidence audit artifact, `cleanup_report.json` if a smoke verification runs, `workload_impact_cross_stage.json`, CSV exports, `missing_data_summary.json`, and `quant_summary.json`.
- P26 artifacts: `phase_summary.json`, `valkey_e2e_evidence.json` or source-real-evidence audit artifact, final report index, Markdown reports, CSV exports, and `quant_summary.json`.
- Gates: common checks, `assert_quant_artifacts.py`, `assert_workload_impact.py`, report/regression assertions, and a real wrapper or strict source-evidence audit path accepted by `codex_gate.py`.

Audit hook:

- Keep legacy `audit/<STAGE_ID>/AUDIT.md` and `audit/<STAGE_ID>/audit_decision.json` because `postcheck` already enforces them.
- Add P15-P26 goal-loop review checks: `artifacts/goal_loop/<STAGE_ID>/REVIEW.md` must contain exact `Decision: PASS`, cite the gate result path, and cite required artifacts before postcheck passes.
- Do not require `COMPLETION.md` in `postcheck` because `COMPLETION.md` is written around mark-complete and commit/push. Instead, require it through next-stage context reload or a completion/journal check. This lifecycle mismatch should be called out in the worker summary.

## Test plan

- Add unit tests for status taxonomy: `PASS`, `FAIL`, `MISSING`, `SKIPPED_WITH_REASON`, `UNSUPPORTED_WITH_REASON`, and stage-specific `PASS_NOOP_VERIFIED` only where explicitly allowed.
- Add schema tests with valid/minimal and invalid fixtures for every new schema, including JSONL line-by-line failures on one malformed or incomplete line.
- Add `assert_goal_loop_stage.py` tests that fail when P15-P26 are missing, out of order, missing stage docs, missing handoff files, missing stage gates, missing schemas, P14 becomes automatic, P21 changes defaults, or a recursive `codex_gate.py run/postcheck` appears as a manifest gate.
- Add management assertion tests for missing required operation rows, `operation_status: PASS` with no real-executed marker, missing timing/convergence fields, and missing workload refs.
- Add failover assertion tests for missing 30/50/100 rungs, too few samples, 200-node downshift, curve values not backed by samples, missing promotion/recovery timestamps, and missing workload refs.
- Add fault/network/split-brain assertion tests for unsafe implementation paths, missing delay/loss/flap rows, missing partition groups, `split_brain_window_ms: 0` without detectors, and missing detector reasons.
- Add workload-impact assertion tests for all required windows, missing p99/error/timeout/redirection fields, and absent missing reasons.
- Add integration tests that import `scripts/codex_gate.py` against a temporary manifest to verify P15 and P21 exceptions are narrow and all other automatic >100 or non-real P03+ stages are rejected.
- Run required P15 commands after implementation: precheck, safety scan, compileall, unit/integration pytest, `assert_goal_loop_stage.py`, `codex_gate.py run`, and `codex_gate.py postcheck`.

## Required artifacts

P15 worker must produce:

- `artifacts/phases/P15_GOAL_REBASE_HARNESS_EXTENSION/phase_summary.json`
- `artifacts/phases/P15_GOAL_REBASE_HARNESS_EXTENSION/quant_summary.json`
- `artifacts/goal_loop/P15_GOAL_REBASE_HARNESS_EXTENSION/CONTEXT_RELOAD.md`
- `artifacts/goal_loop/P15_GOAL_REBASE_HARNESS_EXTENSION/DESIGN_BRIEF.md`
- `artifacts/goal_loop/P15_GOAL_REBASE_HARNESS_EXTENSION/WORKER_SUMMARY.md`
- `artifacts/goal_loop/P15_GOAL_REBASE_HARNESS_EXTENSION/REVIEW.md`
- legacy review outputs: `audit/P15_GOAL_REBASE_HARNESS_EXTENSION/AUDIT.md` and `audit/P15_GOAL_REBASE_HARNESS_EXTENSION/audit_decision.json`
- `artifacts/goal_loop/P15_GOAL_REBASE_HARNESS_EXTENSION/COMPLETION.md` after postcheck/mark-complete/commit/push sequencing

P15 must not produce or claim `valkey_e2e_evidence.json` as real runtime evidence.

## Safety considerations

- Do not add any host-level network command path. New assertion scripts and tests may contain banned command strings only as quoted unsafe examples if `safety_scan.py` allows them; otherwise use neutral fixture strings to avoid weakening the scan.
- Keep P14 non-automatic and preserve its explicit 1000-node dry-run guard.
- Keep `default_max_nodes` exactly 100. P21's `max_nodes: 200` must be a named exception, not a global default increase.
- Real-stage gates must reference wrapper scripts that independently probe Valkey 9.1.x endpoints or fault behavior. P15 should only enforce that the future gates exist; it must not fake their outputs.
- Assertion scripts should never convert missing files, empty samples, or unsupported runtime paths into PASS.

## Resource considerations

- P15 itself has `max_nodes: 0` and should not require Docker, Valkey, or network resources.
- P20 and P21 manifest entries must require resource preflight artifacts and gates before any large cluster execution.
- P21 must remain automatic only because the user explicitly required the 200-node failover curve, and the gate must block rather than downshift when resources are insufficient.
- CI should not accidentally run P20/P21 real scale gates during ordinary P15 validation; `precheck --all` should validate configuration, while `codex_gate.py run --phase ...` executes only the requested phase.

## `待验证`

- Whether `codex_gate.py postcheck` should directly validate `artifacts/goal_loop/<STAGE_ID>/REVIEW.md` or whether `assert_goal_loop_stage.py` should have a separate post-review mode called before postcheck.
- Whether P25/P26 should create a fresh `valkey_e2e_evidence.json` through a smoke wrapper, or whether a stricter source-real-evidence audit artifact should satisfy `real_valkey_required`. Current `check_real_evidence()` only recognizes paths containing `valkey_e2e_evidence`.
- Whether existing CI workflows should add explicit `assert_goal_loop_stage.py --all` or rely on `codex_gate.py precheck --all` plus tests.
- Whether the lifecycle contradiction around `COMPLETION.md` being listed as required but containing mark-complete/commit/push results needs a harness exception note or a clarified postcheck-vs-next-stage assertion.
- Whether all current tests can tolerate adding P15-P26 to `codex/phase_manifest.json`, especially tests that assume the automatic loop ends at P13.

## Worker instructions

- Implement only this stage.
- Do not commit.
- Do not weaken harness or safety rules.
- Keep runtime management and fault behavior for P16-P26 unimplemented except for harness-visible command placeholders that fail closed until their future stage writes real evidence.
- Update `codex/gate_lock.json` only after the strengthened harness, schemas, scripts, docs, templates, and tests are in their final P15 form.
