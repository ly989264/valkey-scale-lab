# DESIGN_BRIEF - P40_STRICT_FINAL_AUDIT_CLOSEOUT

## Stage Contract Summary

P40 is the final fail-closed strict audit closeout. It must not start Valkey, Docker containers, workloads, or faults. It must inspect and validate the completed strict loop artifacts from P27-P39, produce final audit artifacts under `artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/`, and fail if any required real 50/100/200 coverage row is missing, skipped, dry-run-only, fake, downshifted, or not tied to exact-scale evidence. It must also fail if any >200 row has real runtime evidence, if P27-P39 lack PASS gates/reviews/audits/completion records, if cleanup/report/provenance/no-bypass checks fail, or if final report quality is incomplete.

Required P40 outputs:

- `artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/phase_summary.json`
- `artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/final_strict_audit_report.json`
- `artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/final_coverage_verdict.json`
- `artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/final_artifact_manifest.json`
- `artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/final_no_bypass_report.json`
- `artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/final_report_quality_verdict.json`
- `artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/analysis_provenance.json`
- `artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/quant_summary.json`
- `artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/FINAL_STRICT_SUMMARY.md`

## Current Repo Facts

- `python3 scripts/codex_gate.py next` returns `P40_STRICT_FINAL_AUDIT_CLOSEOUT`.
- `codex/status/phase_state.json` lists P27-P39 complete and does not list P40.
- `codex/phase_manifest.json` has `automatic_stop_after: P40_STRICT_FINAL_AUDIT_CLOSEOUT`, `default_max_nodes: 100`, and a P40 entry with `real_valkey_required=false`, `max_nodes=0`, and the required P40 artifact family.
- `codex/phase_manifest.json` P40 gate `coverage_registry` currently runs `python3 scripts/assert_coverage_registry.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT --require-final-real-scales`; the P40 stage doc and context reload require `--require-dry-run-200-plus` as well.
- `scripts/assert_final_strict_closeout.py` currently checks P27-P39 completion, prior gate PASS, prior strict review PASS, prior completion file existence, and `final_strict_audit_report.json.status == PASS`; it does not currently validate all P40 output artifacts, coverage totals, audit decisions, pushed commit evidence, cleanup PASS, P39 report verdicts, or dry-run no-runtime evidence directly.
- `scripts/assert_coverage_registry.py` supports `--require-final-real-scales` and `--require-dry-run-200-plus`; final real checks require real rows to be PASS with source/validation/review refs, and dry-run checks require >200 rows to be `DRY_RUN_PASS` with no-runtime proof in validation artifacts.
- `scripts/assert_no_bypass.py` supports `--scan-all-strict-stages` and checks manifest/gate result runner shape plus forbidden command patterns, 200-node exception policy, P37 dry-run policy, and host network mutation patterns.
- `scripts/assert_report_quality.py` has strong P39-specific report checks only when called with `--phase P39_VISUAL_REPORT_QUALITY_GATE`; the manifest P40 command omits `--phase`, so it performs generic checks plus whatever P40 `report_quality_report.json` exists. P40 should either call it with P39 phase in a direct command or encode a P40 verdict from a successful P39-phase quality check.
- `scripts/assert_analysis_provenance.py` has detailed P38/P39 logic but generic logic for P40. It currently requires `artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/analysis_provenance.json` with non-empty `source_artifacts` and `invented_values_present=false`.
- `artifacts/coverage/strict_coverage_registry.json` has 145 rows: real 50/100/200 lifecycle, management, and fault rows are `PASS`; >200 rows are `DRY_RUN_PASS`. Many `commit_sha` fields still read `PENDING_REVIEW_AND_COMMIT` or `PENDING_STAGE_COMMIT`, so literal commit-hash coverage provenance is incomplete unless P40 accepts completion/journal evidence instead.
- `artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md` records P27-P39 summaries and gate result hashes. P38/P39 journal entries say “containing pushed stage commit” instead of a concrete commit hash.
- `artifacts/goal_loop_strict/P38_CROSS_SCALE_ANALYSIS_REGRESSION/COMPLETION.md` and `artifacts/goal_loop_strict/P39_VISUAL_REPORT_QUALITY_GATE/COMPLETION.md` record pushed-branch text but not a literal 40-character commit hash.
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json` exists with 10 required chart assets and coverage totals matching P38.
- `artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_quality_report.json` has `status=PASS`, required chart checks, section checks, coverage-total check, forbidden-token scan, and missing-data reason checks.
- `artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/` does not exist yet.
- There are tests around strict registry/no-bypass/manifest behavior in `tests/unit/test_goal_loop_assertions.py` and `tests/unit/test_strict_coverage_registry.py`; no focused P40 final closeout tests were found.

## Exact Implementation Plan

1. Add a deterministic P40 artifact generator, preferably `scripts/p40_final_closeout.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT`, that reads only repository artifacts and writes the required P40 output family. It should compute sha256 values for key inputs and include command/gate verdict summaries, coverage totals, dry-run no-runtime verdicts, report-quality verdicts, cleanup verdicts, and prior-stage completion/review/audit status.
2. Strengthen `scripts/assert_final_strict_closeout.py` so P40 cannot pass from a thin `status=PASS` JSON. It should validate all required P40 artifacts, P27-P39 gate results, reviews, audits, completion records, gate sha references, strict journal entries, coverage counts, real/dry-run final statuses, cleanup PASS, P39 report quality, and analysis provenance presence.
3. Strengthen P40 provenance handling in `scripts/assert_analysis_provenance.py`: add P40-specific validation for P40 `analysis_provenance.json`, including source artifacts from manifest/state/coverage registry/P27-P39 gates/audits/completions/P38 analysis/P39 report outputs, sha256 checks, no raw log sources as analysis inputs, `runtime_started=false`, `invented_values_present=false`, and output artifact references.
4. Update the P40 manifest gate command to include `--require-dry-run-200-plus`, matching the stage doc: `python3 scripts/assert_coverage_registry.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT --require-final-real-scales --require-dry-run-200-plus`.
5. Consider making the P40 report-quality gate explicitly use P39 mode: `python3 scripts/assert_report_quality.py --phase P39_VISUAL_REPORT_QUALITY_GATE --report-index artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json`, or make P40 `final_report_quality_verdict.json` record the exact successful P39-quality command and have `assert_final_strict_closeout.py` enforce it.
6. Add focused unit tests for final closeout fail-closed behavior: missing prior stage gate, failed prior review/audit, missing P40 artifact, non-PASS final audit report, real coverage not PASS, dry-run row missing no-runtime proof, P40 provenance source hash mismatch, and forbidden placeholder commit evidence if the worker chooses to require literal commit hashes.
7. Generate P40 artifacts through the new generator after any gate/test hardening. P40 artifacts should use existing schemas (`phase_summary.schema.json`, `quant_summary.schema.json`, `strict_generic_report.schema.json`) but contain rich fields because schemas are permissive.
8. Run the P40 gates and fix only P40-scope defects. Do not mark complete until review passes.

## Exact Files Likely To Change

- `scripts/p40_final_closeout.py` - new generator for P40 final audit artifacts.
- `scripts/assert_final_strict_closeout.py` - strengthen final audit validation.
- `scripts/assert_analysis_provenance.py` - add P40-specific provenance checks.
- `codex/phase_manifest.json` - update P40 coverage/report-quality gate commands only if needed to match stage doc.
- `tests/unit/test_goal_loop_assertions.py` or new `tests/unit/test_p40_final_closeout.py` - focused fail-closed tests.
- `artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/*` - generated P40 output artifacts.
- `artifacts/goal_loop_strict/P40_STRICT_FINAL_AUDIT_CLOSEOUT/WORKER_SUMMARY.md`, `REVIEW.md`, `COMPLETION.md`, and possibly `FIX_LOG.md` - produced later by main/worker/review flow, not by this design subagent.
- `audit/P40_STRICT_FINAL_AUDIT_CLOSEOUT/AUDIT.md` and `audit/P40_STRICT_FINAL_AUDIT_CLOSEOUT/audit_decision.json` - produced by review stage later.

No source runtime, Valkey operation, fault injection, network, or Docker implementation files should need changes for P40.

## Schemas And Artifacts

Use existing schemas:

- `schemas/artifact/phase_summary.schema.json`
- `schemas/artifact/quant_summary.schema.json`
- `schemas/artifact/strict_generic_report.schema.json`

Recommended P40 artifact contents:

- `final_strict_audit_report.json`: overall `PASS`/`FAIL`, P27-P39 status table, gate result sha table, review/audit table, completion/push evidence table, blocking findings.
- `final_coverage_verdict.json`: counts by category and scale, 105 real PASS rows, 40 >200 `DRY_RUN_PASS` rows, evidence refs, missing/fail/block lists.
- `final_artifact_manifest.json`: every required P27-P40 artifact path, existence, size, sha256, schema where known.
- `final_no_bypass_report.json`: manifest no-bypass verdict, all strict gate results scanned, forbidden command scan result, 200-node exception check, >200 dry-run check.
- `final_report_quality_verdict.json`: P39 report index path/hash, report-quality report path/hash, required chart/section counts, missing-data reason status, forbidden-token status.
- `analysis_provenance.json`: P40 closeout input/output provenance, source hashes, `runtime_started=false`, `invented_values_present=false`, no raw logs as sources.
- `quant_summary.json`: P40 audit-only quant summary with `status=PASS`, no runtime claims, and skipped runtime metrics encoded as `SKIPPED_WITH_REASON` with reasons.
- `FINAL_STRICT_SUMMARY.md`: concise human-readable closeout summary derived from P40 JSON artifacts.

## Gates And Commands

Worker should run at least:

```bash
python3 scripts/codex_gate.py precheck --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT
python3 scripts/safety_scan.py
python3 -m compileall -q scripts src
python3 -m pytest -q tests/unit tests/integration
python3 scripts/p40_final_closeout.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT
python3 scripts/assert_strict_stage_contract.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT
python3 scripts/assert_no_bypass.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT
python3 scripts/assert_final_strict_closeout.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT
python3 scripts/assert_coverage_registry.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT --require-final-real-scales --require-dry-run-200-plus
python3 scripts/assert_no_bypass.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT --scan-all-strict-stages
python3 scripts/assert_report_quality.py --phase P39_VISUAL_REPORT_QUALITY_GATE --report-index artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json
python3 scripts/assert_analysis_provenance.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT
python3 scripts/codex_gate.py run --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT
```

After fresh-context review PASS, the main agent, not worker, should run:

```bash
python3 scripts/codex_gate.py postcheck --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT
python3 scripts/codex_gate.py mark-complete --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT
git status --short
git add <intentional P40 files>
git commit -m "P40_STRICT_FINAL_AUDIT_CLOSEOUT: strict final audit closeout"
git push
```

Do not run `mark-complete`, commit, or push from the worker/design phase.

## Coverage IDs Targeted

P40 should not add new real runtime coverage rows. It must final-audit all existing strict required IDs:

- 36 lifecycle real rows: `50.lifecycle.*`, `100.lifecycle.*`, `200.lifecycle.*`
- 33 management real rows: `50.management.*`, `100.management.*`, `200.management.*`
- 36 fault real rows: `50.fault.*`, `100.fault.*`, `200.fault.*`
- 40 dry-run rows: `201.dry_run.*`, `250.dry_run.*`, `300.dry_run.*`, `500.dry_run.*`, `1000.dry_run.*`

Target final counts: 145 required rows total, 105 real `PASS`, 40 dry-run `DRY_RUN_PASS`.

## Safety Constraints

- P40 is audit-only: no Docker start/stop, no live Valkey gate, no workload execution, no fault injection.
- No host firewall, routing, interface, PF/nftables/iptables, or OS networking mutation.
- No real execution above 200 nodes.
- No manual edits to `codex/status/phase_state.json` or gate results.
- Do not loosen schemas, stage docs, safety scan, no-bypass scan, or strict harness controls to make P40 pass.
- Missing evidence must be `MISSING`, `SKIPPED_WITH_REASON`, or blocked/fail with a reason; do not invent commit hashes, metrics, or runtime proof.

## Blocked Conditions

P40 must block/fail if any of these are true:

- Any P27-P39 stage is not marked complete by harness state.
- Any P27-P39 `artifacts/gates/<stage>/gate_result.json` is missing or not `PASS`.
- Any P27-P39 strict review lacks exact `Decision: PASS`.
- Any P27-P39 audit decision is missing, not `PASS`, or not fresh-context.
- Any required 50/100/200 coverage row is not `PASS`, lacks source/validation/review refs, or points to missing artifacts.
- Any >200 row is not `DRY_RUN_PASS`, lacks no-runtime proof, or shows runtime creation.
- Any cleanup report for real stages is missing or not PASS.
- P39 report quality or provenance validation fails.
- No-bypass scan detects forbidden pass-only command, manual state/gate bypass, 200-node downshift, host network mutation, or real execution above 200.
- P40 artifacts are missing, malformed, too shallow, or contain forbidden missing-value encodings.

## Review Focus Points

- Verify P40 did not start runtime resources and did not rerun large-scale Valkey evidence.
- Compare P40 artifact conclusions against `artifacts/coverage/strict_coverage_registry.json`, P38 analysis tables, and P39 report artifacts.
- Check whether final closeout handles the manifest/stage-doc mismatch on `--require-dry-run-200-plus`.
- Check P40 `analysis_provenance.json` hashes and source set; it should cite artifacts, not raw logs.
- Check final artifact manifest includes P27-P39 gate/audit/review/completion files and P40 outputs.
- Check the review/audit decision cites the P40 gate result path and sha256 after gates run.
- Check whether commit/push evidence is concrete enough for the final contract.

## 待验证

- 待验证: whether P40 should require literal commit hashes in P27-P39 `COMPLETION.md` and coverage registry `commit_sha`; current evidence includes placeholders such as `PENDING_REVIEW_AND_COMMIT`, `PENDING_STAGE_COMMIT`, and prose like “containing pushed P39 stage commit.”
- 待验证: whether `scripts/codex_gate.py postcheck` for P40 already checks `FINAL_STRICT_SUMMARY.md`; the manifest required artifacts list does not include the Markdown summary even though the stage doc does.
- 待验证: whether P40 should update `codex/phase_manifest.json` to add `--require-dry-run-200-plus` and `--phase P39_VISUAL_REPORT_QUALITY_GATE` to report-quality command, or whether direct extra commands plus final verdict artifacts are sufficient.
- 待验证: whether P37 no-runtime proof is acceptable when Docker inventory was `SKIPPED_WITH_REASON` because the local socket denied access, with filesystem/runtime-command evidence remaining clean.
- 待验证: whether P39 static visual QA is acceptable for final closeout, since the journal records static inspection rather than browser screenshot rendering.
