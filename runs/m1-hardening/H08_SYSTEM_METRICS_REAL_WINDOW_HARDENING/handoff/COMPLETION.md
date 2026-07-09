# H08 Completion

stage_id: H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING
status: PASS
source_commit_before: 19bfc77e70df685111075c416cce8aeca5640f51
source_commit_after: PENDING_COMMIT

## Summary

H08 hardens system metrics claims so 30/50/100/200-node PASS requires exact-scale C10 system resource evidence from a same-directory `system_metrics_report.json`, `system_metrics_timeseries.jsonl`, and real Valkey 9.1.x evidence bundle. Generic workload, fault, and management `metrics_timeseries.jsonl` rows cannot satisfy system metrics coverage.

Current repository system metrics claims remain `BLOCKED_WITH_REASON` because complete exact-scale C10 system metrics bundles are absent. This is the expected fail-closed state: H08 passes by preventing weak promotion, not by inventing unavailable resource evidence.

## Implemented Checks

- system metrics claim promotion now depends on `diagnostics.system_h08_acceptance.accepted: true`;
- required lifecycle windows are enforced: setup, workload, and cleanup for 30 nodes; setup, management, workload, fault_or_failover, and cleanup for 50/100/200;
- accepted rows must be system-oriented source types, not workload/fault/management metrics rows;
- rows must prove exact scale, exact node cardinality, lifecycle window, metric name, timestamp, monotonic time, and numeric or structured missing values;
- high-value numeric coverage is required for CPU, RSS/memory, network IO, Valkey INFO, and cluster INFO, including per-window coverage;
- `system_metrics_report.json` is schema-validated and cross-checked against parsed timeseries sample count, rows by window, rows by node, lifecycle windows, exact node cardinality, source refs, and missing metric structure;
- fixture-only, report-only, fake, partial, dry-run, legacy, generic-metrics-only, skipped high-value groups, corrupted positive report counts, and node supersets remain blocked with reasons;
- `assert_system_metrics_real_windows.py` rejects unsafe manifest PASS claims without H08 diagnostics;
- H08 stage exit requires `assert_system_metrics_real_windows`.

## Gates

- `PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h08-main3 python3 -m compileall -q scripts src tests` -> PASS
- `python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h` -> PASS, 320 passed
- `python3 -m pytest -q tests/m1h/test_gate_framework.py -k 'system_metrics or h08'` -> PASS, 12 passed
- `python3 scripts/m1h/build_evidence_manifest.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING --out runs/m1-hardening/evidence_manifest.json` -> PASS
- `python3 scripts/m1h/assert_evidence_taxonomy.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS
- `python3 scripts/m1h/assert_system_metrics_real_windows.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS
- `python3 scripts/m1h/assert_no_fixture_fallback.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS
- `python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS
- `python3 scripts/m1h/assert_no_simulated_subagents.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS
- `python3 scripts/m1h/assert_stage_exit.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS
- `git diff --check` -> PASS

## Review

Two real review subagents returned `Decision: FAIL` and found false-PASS risks in report semantic cross-checking, report coverage count matching, and exact node cardinality. Those findings were fixed with required semantics and regression tests.

Fresh real review subagent returned `Decision: PASS` and verified the prior crafted report and extra-node repros now block.

## Commit And Push

commit: PENDING_COMMIT
push: PENDING_PUSH
