# L06 Anti-Regression Report

Status: PASS

Base ref: `5c57761569d8322e3ee057afb2f15b2cfef849d7`

The automated anti-regression check reported zero findings in `anti_regression_check.json`.

Reviewed controlled changes:

- Added `scripts/audit_small_real_scenario_parity.py`.
- Added `schemas/artifact/small_real_parity_audit.schema.json`.
- Added focused L06 audit, coverage, report, real-evidence contract, and CI tests.
- Added the small-real parity gate to `.github/workflows/github-coverage-gates.yml`.
- Updated `scripts/render_audit_report.py` to treat `small_real_parity_audit.json` as a source artifact.
- Regenerated loop report artifacts from JSON source artifacts.

No existing gate was downgraded, no P14 opt-in guard was removed, no required artifact was made optional, no node-count requirement was lowered, and no historical gate result was rewritten to hide a failure.
