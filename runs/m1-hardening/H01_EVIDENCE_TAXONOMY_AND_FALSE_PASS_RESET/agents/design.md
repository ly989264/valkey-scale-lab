# H01 Design Subagent Artifact

role: design
agent_invocation: real_subagent
stage_id: H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET
source_commit_before: c6e5fcdb18b1d4960c613f84a53b8c90109cc019

## Documents Read

- `runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/handoff/CONTEXT_RELOAD.md`
- `runs/m1-hardening/H00_BOOTSTRAP_HARD_GATES/handoff/CONTEXT_RELOAD.md`
- `runs/m1-hardening/H00_BOOTSTRAP_HARD_GATES/handoff/DESIGN_BRIEF.md`
- `runs/m1-hardening/H00_BOOTSTRAP_HARD_GATES/handoff/WORKER_SUMMARY.md`
- `runs/m1-hardening/H00_BOOTSTRAP_HARD_GATES/handoff/REVIEW.md`
- `runs/m1-hardening/H00_BOOTSTRAP_HARD_GATES/handoff/COMPLETION.md`
- `codex_goal_loop_m1_hardening_v2/AGENTS_M1H_V2.md`
- `codex_goal_loop_m1_hardening_v2/docs/00_INDEX.md`
- `codex_goal_loop_m1_hardening_v2/docs/02_NON_NEGOTIABLE_CONTRACT.md`
- `codex_goal_loop_m1_hardening_v2/docs/03_EVIDENCE_TAXONOMY.md`
- `codex_goal_loop_m1_hardening_v2/docs/04_HARD_GATE_ARCHITECTURE.md`
- `codex_goal_loop_m1_hardening_v2/docs/09_NO_SHORTCUT_RULES.md`
- `codex_goal_loop_m1_hardening_v2/docs/10_ACCEPTANCE_MATRIX.md`
- `codex_goal_loop_m1_hardening_v2/contracts/C01_EVIDENCE_MANIFEST_SCHEMA.md`
- `codex_goal_loop_m1_hardening_v2/contracts/C03_MILESTONE_ACCEPTANCE_SCHEMA.md`
- `codex_goal_loop_m1_hardening_v2/contracts/C04_EXACT_SCALE_REQUIREMENTS.md`
- `codex_goal_loop_m1_hardening_v2/contracts/C05_STATIC_FORBIDDEN_PATTERNS.md`
- `codex_goal_loop_m1_hardening_v2/stages/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET.md`

## Inspected Implementation And Evidence

- `scripts/m1h/common.py`
- `scripts/m1h/manifest.py`
- `scripts/m1h/build_evidence_manifest.py`
- `scripts/m1h/assert_evidence_taxonomy.py`
- `scripts/m1h/assert_no_fixture_fallback.py`
- `scripts/m1h/assert_no_legacy_m1_pass.py`
- `scripts/m1h/assert_stage_exit.py`
- `scripts/m1h/capability_gate.py`
- `scripts/m1h/assert_final_milestone1_hardened.py`
- capability wrapper gates under `scripts/m1h/`
- `runs/m1-hardening/evidence_manifest.json`
- `scripts/assert_milestone1_acceptance.py`
- `runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json`

## Current State Assessment

H00 created the right fail-closed foundation, but H01 still needs to turn the deferred false PASS into an ordinary current-state reset artifact. The current generated hardening manifest has 29 required C04 claim ids and every claim is `BLOCKED_WITH_REASON`. The evidence kinds are conservative: 3 `LEGACY_EVIDENCE_ONLY`, 2 `FIXTURE_ONLY`, 23 `INVALID`, and 1 `BLOCKED_WITH_REASON`. No claim currently promotes to PASS.

The old M1-S09 report remains unsafe as an acceptance authority. It says `milestone1_status: PASS`, reports `cross_scenario_coverage: PASS` from fixtures, lists fixture sources as `PASS`, and allows heavy rungs to PASS even when per-rung `metrics` or `report` are `SKIPPED_WITH_REASON`. It should be preserved only as a suspect historical input.

