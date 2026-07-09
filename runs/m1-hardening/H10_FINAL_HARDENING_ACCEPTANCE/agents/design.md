role: design
agent_invocation: real_subagent
stage_id: H10_FINAL_HARDENING_ACCEPTANCE
source_commit_before: e9fc1d44a640b93ed777e400d447fc7d15018f31
source_commit_after: MISSING

# H10 Design Brief

## Read Scope

Read `codex_goal_loop_m1_hardening_v2/prompts/DESIGN_SUBAGENT_PROMPT.md`, `START_HERE.md`, `AGENTS_M1H_V2.md`, `docs/00_INDEX.md`, all indexed docs `01` through `19`, contracts `C00` through `C12`, `stages/H10_FINAL_HARDENING_ACCEPTANCE.md`, current H10 `CONTEXT_RELOAD.md`, H09 review/completion handoff, and the current final acceptance and stage-exit implementation.

Current code targets inspected:

- `scripts/m1h/assert_final_milestone1_hardened.py`: `evaluate_final(...)` at lines 18-60 and CLI output default at lines 76-110.
- `scripts/m1h/build_acceptance_reset.py`: shared C03 builder/validator at lines 18-95 and 98-245.
- `scripts/m1h/assert_stage_exit.py`: required gate lists at lines 15-105, required artifacts at lines 123-136, stage-specific artifact checks at lines 159-166, and gate-result validation at lines 244-264.
- `tests/m1h/test_gate_framework.py`: final gate tests at lines 144-165, H02 stage-exit tests at lines 384-409, and stage-exit helpers at lines 2280-2325.

## Required H10 Behavior

The final acceptance artifact must be:

`runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/artifacts/milestone1_hardened_acceptance.json`

The gate result must remain:

`runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/artifacts/gates/assert_final_milestone1_hardened.json`

The likely correct outcome for the current repository is:

- `hardening_loop_status: PASS`
- `milestone1_status: BLOCKED_WITH_REASON`
- `false_pass_prevented: true`

Only if every C04 required exact-scale claim passes with promotable evidence and all semantic checks pass may `milestone1_status` become `PASS`. Any blocked, failed, missing, fixture-only, legacy-only, dry-run-only, small-smoke-only, fake/PARTIAL, skipped-core, or rendered-only evidence path must keep milestone1 blocked or failed.

## Implementation Targets

1. Update `scripts/m1h/assert_final_milestone1_hardened.py`.
   - Change the H10 default output path to `artifacts/milestone1_hardened_acceptance.json` when `--stage H10_FINAL_HARDENING_ACCEPTANCE` and `--out` is not supplied.
   - Use `artifact_type="milestone1_hardened_acceptance"` for H10, while preserving the existing `milestone1_acceptance_report` behavior for H02 and compatibility callers.
   - Keep the existing C03 fields and add the C19 lists required by `docs/19_FINAL_HANDOFF_CONTRACT.md`: `required_claims`, `passed_claims`, `blocked_claims`, `failed_claims`, `fixture_only_claims`, and `legacy_only_claims`.
   - Ensure `evaluate_final(...)` validates against the H10 artifact type and returns gate `PASS` for an honest blocked milestone only when `hardening_loop_status` is `PASS`, `milestone1_status` is `PASS` or `BLOCKED_WITH_REASON`, and there are zero validation/build violations.
   - Do not introduce a second acceptance algorithm. Reuse `build_acceptance_reset(...)` and `validate_acceptance_report(...)` so H02 and H10 cannot drift.

2. Update `scripts/m1h/build_acceptance_reset.py`.
   - Add optional final-list enrichment, either inside the builder for all acceptance artifacts or via a small helper used by H10.
   - The list fields should be derived from the claim ledger, not hand-authored:
     - `required_claims`: all C04 required claim ids.
     - `passed_claims`: claims whose `acceptance_status` is `PASS`.
     - `blocked_claims`: blocked claims with id and reason, preserving exact missing evidence.
     - `failed_claims`: failed claims with id and reason.
     - `fixture_only_claims`: claims whose source evidence kind or acceptance evidence kind is `FIXTURE_ONLY`.
     - `legacy_only_claims`: claims whose evidence kind is `LEGACY_EVIDENCE_ONLY`.
   - Preserve fail-closed PASS validation in `_failed_pass_checks(...)`: promotable kind only, exact scale, M1 fields complete, hardening stage accepted, capability checks true, no fixture paths, and no skipped or missing semantic values.

