# P40_STRICT_FINAL_AUDIT_CLOSEOUT — Strict Final Audit Closeout

## Purpose

Perform the final fail-closed audit of the strict loop. This stage must prove the clarified goal is fully satisfied before the loop stops.

## Required inputs

P40 must inspect:

```text
codex/phase_manifest.json
codex/status/phase_state.json
artifacts/coverage/strict_coverage_registry.json
artifacts/goal_loop_strict/STRICT_STAGE_JOURNAL.md
artifacts/gates/P27_* through P39_*
artifacts/phases/P30_* through P39_*
audit/P27_* through audit/P39_*
final report artifacts from P39
```

## Required outputs

```text
artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/phase_summary.json
artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/final_strict_audit_report.json
artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/final_coverage_verdict.json
artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/final_artifact_manifest.json
artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/final_no_bypass_report.json
artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/final_report_quality_verdict.json
artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/quant_summary.json
artifacts/phases/P40_STRICT_FINAL_AUDIT_CLOSEOUT/FINAL_STRICT_SUMMARY.md
```

## Required gates

```text
python3 scripts/assert_final_strict_closeout.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT
python3 scripts/assert_coverage_registry.py --require-final-real-scales --require-dry-run-200-plus
python3 scripts/assert_no_bypass.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT --scan-all-strict-stages
python3 scripts/assert_report_quality.py --report-index artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json
python3 scripts/assert_analysis_provenance.py --phase P40_STRICT_FINAL_AUDIT_CLOSEOUT
```

## Final pass criteria

P40 passes only when:

```text
P27-P39 are marked complete by harness state
P27-P39 each have gate_result PASS
P27-P39 each have strict review Decision: PASS
P27-P39 each have committed and pushed completion records
all 50/100/200 lifecycle rows are PASS
all 50/100/200 management rows are PASS
all 50/100/200 fault rows are PASS
all real rows have exact-scale real evidence
all >200 rows are DRY_RUN_PASS and no runtime was created
all required quantitative artifacts validate
final report quality gate passes
no bypass patterns are detected
cleanup is PASS for every real execution stage
```

## Blocking conditions

```text
any real coverage row missing or not PASS
any 200-node real row downshifted
any >200 row ran real resources
any review missing or failed
any gate result manually altered
any report quality failure remains
any cleanup failure remains
```

P40 must not pass with warnings. Non-blocking notes may exist, but the final decision is either complete PASS or blocked FAIL.
