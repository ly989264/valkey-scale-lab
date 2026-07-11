role: worker
agent_invocation: real_subagent
stage_id: H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING
source_commit_before: 1248c98c4eb68deeb446e06ef06586b92aadcbca
source_commit_after: MISSING

# H09 Worker Summary

Implemented H09 fail-closed report input-quality hardening. Report rendering is now tracked separately from source quality, and `report.real_exact.30/50/100/200` can pass only when `diagnostics.report_h09_acceptance.accepted` is true with accepted same-scale M1H source claims.

## Changed Files

- `scripts/m1h/manifest.py`
- `scripts/m1h/assert_report_input_quality.py`
- `scripts/m1h/assert_stage_exit.py`
- `tests/m1h/test_report_input_quality.py`
- `runs/m1-hardening/evidence_manifest.json`
- H09 gate artifacts under `runs/m1-hardening/H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING/artifacts/gates/`
- H09 worker artifacts under `runs/m1-hardening/H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING/`

## Gate Outcome

- Current report claims remain `BLOCKED_WITH_REASON`.
- `assert_report_input_quality` exits 0 as a hardening gate.
- Gate result records `passed_report_claim_count: 0` and `blocked_report_claim_count: 4`.

## Tests Run

- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_pycache python3 -m py_compile scripts/m1h/manifest.py scripts/m1h/assert_report_input_quality.py scripts/m1h/assert_stage_exit.py`
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_pycache python3 scripts/m1h/build_evidence_manifest.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING`
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_pycache python3 scripts/m1h/assert_report_input_quality.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING`
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_pycache python3 scripts/m1h/assert_evidence_taxonomy.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING`
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_pycache python3 scripts/m1h/assert_no_fixture_fallback.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING`
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_pycache python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING`
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_pycache python3 scripts/m1h/assert_no_simulated_subagents.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING`
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey_pycache python3 -m pytest -q tests/m1h/test_report_input_quality.py tests/m1h/test_gate_framework.py`

## Remaining Risks

- Current P36 report indexes lack H09-valid offline/source-input sections, so they correctly remain blocked.
- Review and final H09 stage-exit artifacts are still pending outside worker scope.