3. Update `scripts/m1h/assert_stage_exit.py`.
   - Add `H10_REQUIRED_GATE_RESULTS` with `build_evidence_manifest`, `assert_evidence_taxonomy`, `assert_final_milestone1_hardened`, `assert_no_fixture_fallback`, `assert_no_legacy_m1_pass`, and `assert_no_simulated_subagents`.
   - Register `H10_FINAL_HARDENING_ACCEPTANCE` in `STAGE_REQUIRED_GATE_RESULTS`; do not let H10 fall back to H00.
   - Add `H10_REQUIRED_ACCEPTANCE_ARTIFACTS = ["artifacts/milestone1_hardened_acceptance.json"]`.
   - Add `_validate_h10_hardened_acceptance(...)`, parallel to `_validate_h02_acceptance_report(...)`, calling `validate_acceptance_report(...)` with `expected_stage_id="H10_FINAL_HARDENING_ACCEPTANCE"` and `expected_artifact_type="milestone1_hardened_acceptance"`.
   - Enforce C19 fields and current expected honest result:
     - `hardening_loop_status` must be `PASS`.
     - `milestone1_status` may be `PASS` only when `blocked_claim_count == 0`, `failed_claim_count == 0`, and `passed_claim_count == required_claim_count`.
     - `milestone1_status` must be `BLOCKED_WITH_REASON` when blocked claims exist.
     - `false_pass_prevented` must be true for blocked/failed milestone outcomes.
     - all C19 claim-list fields must exist and their counts must match the ledger.
   - Continue requiring role artifacts and `Decision: PASS` review before stage exit can pass.

4. Update tests.
   - In `tests/m1h/test_gate_framework.py`, import `H10_REQUIRED_GATE_RESULTS`.
   - Add a final gate test proving H10 writes `milestone1_hardened_acceptance.json` with artifact type `milestone1_hardened_acceptance`, current honest blocked milestone status, and the C19 list fields.
   - Add a crafted all-claims-pass test showing milestone PASS is possible only when every required claim has promotable evidence and all capability semantic checks required by `CAPABILITY_REQUIRED_CHECKS` are true.
   - Add regression tests that H10 rejects:
     - a milestone PASS with any blocked required claim;
     - a PASS claim backed by `FIXTURE_ONLY` or a `tests/fixtures` path;
     - a PASS claim backed only by `LEGACY_EVIDENCE_ONLY`;
     - a real PASS with a skipped or missing core semantic check;
     - a report PASS with rendered-only source quality.
   - Add `test_h10_stage_exit_requires_final_gate_and_hardened_acceptance_artifact`, mirroring the H02 stage-exit test but requiring `milestone1_hardened_acceptance.json`.

## Required Gate Commands

Worker/main should run at minimum:

```text
python3 -m compileall -q scripts src tests
python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h
python3 scripts/m1h/build_evidence_manifest.py --stage H10_FINAL_HARDENING_ACCEPTANCE --out runs/m1-hardening/evidence_manifest.json
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H10_FINAL_HARDENING_ACCEPTANCE
python3 scripts/m1h/assert_final_milestone1_hardened.py --stage H10_FINAL_HARDENING_ACCEPTANCE
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H10_FINAL_HARDENING_ACCEPTANCE
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H10_FINAL_HARDENING_ACCEPTANCE
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H10_FINAL_HARDENING_ACCEPTANCE
python3 scripts/m1h/assert_stage_exit.py --stage H10_FINAL_HARDENING_ACCEPTANCE
```

`assert_stage_exit.py` must be run once before review only as an expected blocked check for missing review artifacts, then again after the review artifact exists for the actual PASS.

## Handoff Artifacts

H10 must produce:

- `runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/artifacts/milestone1_hardened_acceptance.json`
- `runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/artifacts/gates/*.json`
- `runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/agents/design.md`
- `runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/agents/worker.md`
- `runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/agents/review.md`
- `runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/handoff/DESIGN_BRIEF.md`
- `runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/handoff/WORKER_SUMMARY.md`
- `runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/handoff/REVIEW.md`
- `runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/handoff/COMPLETION.md`
- `runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/handoff/FINAL_HANDOFF.md`
- `runs/m1-hardening/H10_FINAL_HARDENING_ACCEPTANCE/handoff/NEXT_STAGE_INPUT.md`

`FINAL_HANDOFF.md` should summarize the hardening loop result, final acceptance JSON path, exact blocked claim groups, gate commands and gate result paths, commit/push status, and manual rerun notes for exact-scale evidence. It must not act as proof; the JSON and gate artifacts are the proof.

## Risks

- `assert_stage_exit.py` currently does not know H10, so without explicit registration H10 can silently fall back to the weaker H00 gate list.
- `assert_final_milestone1_hardened.py` currently defaults to `milestone1_acceptance_report.json`, which would miss the C19 final-handoff artifact path.
- Adding a new H10 artifact type can accidentally break H02 compatibility; keep artifact type selection stage-aware.
- Current manifest contains many honest blocked claims, so H10 milestone PASS would be suspicious unless every exact-scale claim is replaced by real promotable evidence.
- The stage scanner may reject forbidden role-artifact wording; keep H10 agent artifacts factual and use `agent_invocation: real_subagent`.
