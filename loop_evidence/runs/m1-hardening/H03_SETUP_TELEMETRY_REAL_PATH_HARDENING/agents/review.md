# H03 Review

role: review
agent_invocation: real_subagent
stage_id: H03_SETUP_TELEMETRY_REAL_PATH_HARDENING
source_commit_before: 65089a70901e8ccb7be4af89bf0bee92ad4e2016
source_commit_after: 65089a70901e8ccb7be4af89bf0bee92ad4e2016

## Scope Reviewed

- H03 context, design, worker, and gate artifacts under `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/`.
- H02 completion, review, and fail-closed acceptance artifacts under `runs/m1-hardening/H02_ACCEPTANCE_GATE_FAIL_CLOSED/`.
- C06 setup telemetry contract and H03 stage contract in `codex_goal_loop_m1_hardening_v2/`.
- Git status/diff for `scripts/m1h/manifest.py`, `scripts/m1h/assert_setup_core_metrics.py`, `scripts/m1h/assert_stage_exit.py`, `scripts/m1h/assert_no_legacy_m1_pass.py`, `tests/m1h/test_gate_framework.py`, and `runs/m1-hardening/evidence_manifest.json`.
- Existing setup telemetry schema and exact-scale setup source artifacts.

## Findings

No blocking findings.

The H03 implementation makes setup telemetry PASS depend on real C06 acceptance instead of timing-file presence. `scripts/m1h/manifest.py` now records setup C06 diagnostics, requires a non-fixture `setup_telemetry.json`, exact artifact node count, artifact `status: PASS`, numeric C06 core metrics, complete per-node samples, exact-scale real Valkey evidence, and Valkey 9.1.x evidence before setting setup evidence to `REAL_EXACT_SCALE`.

`scripts/m1h/assert_setup_core_metrics.py` is now a fail-closed hardening gate: it passes the stage only when unsafe setup PASS promotion is absent, while still recording the current setup claims as blocked. It rejects PASS claims backed by non-promotable evidence kinds, fixture sources, missing `setup_telemetry.json`, timing-only evidence, failed C06 semantic checks, or unaccepted C06 diagnostics.

## Evidence Reviewed

- `runs/m1-hardening/evidence_manifest.json`
- `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/artifacts/gates/build_evidence_manifest.json`
- `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/artifacts/gates/assert_evidence_taxonomy.json`
- `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/artifacts/gates/assert_setup_core_metrics.json`
- `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/artifacts/gates/assert_no_fixture_fallback.json`
- `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/artifacts/gates/assert_no_legacy_m1_pass.json`
- `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/artifacts/gates/assert_no_simulated_subagents.json`
- `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/artifacts/gates/assert_stage_exit.json`
- `runs/m1-hardening/H02_ACCEPTANCE_GATE_FAIL_CLOSED/artifacts/milestone1_acceptance_report.json`

## Setup Claim Verification

- `setup_telemetry.real_exact.30`: remains `BLOCKED_WITH_REASON`; no M1-format exact-scale `setup_telemetry.json`, no exact 30-node real Valkey PASS evidence in the setup claim path, and no Valkey 9.1.x proof for that claim.
- `setup_telemetry.real_exact.50`: remains `BLOCKED_WITH_REASON`; real Valkey 9.1.x exact-scale evidence exists, but only legacy `runtime_timing_breakdown*.json` setup timing evidence exists, not C06 M1 setup telemetry.
- `setup_telemetry.real_exact.100`: remains `BLOCKED_WITH_REASON`; real Valkey 9.1.x exact-scale evidence exists, but only legacy `runtime_timing_breakdown*.json` setup timing evidence exists, not C06 M1 setup telemetry.
- `setup_telemetry.real_exact.200`: remains `BLOCKED_WITH_REASON`; real Valkey 9.1.x exact-scale evidence exists, but only legacy `runtime_timing_breakdown*.json` setup timing evidence exists, not C06 M1 setup telemetry.

The setup gate artifact has `status: PASS`, `setup_claim_status: BLOCKED_WITH_REASON`, `passed_claims: []`, four blocked setup claims, zero violations, and the exact C06 metric list from the contract.

## Gates

- `python3 -m pytest tests/m1h/test_gate_framework.py`: PASS, 24 passed.
- `python3 scripts/m1h/build_evidence_manifest.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING --out runs/m1-hardening/evidence_manifest.json`: PASS.
- `python3 scripts/m1h/assert_evidence_taxonomy.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING`: PASS.
- `python3 scripts/m1h/assert_setup_core_metrics.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING`: PASS.
- `python3 scripts/m1h/assert_no_fixture_fallback.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING`: PASS.
- `python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING`: PASS.
- `python3 scripts/m1h/assert_no_simulated_subagents.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING`: PASS after review artifacts were written.
- `python3 scripts/m1h/assert_stage_exit.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING --allow-blocked`: `BLOCKED_WITH_REASON` before review artifacts, with zero violations and only missing review artifacts.
- `python3 scripts/m1h/assert_stage_exit.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING`: PASS after review artifacts were written.

## Decision

Decision: PASS
