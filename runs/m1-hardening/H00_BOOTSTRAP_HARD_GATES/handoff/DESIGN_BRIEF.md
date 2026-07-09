# H00 Design Brief

role: design
agent_invocation: real_subagent
stage_id: H00_BOOTSTRAP_HARD_GATES
source_commit_before: 5faa7e1a5b0aaa8c98111d3334613f04733e7387

## Summary

H00 should bootstrap `scripts/m1h/` as a fail-closed gate framework. The current M1 acceptance report and gate are not trustworthy enough for the hardening loop because they allow fixture-backed sources, shallow row/file checks, and legacy-looking artifacts to contribute to PASS. H00 must not change milestone status; it must install executable gates that classify evidence and block future false PASS claims.

## Main Findings From Current Acceptance Files

- `scripts/assert_milestone1_acceptance.py:77-86` and `98-106` read fixture sources when runtime artifacts are absent.
- `scripts/assert_milestone1_acceptance.py:89-95`, `109-114`, and `247-252` rely on parse/presence/count checks rather than capability semantics.
- `scripts/assert_milestone1_acceptance.py:144-161` reports fixture scale coverage as a PASS category.
- `runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json:20-52` records PASS reasons based on fixture coverage, row counts, and file presence; lines 253-298 list fixture sources as PASS.

## Recommended Implementation

Create a shared `scripts/m1h` helper for gate JSON writing, status/exit-code mapping, JSON/JSONL reads, source commit capture, and normalized violation records. Then implement every C00 script name.

The H00-critical gates are:

```text
python3 scripts/m1h/build_evidence_manifest.py --out runs/m1-hardening/evidence_manifest.json
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H00_BOOTSTRAP_HARD_GATES
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H00_BOOTSTRAP_HARD_GATES
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H00_BOOTSTRAP_HARD_GATES
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H00_BOOTSTRAP_HARD_GATES
python3 scripts/m1h/assert_stage_exit.py --stage H00_BOOTSTRAP_HARD_GATES
```

Also run:

```text
python3 -m compileall -q scripts src tests
python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h
```

## Acceptance Criteria For Worker

- `runs/m1-hardening/evidence_manifest.json` is generated, C01-shaped, and classifies all candidate claims.
- Every C00 gate writes `runs/m1-hardening/H00_BOOTSTRAP_HARD_GATES/artifacts/gates/<gate_name>.json`.
- Fixture-backed, legacy-only, dry-run-only, invalid, blocked, and small-smoke evidence cannot satisfy required exact-scale milestone claims.
- Agent artifact checks enforce `agent_invocation: real_subagent` and reject C12 forbidden phrases with file/line details.
- `assert_stage_exit.py` fails until all H00 gates, worker/review artifacts, review PASS, and required handoff files exist.
- Tests prove both success and failure paths for the new gates.

## Risks

- Static scans may be noisy; keep production-code shortcut scans separate from stage-artifact C12 scans.
- Existing P30-P36 artifacts may be real, but must not be promoted without M1 semantic checks.
- Later capability gates must not be empty wrappers. H00 should give them executable, test-covered fail-closed behavior immediately.
