# H09 Input

previous_stage: H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING
previous_status: PASS
previous_commit: PENDING_COMMIT

## Carry Forward

System metrics exact-scale claims now fail closed. H09 can rely on H08 semantics when validating Chinese report input quality: report generation must not turn blocked or weak source evidence into milestone PASS.

For H09 Chinese report input quality hardening, pay special attention to:

- report PASS proves rendering only, not source evidence quality;
- final report inputs must cite accepted M1H claims or explicitly preserve blocked source status;
- fixture-only, legacy-only, report-only, generic metrics, skipped core metrics, fake or partial fault timelines, and weak workload/system metrics must not satisfy milestone report claims;
- report index and generated outputs should remain offline and artifact-only;
- blocked source claims should allow report rendering PASS only while milestone status remains `BLOCKED_WITH_REASON`.

Required H08 artifacts:

- `runs/m1-hardening/H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING/artifacts/gates/assert_system_metrics_real_windows.json`
- `runs/m1-hardening/H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING/handoff/REVIEW.md`
- `runs/m1-hardening/evidence_manifest.json`