The legacy acceptance script still contains the concrete false-PASS mechanisms:

- `scripts/assert_milestone1_acceptance.py:80-86` falls back to management fixtures and passes on non-empty matrix/command data.
- `scripts/assert_milestone1_acceptance.py:94-95` passes fault/failover on non-empty events/report/samples.
- `scripts/assert_milestone1_acceptance.py:102-106` falls back to workload fixtures and passes on non-empty windows/metrics.
- `scripts/assert_milestone1_acceptance.py:144-161` makes fixture scale coverage a PASS category.
- `scripts/assert_milestone1_acceptance.py:247-260` treats parseable metric/report files as sufficient for full-flow rung PASS.
- `scripts/assert_milestone1_acceptance.py:274-275` records `SKIPPED_WITH_REASON` metric/report fields on PASS rows.

`scripts/m1h/assert_no_legacy_m1_pass.py` correctly detects that a PASS report with fixture sources is a violation. The H00-only deferral at lines 79-88 must not continue to protect H01. For H01, the gate should PASS only because the current hardening acceptance output is blocked, not because the old report is ignored or treated as truth.

## Recommended H01 Design

H01 should introduce a generated C03-shaped reset artifact under the H01 run directory, for example:

`runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/artifacts/milestone1_acceptance_reset.json`

The artifact should be built from `runs/m1-hardening/evidence_manifest.json`, not from fixtures and not from the old M1-S09 report. It should contain:

- `hardening_loop_status: PASS`
- `milestone1_status: BLOCKED_WITH_REASON`
- `false_pass_prevented: true`
- `required_claim_count: 29`
- `passed_claim_count: 0`
- `blocked_claim_count: 29`
- `failed_claim_count: 0`
- `claims`: the required claim ids, evidence kinds, statuses, reasons, semantic checks, and source artifacts from the generated manifest
- `supersedes`: the old `runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json`
- `superseded_reason`: the old report claims PASS with fixture, legacy, skipped, and shallow-count evidence that cannot satisfy M1 hardening

This reset artifact is an acceptance output, not a milestone PASS. It should be the default H01 acceptance input for `assert_no_legacy_m1_pass.py`. The old M1-S09 report should be passed as a separate historical/suspect input and recorded in gate metadata as `superseded_inputs`; it must never be used to supply a PASS claim.

## Exact Worker Recommendations

1. Add a small generator or extend an existing final gate to write the C03 reset artifact from `runs/m1-hardening/evidence_manifest.json`.
   Recommended script name: `scripts/m1h/build_acceptance_reset.py`.
   It should also write a C00 gate result at `runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/artifacts/gates/build_acceptance_reset.json` with status `PASS` when the reset is C03-shaped and every non-PASS required claim has a reason.

2. Update `scripts/m1h/assert_no_legacy_m1_pass.py` so H01 checks the new reset artifact as the current acceptance report. Add a separate option such as `--historical-acceptance-report` for M1-S09. For H01, a historical report with `milestone1_status: PASS` and fixture sources should be recorded as superseded evidence, while a current hardening report with `milestone1_status: PASS` from fixture, legacy, dry-run, small-smoke, invalid, skipped, or blocked evidence must be a `FAIL`.

3. Ensure `assert_no_legacy_m1_pass.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET` exits 0 only when:
   - current hardening acceptance has `milestone1_status: BLOCKED_WITH_REASON`;
   - `false_pass_prevented` is true;
   - all 29 required C04 claims are represented;
   - no required claim has `status: PASS`;
   - each blocked claim has a non-empty reason;
   - any fixture or legacy source is classified as non-promotable and is not required for PASS.

4. Remove the H00-only deferral from H01 behavior. The branch at `scripts/m1h/assert_no_legacy_m1_pass.py:79-88` can stay only for `H00_BOOTSTRAP_HARD_GATES`. For H01, do not clear violations from the old report unless a valid reset artifact explicitly supersedes it.

