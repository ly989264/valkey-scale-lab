role: worker
agent_invocation: real_subagent
stage_id: H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING
source_commit_before: 19bfc77e70df685111075c416cce8aeca5640f51
source_commit_after: 19bfc77e70df685111075c416cce8aeca5640f51

# WORKER_SUMMARY

Implemented H08 real-window system metrics hardening.

Changed files:
- `scripts/m1h/manifest.py`
- `scripts/m1h/assert_system_metrics_real_windows.py`
- `scripts/m1h/assert_stage_exit.py`
- `tests/m1h/test_gate_framework.py`
- `runs/m1-hardening/evidence_manifest.json`
- H08 gate artifacts under `runs/m1-hardening/H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING/artifacts/gates/`
- `runs/m1-hardening/H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING/agents/worker.md`
- `runs/m1-hardening/H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING/handoff/WORKER_SUMMARY.md`

Key behavior:
- System metrics claims for 30/50/100/200 can PASS only through H08 diagnostics accepted from a same-directory real exact-scale `system_metrics_report.json`, `system_metrics_timeseries.jsonl`, and Valkey 9.1.x evidence bundle.
- Generic workload/fault/management `metrics_timeseries.jsonl` rows are counted as rejected non-system rows and cannot satisfy H08 system metrics coverage.
- Missing lifecycle windows, missing node coverage, missing timestamp/monotonic/node/window fields, fixture/report-only/fake/PARTIAL/dry-run/legacy inputs, wrong scale/version, and missing high-value numeric CPU/RSS/network/Valkey INFO/cluster INFO coverage all block with reasons.
- Current repository system metrics claims remain `BLOCKED_WITH_REASON`; the H08 gate passes as a hardening gate with zero passed system metric claims and four blocked claims.

Tests run:
- `python3 -m pytest -q tests/m1h/test_gate_framework.py` -> PASS, 82 passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h08 python3 -m compileall -q scripts/m1h tests/m1h` -> PASS.
- `python3 scripts/m1h/build_evidence_manifest.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING --out runs/m1-hardening/evidence_manifest.json` -> PASS.
- `python3 scripts/m1h/assert_evidence_taxonomy.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS.
- `python3 scripts/m1h/assert_system_metrics_real_windows.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS.
- `python3 scripts/m1h/assert_no_fixture_fallback.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS.
- `python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS.
- `python3 scripts/m1h/assert_no_simulated_subagents.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS.

Remaining risks:
- Review artifacts are intentionally not produced by the worker, so full H08 stage exit still depends on the review subagent and final main-agent stage exit.
- Full `tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h` was not run by this worker; focused H08 gate-framework coverage was run.
- H08 acceptance remains blocked until real exact-scale C10 system metrics bundles are generated.
