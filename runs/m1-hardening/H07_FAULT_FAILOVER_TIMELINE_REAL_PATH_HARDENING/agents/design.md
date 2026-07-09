role: design
agent_invocation: real_subagent
stage_id: H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING
source_commit_before: 3c2579c123bf498b2a8d1ea16a6eb8e31647a720
source_commit_after: MISSING

# H07 Fault Timeline Design

## Context Summary

H07 must turn fault/failover timeline acceptance into a C09-specific, fail-closed gate. Current repository claims for `fault_timeline.real_exact.50`, `.100`, and `.200` should remain `BLOCKED_WITH_REASON` unless a same-run M1-format evidence bundle proves real Valkey 9.1.x fault/failover execution at the exact scale.

Current state inspected:

- `scripts/m1h/assert_fault_timeline_real.py` is still the generic capability wrapper.
- `scripts/m1h/manifest.py` uses shallow fault checks: an exact-scale heuristic, any fault-named file, any fault JSONL row or `fault_sequence.json`, and a path-name fake/PARTIAL guard.
- `hardening_stage_accepted` is never true for fault timeline claims, so current claims are blocked, but the blocked reasons are too generic and would not catch many unsafe future PASS paths.
- Existing 50/100/200 fault directories contain real Valkey evidence, fault matrix rows, command logs, workload impact, cleanup reports, and legacy failover samples, but they do not contain a complete C09 bundle with `fault_timeline_report.json`, `fault_timeline_events.jsonl`, and `failover_latency_samples.jsonl` for each exact scale.
- P20/P21 failover curve artifacts are historical latency evidence, not complete exact-scale C09 timeline bundles, and must not satisfy H07.

## Proposed Code Changes

1. Add C09 constants and fault-specific checks in `scripts/m1h/manifest.py`.

   Add canonical required fault types:

   - `primary_stop_failover`
   - `replica_stop`
   - `node_host_stop`
   - `az_stop`
   - `network_delay`
   - `network_loss`
   - `network_flap`
   - `network_partition`
   - `minority_partition`
   - `majority_partition`
   - `split_brain_window_detection`
   - `fault_period_workload_impact`

   Add canonical timeline events using schema names:

   - `fault_planned`
   - `fault_apply_started`
   - `fault_apply_completed`
   - `fault_effect_observed`
   - `cluster_impact_started`
   - `failover_started`
   - `promotion_observed`
   - `cluster_recovered`
   - `workload_recovered`
   - `fault_clear_started`
   - `fault_clear_completed`
   - `cleanup_verified`

   Add required numeric metrics:

   - `apply_duration_ms`
   - `effect_observed_delay_ms`
   - `cluster_impact_ms`
   - `failover_latency_ms`
   - `promotion_latency_ms`
   - `client_unavailability_ms`
   - `workload_recovery_ms`
   - `clear_duration_ms`
   - `cleanup_duration_ms`
   - `split_brain_window_ms`
   - `cluster_down_window_ms`

2. Replace the fault entry in `CAPABILITY_REQUIRED_CHECKS`.

   Required checks should include:

   - `real_valkey_verified`
   - `exact_scale_observed`
   - `valkey_9_1_verified`
   - `real_valkey_exact_scale`
   - `fault_bundle_same_directory`
   - `fault_timeline_report_present`
   - `fault_timeline_report_schema_valid`
   - `fault_timeline_report_status_pass`
   - `required_fault_types_present`
   - `required_scale_rung_exact`
   - `fault_timeline_events_present`
   - `fault_timeline_events_schema_valid`
   - `required_lifecycle_events_observed`
   - `timeline_events_status_observed`
   - `timeline_events_real_valkey`
   - `timeline_events_execution_mode_real`
   - `timeline_event_order_valid`
   - `timeline_event_refs_resolve`
   - `required_metrics_numeric`
   - `missing_metrics_empty`
   - `failover_latency_samples_present`
   - `failover_latency_samples_schema_valid`
   - `failover_samples_derived_from_timeline`
   - `failover_latency_curve_schema_valid`
   - `workload_refs_resolve`
   - `workload_refs_h06_accepted`
   - `cleanup_refs_resolve`
   - `cleanup_clean_cluster_verified`
   - `no_fixture_or_legacy_splice`
   - `fake_or_partial_not_promoted`

