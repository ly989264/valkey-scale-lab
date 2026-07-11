role: review
agent_invocation: real_subagent
stage_id: H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING
source_commit_before: 1248c98c4eb68deeb446e06ef06586b92aadcbca
source_commit_after: MISSING

# H09 Review

Decision: PASS

## Findings

No blocking findings.

The prior FAIL findings are fixed:

- Invalid `derivation_policy` fallback no longer satisfies the offline contract. `scripts/m1h/manifest.py` now requires an explicit `offline_policy` object with the exact H09 fields, and `tests/m1h/test_report_input_quality.py::test_report_input_quality_rejects_derivation_policy_without_exact_offline_policy_for_pass` covers the crafted fallback case.
- A report PASS backed only by rendered report/index files is now rejected even when accepted claim ids are cited. `scripts/m1h/manifest.py` filters rendered refs out of source acceptance, requires non-rendered source refs for every required report input section, and `scripts/m1h/assert_report_input_quality.py` rejects report-only backing from both claim diagnostics and re-read report indexes. The regression is covered by `test_report_input_quality_rejects_rendered_files_as_only_source_refs_for_pass`.
- `cleanup_report_inputs` and `missing_metrics_report_inputs` are now part of `H09_CANONICAL_REPORT_INPUT_KEYS`; report acceptance requires those sections and resolving source refs. The positive test fixture now writes setup, command audit, management, workload, fault, system metrics, cleanup, and missing-metrics inputs.

## Gate And Artifact Evidence

- Re-ran `python3 -m pytest -q tests/m1h/test_report_input_quality.py tests/m1h/test_gate_framework.py`: 96 passed.
- Re-ran `PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h09-fix python3 -m compileall -q scripts src tests`: exit 0.
- Re-ran `python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h`: 330 passed.
- Verified `runs/m1-hardening/H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING/artifacts/gates/build_evidence_manifest.json`: `PASS`, 0 violations.
- Verified `runs/m1-hardening/H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING/artifacts/gates/assert_evidence_taxonomy.json`: `PASS`, 0 violations, 29 blocked required claims recorded.
- Verified `runs/m1-hardening/H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING/artifacts/gates/assert_report_input_quality.json`: `PASS`, 0 violations, 4 blocked report claims, 0 passed report claims.
- Verified `runs/m1-hardening/H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING/artifacts/gates/assert_no_fixture_fallback.json`: `PASS`, 0 violations.
- Verified `runs/m1-hardening/H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING/artifacts/gates/assert_no_legacy_m1_pass.json`: `PASS`, 0 violations, 47 blocked legacy/non-promotable contexts recorded.
- Verified `runs/m1-hardening/H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING/artifacts/gates/assert_no_simulated_subagents.json`: `PASS`, 0 violations.

`runs/m1-hardening/evidence_manifest.json` contains 29 claims. All four H09 report claims remain honest `BLOCKED_WITH_REASON` claims:

- `report.real_exact.30`: no report index, source quality not accepted.
- `report.real_exact.50`: render status is PASS, but exact offline policy, required sections, resolving source refs, and accepted source-claim citations are not sufficient.
- `report.real_exact.100`: same blocked H09 source-quality state.
- `report.real_exact.200`: same blocked H09 source-quality state.

This is the correct H09 result: report rendering may succeed, but source-quality PASS is not promoted from weak inputs.

## Review Notes

- Inspected `git status --short` and `git diff --stat`; dirty changes are explained by the H09 implementation, tests, manifest, and H09 artifacts.
- Read the required M1 hardening prompt, start, agent rules, indexed docs/contracts, H09 stage file, H09 design/worker artifacts, gate scripts, tests, gate results, and current evidence manifest.
- The review did not rerun the mutating gate commands because this review agent's write scope is limited to the two review artifacts; their existing JSON results were read and checked instead.

## Residual Risks

- Current exact-scale report source-quality claims are still blocked until upstream exact-scale setup, command audit, management, workload, fault, system metrics, cleanup, and report-index inputs are strengthened.
- H09 final stage exit still needs the main agent to run after this review artifact exists, then commit and push according to the loop protocol.
