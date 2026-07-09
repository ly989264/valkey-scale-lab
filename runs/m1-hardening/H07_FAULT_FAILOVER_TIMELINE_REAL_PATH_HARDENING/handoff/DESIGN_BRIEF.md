role: design
agent_invocation: real_subagent
stage_id: H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING
source_commit_before: 3c2579c123bf498b2a8d1ea16a6eb8e31647a720
source_commit_after: MISSING

# DESIGN_BRIEF

## Recommendation

Implement H07 as a dedicated C09 fault/failover timeline hardening gate. Current `fault_timeline.real_exact.{50,100,200}` claims should remain `BLOCKED_WITH_REASON` because the repository does not yet contain complete same-directory M1-format C09 bundles for those exact scales.

## Code Changes

- In `scripts/m1h/manifest.py`, add H07 constants for 12 required fault types, 12 lifecycle events, and 11 numeric C09 metrics.
- Replace shallow fault timeline checks with a dedicated `evaluate_fault_timeline_claim(...)` that scores same-directory evidence bundles.
- Require `fault_timeline_report.json`, `fault_timeline_events.jsonl`, `failover_latency_samples.jsonl`, workload refs, cleanup refs, and `valkey_e2e_evidence.json` in one coherent exact-scale bundle.
- Validate report, event, latency-sample, curve, cleanup, workload, and Valkey artifacts against schemas plus semantic checks.
- Promote `fault_timeline` to `REAL_EXACT_SCALE` only when `diagnostics.fault_h07_acceptance.accepted` is true.
- Replace `scripts/m1h/assert_fault_timeline_real.py` with a H07-specific gate modeled on the H06 workload gate.
- Register `H07_REQUIRED_GATE_RESULTS` in `scripts/m1h/assert_stage_exit.py`.

## Required Semantics

A fault timeline PASS requires:

- exact scale 50, 100, or 200;
- real Valkey 9.1.x evidence in the same bundle;
- report status PASS and no PARTIAL row;
- all required fault types;
- observed lifecycle events for every accepted row;
- numeric C09 metrics, with no missing/skipped placeholders;
- real execution mode, not fixture, dry-run, legacy, fake, or partial;
- resolved workload refs, with exact-scale H06 workload claim accepted;
- resolved cleanup refs and clean cluster evidence;
- no P20/P21-only or `fault_sequence.json`-only promotion.

## Tests

Add tests for a valid exact-scale bundle, missing report/events/samples, missing fault type, missing lifecycle event, non-numeric metric, PARTIAL status, non-real execution mode, scale mismatch, Valkey version mismatch, missing workload ref, H06-blocked workload dependency, missing/dirty cleanup, legacy sample substitution, P20/P21 curve-only evidence, split-directory splicing, dedicated gate behavior, and H07 stage-exit wiring.

## Gates

Run compile, pytest, manifest build, taxonomy, H07 fault gate, fixture/legacy/subagent scans, and stage exit:

```text
PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h07 python3 -m compileall -q scripts src tests
python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h
python3 scripts/m1h/build_evidence_manifest.py --stage H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING --out runs/m1-hardening/evidence_manifest.json
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING
python3 scripts/m1h/assert_fault_timeline_real.py --stage H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING
python3 scripts/m1h/assert_stage_exit.py --stage H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING
```

## Acceptance Criteria

- Unsafe `fault_timeline` PASS claims fail.
- Honest blocked exact-scale fault claims pass the H07 stage gate while keeping milestone PASS blocked.
- Gate JSON is written under `runs/m1-hardening/H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING/artifacts/gates/`.
- No fixture, legacy, fake, PARTIAL, dry-run, small-smoke, or non-empty-only artifact can promote a C09 claim.

## Blocked-State Expectations

Expected current state: `fault_claim_status: BLOCKED_WITH_REASON`, zero passed fault claims, three blocked exact-scale claims, and reasons naming missing C09 timeline report/events/samples, incomplete metrics, workload benchmark dependency, cleanup proof, and exact-scale Valkey bundle requirements.

## Review Risks

- Do not accept legacy real Valkey files without C09 fields.
- Do not let schema validity replace semantic validation.
- Do not treat fault workload impact rows as accepted H06 benchmark evidence.
- Do not combine artifacts across directories to create a PASS.
