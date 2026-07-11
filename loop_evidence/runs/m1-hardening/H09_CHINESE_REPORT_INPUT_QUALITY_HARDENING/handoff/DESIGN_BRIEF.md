role: design
agent_invocation: real_subagent
stage_id: H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING
source_commit_before: 1248c98c4eb68deeb446e06ef06586b92aadcbca
source_commit_after: MISSING

# H09 Design Brief

## Scope

H09 must harden Chinese offline report acceptance without turning rendering success into milestone evidence. The current code path treats `report` as a generic capability with weak checks in `scripts/m1h/manifest.py`: `report_index_present` may be true while `accepted_inputs_only` is always false, and `scripts/m1h/assert_report_input_quality.py` is only the generic capability wrapper. Current report claims are correctly blocked, but the system does not yet prove that a crafted report PASS would be rejected.

The design is to make report acceptance two-status:

- `render_status`: whether Markdown, HTML, CSV, SVG, and index artifacts were produced.
- `source_quality_status`: whether the report is backed by accepted M1H exact-scale source claims and source refs.

Only `source_quality_status: PASS` may make `report.real_exact.<scale>` pass. `render_status: PASS` alone must never promote a report claim.

## Manifest Design

Update `scripts/m1h/manifest.py` so report claims are evaluated with a report-specific evaluator instead of the current `report_index_present` plus `accepted_inputs_only: False` stub.

Use a two-pass manifest build:

1. Build all non-report claims and keep them in a claim ledger keyed by `(capability, scale)`.
2. Evaluate report claims using the rendered report artifacts plus the already computed source claim ledger.
3. Preserve cleanup claims with the existing logic.

Required report semantic checks:

- `exact_scale_observed`: report index scale or node_count equals the required scale, and source claim refs match that scale.
- `report_index_present`: non-fixture `report_index.json` exists.
- `render_status_pass`: report index rendering status is `PASS`.
- `offline_policy_valid`: exact offline policy is present: `artifact_only: true`, `llm_used: false`, `external_urls_allowed: false`, `cdn_allowed: false`, `online_chart_service_allowed: false`.
- `required_sections_present`: setup, command audit, management, workload, fault, system metrics, cleanup, missing metrics, offline policy, and source refs are represented in the index and views.
- `section_source_refs_resolve`: every required chart/table/export/report section has non-empty source refs that resolve to versioned artifacts.
- `accepted_m1h_source_claims_cited`: exact-scale report PASS cites accepted M1H source claims, not just artifact paths.
- `blocked_source_claims_preserved`: any blocked setup, command, management, workload, fault, system, or cleanup source claim keeps the report source quality blocked with reasons.
- `no_fixture_report_sources`: neither report artifacts nor cited source refs use `tests/fixtures` for milestone report PASS.
- `no_legacy_report_sources`: legacy-only artifacts cannot satisfy source-quality PASS.
- `report_source_quality_diagnostics_present`: report claims include machine-readable diagnostics sufficient for the H09 gate to audit them.
- `accepted_inputs_only`: true only when all source-quality checks pass.
- `m1_format_fields_complete`: all report checks above are true.
- `hardening_stage_accepted`: equal to the report evaluator's `accepted` field.

Scale dependency map:

- scale 30: require accepted `setup_telemetry`, `workload_benchmark`, `system_metrics`, and `cleanup` claims at scale 30. Command, management, and fault sections may be present as `SKIPPED_WITH_REASON` or `MISSING` with reasons, because those exact-scale capability claims are not required at scale 30.
- scales 50, 100, 200: require accepted `setup_telemetry`, `command_audit`, `management_matrix`, `workload_benchmark`, `fault_timeline`, `system_metrics`, and `cleanup` claims for the same scale.

If any required dependency claim is `BLOCKED_WITH_REASON`, the report claim must be:

- `status: BLOCKED_WITH_REASON`
- `evidence_kind: BLOCKED_WITH_REASON`
- `reason`: cites every blocked dependency claim id and reason
- `diagnostics.report_h09_acceptance.accepted: false`
- `diagnostics.report_h09_acceptance.render_status: PASS` if rendering succeeded
- `diagnostics.report_h09_acceptance.source_quality_status: BLOCKED_WITH_REASON`

If a report index says `status: PASS` but lacks accepted source claim refs or cites blocked dependencies, the claim remains blocked. If it asserts source quality without diagnostics, the H09 gate fails.

## Report Index And Renderer Design

Keep existing offline report generation. Do not make network calls and do not rerun source scenarios.

Add or normalize these report-index fields in `src/valkey_scale_lab/report/render.py` and `src/valkey_scale_lab/report/final.py`:

- `status`: rendering status only, kept for backward compatibility.
- `render_status`: explicit rendering status.
- `source_quality_status`: `PASS`, `BLOCKED_WITH_REASON`, or `FAIL`.
- `milestone_eligible`: boolean, true only when `source_quality_status` is `PASS`.
- `offline_policy`: exact C11/C12 offline policy object.
- `source_quality`: object with `required_source_claims`, `accepted_source_claims`, `blocked_source_claims`, `source_claim_refs`, `source_artifact_refs`, and `reasons`.
- `required_sections`: object or array covering setup, command audit, management, workload, fault, system metrics, cleanup, missing metrics, offline policy, and source refs. Each section has `status`, `reason` when not PASS, and `source_refs`.
- `view_sources`: mapping for every generated CSV, SVG, Markdown, and HTML view to the artifact refs used to derive it.

