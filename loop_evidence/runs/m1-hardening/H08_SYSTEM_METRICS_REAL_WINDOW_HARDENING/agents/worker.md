role: worker
agent_invocation: real_subagent
stage_id: H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING
source_commit_before: 19bfc77e70df685111075c416cce8aeca5640f51
source_commit_after: 19bfc77e70df685111075c416cce8aeca5640f51

# Worker Artifact

Implemented H08 fail-closed system metrics hardening only.

Changed files:
- scripts/m1h/manifest.py
- scripts/m1h/assert_system_metrics_real_windows.py
- scripts/m1h/assert_stage_exit.py
- tests/m1h/test_gate_framework.py
- runs/m1-hardening/evidence_manifest.json
- runs/m1-hardening/H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING/artifacts/gates/build_evidence_manifest.json
- runs/m1-hardening/H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING/artifacts/gates/assert_evidence_taxonomy.json
- runs/m1-hardening/H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING/artifacts/gates/assert_system_metrics_real_windows.json
- runs/m1-hardening/H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING/artifacts/gates/assert_no_fixture_fallback.json
- runs/m1-hardening/H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING/artifacts/gates/assert_no_legacy_m1_pass.json
- runs/m1-hardening/H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING/artifacts/gates/assert_no_simulated_subagents.json
- runs/m1-hardening/H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING/agents/worker.md
- runs/m1-hardening/H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING/handoff/WORKER_SUMMARY.md

Implementation notes:
- Added H08/C10 system metric semantics to manifest generation.
- Required same-directory `system_metrics_report.json`, `system_metrics_timeseries.jsonl`, and `valkey_e2e_evidence.json` for exact-scale system metric PASS.
- Rejected fixture-only, report-only, generic `metrics_timeseries.jsonl`, fake/PARTIAL/dry-run/legacy, wrong scale/version, missing lifecycle windows, missing node coverage, invalid row fields, and missing high-value numeric CPU/RSS/network/Valkey INFO/cluster INFO coverage.
- Replaced the generic system metrics capability wrapper with a dedicated H08 gate that fails crafted PASS claims without `diagnostics.system_h08_acceptance.accepted is true`.
- Added H08 stage-exit gate wiring and focused tests/helpers.

Tests run:
- `python3 -m pytest -q tests/m1h/test_gate_framework.py` -> PASS, 82 passed.
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h08 python3 -m compileall -q scripts/m1h tests/m1h` -> PASS.
- `python3 scripts/m1h/build_evidence_manifest.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING --out runs/m1-hardening/evidence_manifest.json` -> PASS.
- `python3 scripts/m1h/assert_evidence_taxonomy.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS.
- `python3 scripts/m1h/assert_system_metrics_real_windows.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS.
- `python3 scripts/m1h/assert_no_fixture_fallback.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS.
- `python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS.
- `python3 scripts/m1h/assert_no_simulated_subagents.py --stage H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING` -> PASS.

Current H08 gate result:
- `assert_system_metrics_real_windows` exits 0 as a hardening gate.
- `system_metrics_claim_status`: `BLOCKED_WITH_REASON`
- `passed_claims`: `[]`
- `blocked_claims`: 4
- Generic non-system metric rows rejected/counted: 4356

Remaining risks:
- Full stage exit was not run to PASS because review artifacts are outside the worker role and are still expected from the real review subagent.
- The first compileall attempt without `PYTHONPYCACHEPREFIX` failed because Python tried to write bytecode under the user Library cache outside the sandbox; the rerun with `/private/tmp/valkey-scale-lab-pycache-h08` passed.
- H08 correctly remains blocked until real exact-scale C10 system metric bundles exist for 30/50/100/200.