3. Add `evaluate_fault_timeline_claim(root, scale, paths)` in `scripts/m1h/manifest.py`.

   Evaluate one candidate directory at a time and never assemble a passing claim from multiple phases. A C09 candidate bundle should include:

   - `fault_timeline_report.json`
   - `fault_timeline_events.jsonl`
   - `failover_latency_samples.jsonl`
   - `failover_latency_curve.json` when present, validated if cited
   - `fault_workload_impact.json`
   - `workload_windows.json`
   - `cleanup_report.json`
   - `valkey_e2e_evidence.json`

   Store diagnostics under `diagnostics.fault_h07_acceptance`, for example:

   ```json
   {
     "accepted": false,
     "checks": {},
     "reasons": [],
     "report_path": ".../fault_timeline_report.json",
     "events_path": ".../fault_timeline_events.jsonl",
     "samples_path": ".../failover_latency_samples.jsonl",
     "required_fault_types": [],
     "required_events": [],
     "required_metrics": []
   }
   ```

   `_evidence_kind` should return `REAL_EXACT_SCALE` for `fault_timeline` only when `fault_h07_acceptance.accepted` is true. `hardening_stage_accepted` should also come from that diagnostic.

4. Implement C09 semantic validation.

   The evaluator should:

   - validate `fault_timeline_report.json` with `schemas/artifact/fault_timeline_report.schema.json`;
   - validate every `fault_timeline_events.jsonl` row with `schemas/artifact/fault_timeline_event.schema.json`;
   - validate every `failover_latency_samples.jsonl` row with `schemas/artifact/failover_latency_sample.schema.json`;
   - validate `failover_latency_curve.json` with `schemas/artifact/failover_latency_curve.schema.json` if referenced by the report or present in the same bundle;
   - require report `status: PASS`, each row `timeline_status: PASS`, `real_valkey: true`, and `execution_mode` not equal to fake, fixture, dry-run, legacy, or partial markers;
   - require `valkey_e2e_evidence.json` in the same directory with `status: PASS`, `real_valkey: true`, `nodes_observed == scale`, Valkey version prefix `9.1.`, `probe_result: PASS`, `cluster_state_observed: ok`, `data_path_result: PASS`, and cleanup status PASS;
   - require all 12 fault types in `observed_fault_types` and at least one report `fault_rows` entry for each required type at the exact scale;
   - require the exact scale rung in report rows and event rows, and reject 50/100/200 claims backed by smaller or larger observed node counts;
   - require each sample/fault row to have all 12 lifecycle events with `event_status: OBSERVED`, numeric `timestamp_unix_ms`, numeric `monotonic_ms`, `real_valkey: true`, and acceptable execution mode;
   - require lifecycle monotonic order per sample;
   - require every report `timeline_event_refs` value to resolve to an event row by id, line anchor, or deterministic row reference;
   - require every C09 metric in report rows to be a non-negative number, not string, bool, null, `MISSING`, `SKIPPED_WITH_REASON`, or a placeholder object;
   - require `missing_metrics` to be empty for a real PASS;
   - require `failover_latency_samples.jsonl` primary failover rows to cite timeline events and workload recovery refs, with numeric promotion, cluster recovery, read, and write unavailability fields;
   - require workload refs to resolve inside the same bundle and, for exact-scale benchmark claims, to a passed `workload_benchmark.real_exact.<scale>` H06 claim. If H06 remains blocked, the H07 fault timeline claim must stay blocked even if other fault artifacts look real;
   - require cleanup refs to resolve to a cleanup artifact with no `resources_remaining` and clean cluster evidence `status: PASS`;
   - reject fixture paths, legacy P20/P21-only latency curves, `fault_sequence.json`-only evidence, `failover_samples.jsonl` in place of M1 `failover_latency_samples.jsonl`, PARTIAL statuses, and shallow non-empty file checks.

5. Replace `scripts/m1h/assert_fault_timeline_real.py` with a dedicated H07 gate.

   Follow the H06 gate shape:

   - read `runs/m1-hardening/evidence_manifest.json`;
   - inspect required scales `{50, 100, 200}`;
   - return gate `status: PASS` when all fault claims either pass C09 or are explicitly blocked with H07 diagnostics;
   - reject any `fault_timeline` PASS without `REAL_EXACT_SCALE`, full semantic checks, `diagnostics.fault_h07_acceptance.accepted: true`, same-directory M1 bundle refs, and no fixture/legacy/PARTIAL source;
   - require blocked claims to name missing timeline report, event JSONL, latency samples, numeric metrics, workload refs, cleanup refs, Valkey 9.1.x proof, or exact-scale proof;
   - write gate extras such as `fault_claim_status`, `passed_claims`, `blocked_claims`, `h07_required_fault_types`, `h07_required_events`, and `h07_required_metrics`.

