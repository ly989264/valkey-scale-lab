# H09 Completion

stage_id: H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING
status: PASS
source_commit_before: 1248c98c4eb68deeb446e06ef06586b92aadcbca
source_commit_after: PENDING_COMMIT

## Summary

H09 hardens Chinese/final report input quality so rendered reports cannot promote milestone1 to PASS unless their report indexes cite exact-scale accepted M1H source claims and non-rendered, resolving source artifacts. Render status is treated as a view result only; source-quality acceptance is separate and fail-closed.

Current repository report claims remain `BLOCKED_WITH_REASON` because exact-scale source-quality evidence and canonical report input sections are not complete. This is the expected H09 outcome: report rendering may exist, but weak, legacy, fixture, or rendered-only inputs do not satisfy milestone evidence.

## Implemented Checks

- report claim construction now depends on `diagnostics.report_h09_acceptance.accepted: true`;
- `offline_policy` must contain the exact required artifact-only fields; `derivation_policy` fallback no longer satisfies H09;
- report PASS must cite every same-scale required source claim, and those source claims must be promotable `REAL_EXACT_SCALE` evidence;
- rendered files such as `report_index.json`, `final_report_index.json`, `report.md`, and `index.html` cannot be the only report source backing;
- canonical report input sections now include setup, command audit, management, workload, fault timeline, system metrics, cleanup, and missing metrics inputs;
- required report sections must contain non-rendered source refs that resolve from the repository or report index directory;
- fixture and legacy report source refs remain blocked;
- `assert_report_input_quality.py` rejects crafted PASS claims without H09 diagnostics or with blocked dependencies.

## Gates

- `python3 -m pytest -q tests/m1h/test_report_input_quality.py tests/m1h/test_gate_framework.py` -> PASS, 96 passed
- `PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h09-fix python3 -m compileall -q scripts src tests` -> PASS
- `python3 -m pytest -q tests/unit tests/integration tests/ci/test_milestone1_acceptance_gate.py tests/m1h` -> PASS, 330 passed
- `python3 scripts/m1h/build_evidence_manifest.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING --out runs/m1-hardening/evidence_manifest.json` -> PASS
- `python3 scripts/m1h/assert_evidence_taxonomy.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING` -> PASS
- `python3 scripts/m1h/assert_report_input_quality.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING` -> PASS
- `python3 scripts/m1h/assert_no_fixture_fallback.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING` -> PASS
- `python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING` -> PASS
- `python3 scripts/m1h/assert_no_simulated_subagents.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING` -> PASS
- `python3 scripts/m1h/assert_stage_exit.py --stage H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING` -> PASS

## Review

Initial real review subagent returned `Decision: FAIL` and found three false-PASS risks: `derivation_policy` fallback, rendered-only report backing despite cited claims, and missing cleanup/missing-metrics sections. Those findings were fixed with stricter acceptance logic and regression tests.

Fresh real review subagent returned `Decision: PASS` and verified the prior false-PASS paths now block.

## Commit And Push

commit: PENDING_COMMIT
push: PENDING_PUSH
