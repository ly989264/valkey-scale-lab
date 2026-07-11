# H02 Design Subagent Artifact

role: design
agent_invocation: real_subagent
stage_id: H02_ACCEPTANCE_GATE_FAIL_CLOSED
source_commit_before: 577b37d3aaadc5bc87f81090b02014133d318b1f

## Scope Read

- `runs/m1-hardening/H02_ACCEPTANCE_GATE_FAIL_CLOSED/handoff/CONTEXT_RELOAD.md`
- `codex_goal_loop_m1_hardening_v2/START_HERE.md`
- `codex_goal_loop_m1_hardening_v2/AGENTS_M1H_V2.md`
- hardening docs `00`, `02`, `03`, `04`, `05`, `09`, `10`, `13`, `15`, `17`, and `18`
- `codex_goal_loop_m1_hardening_v2/stages/H02_ACCEPTANCE_GATE_FAIL_CLOSED.md`
- contracts `C03_MILESTONE_ACCEPTANCE_SCHEMA.md`, `C04_EXACT_SCALE_REQUIREMENTS.md`, and `C05_STATIC_FORBIDDEN_PATTERNS.md`
- H01 handoff artifacts: `DESIGN_BRIEF.md`, `WORKER_SUMMARY.md`, `REVIEW.md`, `COMPLETION.md`, and `NEXT_STAGE_INPUT.md`
- `runs/m1-hardening/evidence_manifest.json`
- `runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/artifacts/milestone1_acceptance_reset.json`
- `runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json`
- `scripts/assert_milestone1_acceptance.py`
- `scripts/m1h/build_acceptance_reset.py`
- `scripts/m1h/assert_final_milestone1_hardened.py`
- `scripts/m1h/assert_stage_exit.py`
- related H01 tests in `tests/m1h/test_gate_framework.py` and `tests/ci/test_milestone1_acceptance_gate.py`

## Current State

H01 correctly reset the active hardening acceptance state. The generated manifest has all 29 C04 required claim ids, with 29 `BLOCKED_WITH_REASON` claims, 0 `PASS` claims, evidence kinds of 23 `INVALID`, 3 `LEGACY_EVIDENCE_ONLY`, 2 `FIXTURE_ONLY`, and 1 `BLOCKED_WITH_REASON`. The H01 reset artifact is C03-shaped: `hardening_loop_status: PASS`, `milestone1_status: BLOCKED_WITH_REASON`, `false_pass_prevented: true`, `required_claim_count: 29`, `passed_claim_count: 0`, `blocked_claim_count: 29`, and `failed_claim_count: 0`.

The old M1-S09 acceptance report is still present and still says `milestone1_status: PASS`. It contains 12 fixture source entries and 7 PASS heavy-rung rows with `SKIPPED_WITH_REASON` metric or report fields. H01 supersedes it as suspect historical input; H02 should make that fail-closed behavior reusable as the ordinary final acceptance gate.

## Design Findings

`scripts/m1h/assert_final_milestone1_hardened.py` is too thin for H02. It only counts manifest claims marked `required_for_milestone_pass` and permits `PASS` when `status == PASS` and `evidence_kind` is in `ALLOWED_PASS_KINDS`. It does not independently enforce the exact 29 C04 claim ids, C03 claim-ledger shape, PASS semantic checks, fixture-source exclusion, blocked-reason presence, or count consistency.

The final gate currently returns gate status `BLOCKED_WITH_REASON` when the milestone is blocked. The H02 stage command is specified without `--allow-blocked`, and the architecture says hardening can PASS while milestone acceptance remains blocked. Therefore H02 should make the gate result status represent harness correctness, not milestone completion: malformed or unsafe acceptance is `FAIL`; honest blocked milestone acceptance is a gate `PASS` with `milestone1_status: BLOCKED_WITH_REASON` in the payload.

`scripts/m1h/assert_stage_exit.py` is stage-aware only for H00 and H01. H02 currently falls back to the H00 gate list and does not require `assert_final_milestone1_hardened.json`, an H02 C03 acceptance artifact, or H02-specific no-legacy validation. This is the main stage-exit gap.

`scripts/assert_milestone1_acceptance.py` is now routed through the hardening manifest, but H02 should avoid a second acceptance implementation drifting from `assert_final_milestone1_hardened.py`. The safest design is one shared C03 acceptance builder/validator used by both the legacy wrapper and the final hardening gate.

## Implementation Recommendations

1. Generalize the H01 acceptance reset builder into a reusable acceptance report builder.
   - Keep `build_acceptance_reset.py` compatible for H01.
   - Add a reusable function such as `build_acceptance_report(root, manifest_path, stage_id, artifact_type)` or extend `build_acceptance_reset(...)` with H02-safe defaults.
   - H02 should write a current C03 artifact, for example:
     `runs/m1-hardening/H02_ACCEPTANCE_GATE_FAIL_CLOSED/artifacts/milestone1_acceptance_report.json`.