6. Register H07 in `scripts/m1h/assert_stage_exit.py`.

   Add `H07_REQUIRED_GATE_RESULTS`:

   - `build_evidence_manifest`
   - `assert_evidence_taxonomy`
   - `assert_fault_timeline_real`
   - `assert_no_fixture_fallback`
   - `assert_no_legacy_m1_pass`
   - `assert_no_simulated_subagents`

   Add `H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING` to `STAGE_REQUIRED_GATE_RESULTS`.

## Tests

Add focused tests in `tests/m1h/test_gate_framework.py`:

- a fully valid H07 same-directory exact-scale bundle can pass for one scale;
- missing `fault_timeline_report.json` blocks;
- missing `fault_timeline_events.jsonl` blocks;
- missing `failover_latency_samples.jsonl` blocks;
- missing one required fault type blocks;
- missing one lifecycle event blocks;
- an event with `MISSING` or `SKIPPED_WITH_REASON` status blocks real PASS;
- non-numeric, string, bool, null, and placeholder metric values block;
- non-empty-only event JSONL cannot pass;
- `PARTIAL` report or row status blocks;
- `real_valkey: false` blocks;
- execution mode with fake, fixture, dry-run, legacy, or partial markers blocks;
- exact scale mismatch blocks;
- Valkey version not `9.1.x` blocks;
- workload ref missing blocks;
- workload ref present but H06 claim blocked keeps H07 blocked;
- cleanup ref missing or resources remaining blocks;
- `failover_samples.jsonl` legacy samples do not substitute for `failover_latency_samples.jsonl`;
- P20/P21 curve-only legacy evidence cannot satisfy a new H07 claim;
- artifacts split across directories cannot be combined into PASS;
- `assert_fault_timeline_real` allows honest blocked claims but rejects unsafe PASS;
- H07 stage exit requires `assert_fault_timeline_real.json`.

Update import checks and any "required checks are not shallow" test to include the new H07 constants and the new H07 stage-exit gate list.

## Gates To Run

Run:

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

- `fault_timeline.real_exact.50`, `.100`, and `.200` can be `PASS` only with same-directory M1-format C09 bundles, exact-scale real Valkey 9.1.x proof, required lifecycle events, numeric metrics, workload refs, cleanup refs, and clean cluster evidence.
- Current repository fault claims remain `BLOCKED_WITH_REASON` unless exact-scale C09 evidence is actually present.
- The H07 gate exits 0 for honest blocked claims and writes `runs/m1-hardening/H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING/artifacts/gates/assert_fault_timeline_real.json` with zero violations.
- No fixture, legacy, fake, PARTIAL, dry-run, small-smoke, or non-empty-only artifact path can promote a fault timeline claim.
- `assert_stage_exit.py` recognizes and requires the H07 gate result.

## Blocked-State Expectations

For the current repository, the expected safe outcome is:

- `fault_claim_status: BLOCKED_WITH_REASON` in the H07 gate extras;
- zero passed fault timeline claims;
- three blocked fault timeline claims at 50, 100, and 200;
- blocked reasons that explicitly name missing C09 report/events/samples, missing complete numeric metrics, workload benchmark dependency not yet accepted by H06, cleanup proof gaps when present, and exact-scale bundle requirements;
- milestone PASS remains blocked until real exact-scale C09 evidence is produced.

## Review Risks

- The biggest risk is accidentally accepting legacy real evidence because it was generated by real Valkey. H07 must require the new C09 M1 bundle, not just historical raw files.
- Schema validation alone is insufficient; the gate must enforce semantic truth: exact scale, event order, numeric metrics, status PASS, clean cluster proof, and workload/cleanup refs.
- H06 currently blocks workload benchmark claims. H07 must not bypass that by accepting fault-local workload impact rows as benchmark evidence.
- Existing `cleanup_report.json` can contain SKIPPED cleanup actions even when top-level status is PASS; H07 should require a clean-cluster proof and no remaining owned resources for any real PASS.
- Keep candidate evaluation directory-scoped to avoid building a false PASS from P20/P21 latency samples plus P33/P34/P35 Valkey evidence.
