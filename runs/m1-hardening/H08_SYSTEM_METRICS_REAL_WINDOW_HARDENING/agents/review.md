role: review
agent_invocation: real_subagent
stage_id: H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING
source_commit_before: 19bfc77e70df685111075c416cce8aeca5640f51
source_commit_after: MISSING

# REVIEW

Decision: PASS

## Summary

The prior H08 findings are fixed. I found no remaining false-PASS blocker in the current H08 implementation or artifacts.

## Checks Performed

- Read the H08 context reload, design brief, worker summary, H08 stage doc, C04 exact-scale requirements, C10 system-metrics contract, and hard-gate architecture.
- Inspected `scripts/m1h/manifest.py` H08 logic. `system_metrics_report_semantics_valid` is now a required system-metrics semantic check, and H08 acceptance is tied to `diagnostics.system_h08_acceptance.accepted`.
- Verified report semantic checks now compare `sample_count`, `coverage.rows_by_window`, and `coverage.rows_by_node` against parsed `system_metrics_timeseries.jsonl` counts.
- Verified exact node cardinality now requires `len(unique_node_ids) == scale` for rows and `len(coverage.rows_by_node) == scale` for reports, so supersets like 31 unique nodes for a 30-node claim block.
- Inspected `scripts/m1h/assert_system_metrics_real_windows.py`; a system-metrics PASS without H08 diagnostics still fails with `system_metrics_pass_h08_not_accepted`.
- Inspected `scripts/m1h/assert_stage_exit.py`; H08 now requires `assert_system_metrics_real_windows.json`.
- Inspected `tests/m1h/test_gate_framework.py`; coverage now includes corrupt report semantics, report window/node count mismatch, extra node coverage, generic metrics rows, fixture-only/report-only paths, skipped high-value groups, runtime label node/window handling, missing row fields, and crafted PASS without diagnostics.
- Inspected `runs/m1-hardening/evidence_manifest.json`; all four system-metrics claims remain honestly `BLOCKED_WITH_REASON`, with `hardening_stage_accepted: false` and H08 diagnostics.
- Inspected H08 gate artifacts; the system-metrics gate is `PASS` as a hardening gate, with zero passed system-metrics claims, four blocked claims, and `rejected_non_system_row_count: 4356`.

## Commands Run

- `python3 -m pytest -q tests/m1h/test_gate_framework.py -k 'system_metrics or h08'` -> PASS, 12 passed.
- `python3 scripts/m1h/assert_system_metrics_real_windows.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS.
- `python3 scripts/m1h/assert_evidence_taxonomy.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS.
- `python3 scripts/m1h/assert_stage_exit.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> FAIL only because the prior review artifact still contained `Decision: FAIL`; this review overwrites that artifact with `Decision: PASS`.
- After writing this PASS review: `python3 scripts/m1h/assert_stage_exit.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS.
- After writing this PASS review: `python3 scripts/m1h/assert_no_simulated_subagents.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS.

## Residual Risks

- The dedicated H08 gate validates generated manifest claims and diagnostics, but it does not independently re-parse all cited artifacts from a deliberately forged manifest whose semantic booleans and H08 diagnostics are all fabricated. The normal loop mitigates this by regenerating `runs/m1-hardening/evidence_manifest.json` through `build_evidence_manifest.py`.
- Current real repository evidence remains blocked for H08 exact-scale system metrics until real C10 bundles exist for 30/50/100/200.