2. Strengthen PASS promotion in the shared builder.
   - Require the exact C04 required id set, not merely whatever claims are present.
   - A required claim can pass only when:
     `status == PASS`,
     `evidence_kind` is `REAL_EXACT_SCALE` or `M1_FORMAT_RECONSTRUCTED_FROM_REAL_RAW`,
     `semantic_checks.m1_format_fields_complete is true`,
     `semantic_checks.hardening_stage_accepted is true`,
     `semantic_checks.exact_scale_observed is true`,
     no `source_artifacts` path is under `tests/fixtures`,
     and all capability-required semantic checks from `CAPABILITY_REQUIRED_CHECKS` are true.
   - Any required claim attempting PASS without those properties should be `FAIL`, not blocked.
   - Any non-PASS required claim must be `BLOCKED_WITH_REASON` with a non-empty reason.

3. Rewrite `assert_final_milestone1_hardened.py` around the C03 acceptance artifact.
   - Build or read the H02 acceptance report.
   - Validate C03 fields, count consistency, all 29 C04 claims, blocked reasons, and PASS promotion semantics.
   - Write `runs/m1-hardening/H02_ACCEPTANCE_GATE_FAIL_CLOSED/artifacts/gates/assert_final_milestone1_hardened.json`.
   - Gate result `status` should be `PASS` when `hardening_loop_status: PASS`, even if `milestone1_status: BLOCKED_WITH_REASON`.
   - Gate result `status` should be `FAIL` for malformed ledgers, missing C04 claims, non-promotable PASS, fixture-backed PASS, legacy-only PASS, skipped-core-metric PASS, or count mismatch.

4. Make `scripts/assert_milestone1_acceptance.py` a compatibility wrapper only.
   - It should call the same acceptance builder/validator as the final gate.
   - It should not maintain separate fixture, non-empty, or legacy compatibility acceptance logic.
   - `--allow-blocked` may remain for CI compatibility, but it must never convert blocked claims into milestone PASS.

5. Update `assert_no_legacy_m1_pass.py` defaults or H02 gate invocation.
   - H02 should validate the H02 acceptance artifact as current acceptance.
   - The old M1-S09 report should remain a historical input only when listed in `supersedes`.
   - Prefer adding H02 to the default stage mapping so the common command works without bespoke arguments:
     `python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED`.

6. Extend `assert_stage_exit.py` for H02.
   - Add an H02 required gate list including:
     `build_evidence_manifest`,
     `assert_evidence_taxonomy`,
     `assert_final_milestone1_hardened`,
     `assert_no_fixture_fallback`,
     `assert_no_legacy_m1_pass`,
     `assert_no_simulated_subagents`.
   - Require the H02 C03 acceptance report artifact.
   - Validate the H02 report with the same reusable C03/C04 semantic validator.
   - Continue to require agent artifacts, review `Decision: PASS`, and PASS gate result JSON.

7. Add focused regression tests.
   - Empty manifest or missing C04 claim cannot produce milestone PASS.
   - All-blocked manifest with reasons produces gate `PASS`, `milestone1_status: BLOCKED_WITH_REASON`, and exit 0 for the H02 final gate.
   - Allowed evidence kind without `exact_scale_observed`, complete M1 fields, or hardening acceptance fails.
   - `REAL_EXACT_SCALE` PASS with fixture source fails.
   - `LEGACY_EVIDENCE_ONLY`, `FIXTURE_ONLY`, `DRY_RUN_ONLY`, `REAL_SMALL_SMOKE`, `INVALID`, and `BLOCKED_WITH_REASON` cannot pass required claims.
   - H02 stage exit fails until the final gate result, C03 acceptance artifact, H02 agent artifacts, and review PASS exist.

## Recommended H02 Gate Sequence

```text
PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache python3 -m compileall -q scripts src tests
PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h
python3 scripts/m1h/build_evidence_manifest.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED --out runs/m1-hardening/evidence_manifest.json
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED
python3 scripts/m1h/assert_final_milestone1_hardened.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED
python3 scripts/m1h/assert_stage_exit.py --stage H02_ACCEPTANCE_GATE_FAIL_CLOSED
```

Worker handoff may use `assert_stage_exit.py --allow-blocked` only before worker/review artifacts exist. After review writes `Decision: PASS`, the final stage-exit command above must exit 0 without `--allow-blocked`.

## Acceptance Criteria

H02 is complete only when a current H02 C03 claim ledger exists, all 29 C04 claims are represented, the final hardening gate exits 0 while keeping the milestone blocked with reasons, and no fixture, legacy-only, skipped metric, shallow non-empty, invalid, or blocked evidence can promote a required claim to milestone PASS.
