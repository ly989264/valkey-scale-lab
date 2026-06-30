# L04 Stage Design

Stage: `L04_P13_P14_SCALE_AUDIT_AND_REFRESH`

## Goal

L04 adds a dedicated static audit for the scale boundary around P13 and P14:

- Canonical P13 50/100-node evidence must be non-empty, schema-valid, real-Valkey-backed, status-consistent, and tied to the committed P13 scale rung/report/timing/cleanup artifacts.
- P13 timing breakdowns must prove setup, cluster create, replica config, probe, cleanup, and accounting coverage with typed nonnegative measured durations or explicit missing/skipped semantics.
- P13 cleanup and scale ladder artifacts must be cross-consistent with the canonical P13 real evidence, not with `P13O_*` optimization artifacts.
- P13 historical gate command/manifest drift must remain explicit and nonblocking, not hidden by rewriting committed gate history or excluding P13 from scrutiny.
- P14 must remain opt-in dry-run/resource/planner only. No P14 real evidence, default gate result, or automatic 1000-node execution may be present or run by L04.

## Harness

New schema:

- `schemas/artifact/p13_p14_scale_audit.schema.json`

New static builder:

- `scripts/audit_p13_p14_scale.py --out artifacts/loop_engineering/reports/p13_p14_scale_audit.json`

New tests:

- `tests/scale/test_p13_p14_scale_audit.py`
- `tests/ci/test_p13_p14_scale_audit_gate.py`

Workflow extension:

- `.github/workflows/github-coverage-gates.yml` runs the static L04 audit builder, schema validation, and focused tests.

Generated artifact:

- `artifacts/loop_engineering/reports/p13_p14_scale_audit.json`

## Audit Invariants

P13 rung checks for both 50 and 100:

- canonical evidence path is exactly `artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_<N>.json`
- evidence validates against `schemas/artifact/valkey_e2e_evidence.schema.json`
- `phase_id=P13_SCALE_LADDER_50_100`, `scenario=scale_<N>`, `status=PASS`, `real_valkey=true`
- `nodes_observed=<N>`, `cluster_state_observed=ok`, `probe_result=PASS`, `data_path_result=PASS`
- all `valkey_versions` start with `9.1.`
- probes are nonempty and every probe status is PASS
- evidence cleanup status is PASS and points at a committed P13 cleanup report
- canonical scale rung has `node_count=<N>`, status PASS, and evidence_path equal to the canonical evidence path
- timing breakdown validates against `schemas/artifact/p13_timing_breakdown.schema.json`, has `node_count=<N>`, status PASS, and covers setup/process, cluster create, replica config, probe, cleanup, and accounting categories
- cleanup report has status PASS, empty `resources_remaining`, and nonempty cleanup actions

P13 report/gate checks:

- `scale_ladder_report.json` contains exactly rungs 50 and 100, status PASS, comparison from 50 to 100, node_count_multiplier 2.0, and canonical P13 real evidence paths.
- P13 `gate_result.json` remains present and status PASS. The known `scale_tests` command mismatch and legacy manifest hash drift are classified as historical nonblocking, but unexpected P13 gate drift is blocking.
- `audit/P13_SCALE_LADDER_50_100/audit_decision.json` remains present and PASS.
- `P13O_*` optimization artifacts are reported separately and never counted as canonical P13 50/100 evidence.

P14 boundary checks:

- Manifest entry for `P14_SCALE_1000_OPTIN_DRYRUN` has `automatic=false`, `real_valkey_required=false`, and `max_nodes=1000`.
- P14 gates are planner/resource/dry-run style with `real_valkey=false`, `--dry-run`, and opt-in environment requirements.
- `templates/configs/scale_1000_dryrun_optin.yaml` remains dry-run-only and requires `VSLAB_ALLOW_1000_DRYRUN`.
- No `artifacts/gates/P14_SCALE_1000_OPTIN_DRYRUN/gate_result.json` or `artifacts/phases/P14_SCALE_1000_OPTIN_DRYRUN/valkey_e2e_evidence*.json` is present by default.
- Existing `artifacts/phases/P02_PLANNER/scale_1000_dryrun_plan.json` is allowed only as dry-run planner evidence with `dry_run/no_execution/opt_in_1000=true` and `default_node_cap=100`.

## Non-Goals

- Do not rerun P13 real wrappers unless a later explicit refresh is required and fully recorded.
- Do not run P14 dry-run or real execution.
- Do not rewrite historical P13 gate, phase, or audit artifacts to make compatibility pass.

## Acceptance

- Previous harness remains PASS.
- L04 audit artifact validates against its schema and has status PASS with zero blocking findings.
- L04 tests prove P13 50/100 real evidence, timing, cleanup, scale report, historical drift, P13O separation, and P14 dry-run invariants.
- CI workflow includes only static L04 audit commands and remains free of P14 opt-in execution or real/fault wrapper commands.
- `commands.jsonl` contains no P14 execution, no `VSLAB_ALLOW_1000_DRYRUN` assignment, and no real/fault wrapper invocation by L04.