5. Either update `scripts/assert_milestone1_acceptance.py` in H01 to generate blocked current acceptance from the hardening manifest, or quarantine it as a legacy-only producer that cannot be used by hardening gates. If it remains callable, fixture fallback paths and cross-scenario fixture PASS must not be part of any PASS-capable milestone path.

6. If common H01 gates include `assert_no_fixture_fallback.py`, fix the legacy acceptance script at the same time. The existing fixture fallback lines in `scripts/assert_milestone1_acceptance.py` will cause H01 to fail unless H01 has an explicit, tested quarantine that prevents that script from being a hardening PASS source.

7. Make `assert_stage_exit.py` stage-aware. Its current `H00_REQUIRED_GATE_RESULTS` list and required PASS status should not be hardcoded for every later stage. For H01 it should require at least:
   - `build_evidence_manifest`
   - `build_acceptance_reset`
   - `assert_evidence_taxonomy`
   - `assert_no_fixture_fallback` if part of common gates
   - `assert_no_legacy_m1_pass`
   - `assert_no_simulated_subagents`
   - `assert_stage_exit`
   It should require these gate results under the H01 stage directory and require `PASS` for the gate checks, even though the generated milestone reset itself says `BLOCKED_WITH_REASON`.

8. Add tests under `tests/m1h/` for:
   - a manifest with 29 blocked claims produces a C03 reset with milestone blocked and false pass prevented;
   - a current acceptance report with fixture-backed PASS fails;
   - the old M1-S09 report is accepted only as a superseded historical input when the current reset is blocked;
   - fixture-only and legacy-only required claims cannot increment `passed_claim_count`;
   - missing blocked reasons fail taxonomy/reset validation;
   - H01 stage exit fails without the reset gate result and passes once all required H01 gate artifacts and handoff artifacts exist.

## Gate Sequence For H01 Worker

Recommended worker sequence after implementation:

```text
PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache python3 -m compileall -q scripts src tests
PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h
python3 scripts/m1h/build_evidence_manifest.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET --out runs/m1-hardening/evidence_manifest.json
python3 scripts/m1h/build_acceptance_reset.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET --manifest runs/m1-hardening/evidence_manifest.json --out runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/artifacts/milestone1_acceptance_reset.json
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET --acceptance-report runs/m1-hardening/H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET/artifacts/milestone1_acceptance_reset.json --historical-acceptance-report runs/m1-s09-local/artifacts/goal_loop/M1-S09/milestone1_acceptance_report.json
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET
python3 scripts/m1h/assert_stage_exit.py --stage H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET
```

## Acceptance Criteria

- H01 has a current C03 acceptance reset artifact with `milestone1_status: BLOCKED_WITH_REASON`, not PASS.
- The reset artifact cites all 29 C04 claims and all missing or non-promotable evidence has reasons.
- No fixture, legacy, dry-run, invalid, small-smoke, skipped, fake/PARTIAL, or blocked evidence contributes to a PASS count.
- The old M1-S09 PASS report is explicitly superseded and recorded as suspect historical evidence.
- H01 `assert_no_legacy_m1_pass.py` passes because current hardening acceptance is blocked and false pass is prevented.
- H01 does not mark stage completion until stage-specific gate JSON, worker summary, review PASS, and stage exit all exist.

## Risks

- Treating the old M1-S09 report as the default acceptance input for H01 will make the no-legacy gate fail, correctly. The fix is not to soften the gate; it is to create and validate the current blocked reset output.
- Allowing `scripts/assert_milestone1_acceptance.py` to remain PASS-capable with fixture fallback will keep producing false confidence. Either harden it now or exclude it from hardening PASS sources with explicit gate coverage.
- The H00 manifest includes fixture paths in some `source_artifacts`. This is acceptable only while the claim is blocked or non-promotable. Any future PASS claim must use only allowed evidence kinds and complete semantic checks.