The Markdown and HTML outputs should include visible Chinese sections for:

- offline policy and derivation rules
- source artifact refs
- setup inputs
- command audit inputs
- management inputs
- workload inputs
- fault/failover inputs
- system metrics inputs
- cleanup inputs
- missing metrics and skipped values

Existing `SKIPPED_WITH_REASON` rendering is acceptable for unavailable sections, but the reason must be explicit and the section must not be counted as source-quality PASS.

## Dedicated H09 Gate Design

Replace `scripts/m1h/assert_report_input_quality.py` with a dedicated gate, not the generic capability wrapper. The gate should return PASS when the hardening rules are enforced, even if current report source-quality claims are honestly blocked.

Gate algorithm:

1. Load `runs/m1-hardening/evidence_manifest.json`.
2. Collect all report claims for scales 30, 50, 100, and 200.
3. For each report claim, require valid H09 diagnostics under `diagnostics.report_h09_acceptance`.
4. Re-read cited report indexes from `source_artifacts`; do not trust manifest booleans alone.
5. Validate render/source split:
   - `render_status_pass` may be true from report index rendering status.
   - `accepted_inputs_only` and `source_quality_status: PASS` require accepted source claim refs.
6. Validate dependency claims in the same manifest:
   - every cited source claim exists;
   - required dependencies for that scale are present;
   - a report PASS may cite only dependency claims whose `status` is `PASS`, whose evidence kind is allowed, and whose semantic checks are complete;
   - blocked dependency claims force report source quality to `BLOCKED_WITH_REASON`.
7. Validate report index contents:
   - exact offline policy;
   - required sections;
   - source refs for every chart/table/export/view;
   - refs resolve and are not fixture-only or legacy-only for milestone PASS.
8. Reject crafted manifest report PASS:
   - report claim `status: PASS` with no `diagnostics.report_h09_acceptance` is a FAIL;
   - report claim `status: PASS` where diagnostics do not cite accepted source claims is a FAIL;
   - report claim `status: PASS` while any dependency claim is blocked is a FAIL;
   - report claim `status: PASS` backed only by `report_index.json`, `report.md`, or `index.html` is a FAIL.
9. Emit `runs/m1-hardening/H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING/artifacts/gates/assert_report_input_quality.json` with `status: PASS` only when the checker found no violations. Current blocked report claims should appear in `extra.blocked_report_claims`, not as gate failure.

Recommended violation codes:

- `report_pass_without_h09_diagnostics`
- `report_pass_without_accepted_source_claims`
- `report_pass_with_blocked_source_claim`
- `report_render_pass_promoted_to_source_quality`
- `report_offline_policy_invalid`
- `report_required_section_missing`
- `report_view_source_ref_missing`
- `report_source_ref_unresolved`
- `report_fixture_source_promoted`
- `report_legacy_source_promoted`
- `report_scale_mismatch`

## Stage Exit Integration

Update `scripts/m1h/assert_stage_exit.py`:

- Add `H09_REQUIRED_GATE_RESULTS`.
- Add `H09_CHINESE_REPORT_INPUT_QUALITY_HARDENING` to `STAGE_REQUIRED_GATE_RESULTS`.
- Require `assert_report_input_quality.json` alongside common gates.

This makes H09 impossible to complete with only the generic gates.

## Tests

Add focused tests in `tests/m1h/test_gate_framework.py` or a new `tests/m1h/test_report_input_quality.py`:

- valid blocked current state: report index render PASS plus blocked source claims yields report claim `BLOCKED_WITH_REASON`, not gate failure.
- all dependencies accepted: exact-scale report claim may pass only when report index cites accepted source claims and required sections/source refs/offline policy are valid.
- blocked setup/workload/fault/system source claim: report source quality remains `BLOCKED_WITH_REASON` and reason cites the blocked claim.
- crafted manifest PASS without H09 diagnostics is rejected by the dedicated gate.
- crafted manifest PASS with diagnostics but no accepted source claim refs is rejected.
- report index `status: PASS` with missing or bad offline policy is rejected.
- fixture-backed or legacy-backed report source refs cannot satisfy report PASS.
- required report section missing or view source ref missing is rejected.
- H09 stage exit blocks when `assert_report_input_quality.json` is absent and passes once present.

Fixtures may be used for unit tests only. They must never become accepted exact-scale source claims.

## Expected Current Outcome After Worker Implementation

Given the current manifest, H09 should likely produce:

- hardening gate status: `PASS`, because the gate proves render PASS cannot promote weak input quality.
- report claims: still `BLOCKED_WITH_REASON` until setup, command, management, workload, fault, system, and cleanup dependencies are accepted for the relevant scales.
- milestone status: still blocked, not PASS.

That outcome is correct. The important H09 success condition is fail-closed source-quality enforcement, not inventing or manufacturing report evidence.
