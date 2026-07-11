# DESIGN_BRIEF - P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY

## Objective

Add failover RTO timeline observability that separates process-stop detection, PFAIL/FAIL gossip, replica promotion, slot/cluster recovery, business-visible client recovery, and clean-snapshot tail cost. P44 must produce schema-validated real evidence for small smoke plus 30/50/100/200 node primary-stop failover timelines, and must keep greater-than-200 coverage dry-run only.

## Repository findings

- Existing failover gates live mostly in `scripts/fault_failover_gate.py`. P20/P21 controller paths run 30/50/100/200 primary-stop samples and derive `promotion_latency_ms` and `cluster_recovery_latency_ms`, but they do not continuously observe PFAIL/FAIL, slots, client recovery, or clean-snapshot tail as independent segments.
- Existing generic failover gate currently sets `kill_to_pfail_ms` from `primary_unreachable_at_ms - fault_injected_at_ms`, and `pfail_to_cluster_ok_ms` from `recovery_unix_ms - primary_unreachable_at_ms`. That is not sufficient for P44 because `primary_unreachable_at_ms` is a target-process-gone/apply marker, not first observed PFAIL.
- Existing strict P33/P34/P35 failover samples set `cluster_recovery_latency_ms` equal to promotion latency and record client success from a post-recovery workload window. P44 must instead run a continuous client probe during the fault period and record first successful SET/GET after the fault.
- Existing probe helpers in `scripts/valkey_probe_lib.py` can parse `CLUSTER INFO` and `CLUSTER NODES`, but the requested observer must live under `src/valkey_scale_lab/observer/`. Reusing script-only helpers from package code would be brittle; package-owned observer code should contain or share its own RESP/probe primitives.
- `codex/phase_manifest.json` currently includes P43 as a non-automatic stage and has no P44 entry. `scripts/codex_gate.py` can run non-automatic phases if they are present in the manifest. P44 should be appended as `automatic: false`, `real_valkey_required: true`, `max_nodes: 200`.
- `codex/gate_lock.json` locks `codex/phase_manifest.json` and many docs/scripts. Any manifest or harness-script addition will require a transparent lock update; do not bypass the lock.
- Existing schemas cover `failover_latency_sample`, `failover_latency_curve`, `event`, `metric_sample`, `workload_windows`, `analysis_summary`, and `report_index`, but no schema exists for P44 timeline samples, observer samples, continuous client recovery samples, or RTO summary.
- Existing dry-run projection patterns are in `scripts/p42_server_profile_artifacts.py`, `scripts/p43_cluster_timeout_artifacts.py`, and `scripts/assert_200_plus_dry_run.py`. P44 can reuse the same `scale_1000_dryrun_optin.yaml` planning-only pattern and must not create runtime resources above 200.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `src/valkey_scale_lab/observer/__init__.py` | add | Export the failover observer package API. |
| `src/valkey_scale_lab/observer/failover_timeline.py` | add | Implement concurrent polling observer, timeline derivation, client probe accounting, and percentile summary helpers. |
| `scripts/p44_failover_timeline_gate.py` | add | Stage wrapper that performs resource preflight, runs small/30/50/100/200 real primary-stop samples with the observer, writes P44 artifacts, and performs cleanup. |
| `scripts/assert_failover_timeline_completeness.py` | add | Fail closed on missing required timestamps, absent scales, non-real evidence presented as real, incomplete observer/client samples, and non-monotonic timelines. |
| `scripts/assert_rto_metric_semantics.py` | add | Fail closed when derived RTO segments are substituted or include clean-gate time incorrectly. |
| `scripts/assert_no_rto_partial_coverage.py` | add | Fail closed when smoke-only, one-scale-only, or missing 30/50/100/200 coverage is present. |
| `schemas/artifact/failover_timeline_sample.schema.json` | add | Validate `failover_timeline_samples.jsonl` rows. |
| `schemas/artifact/failover_rto_summary.schema.json` | add | Validate `failover_rto_summary.json`. |
| `schemas/artifact/client_recovery_sample.schema.json` | add | Validate `client_recovery_samples.jsonl`. |
| `schemas/artifact/observer_sample.schema.json` | add | Validate `observer_samples.jsonl`. |
| `codex/phase_manifest.json` | update | Add non-automatic P44 with real gates, schema gates, assertions, and required artifact list. |
| `codex/gate_lock.json` | update | Refresh hashes for intentionally changed locked harness files and include new harness controls where the existing lock pattern requires it. |
| `tests/unit/test_failover_timeline_observer.py` | add | Unit tests for timestamp derivation, missing-field fail-closed behavior, client probe accounting, and percentile calculation. |
| `tests/failover/test_failover_timeline_assertions.py` | add | Negative tests for missing PFAIL, missing client recovery, semantic substitution, clean-gate contamination, and partial scale coverage. |
| `tests/integration/test_failover_timeline_artifacts.py` | add | Integration-style fake aggregation test that validates schema-shaped artifacts without claiming real evidence. |
| `tests/unit/test_goal_loop_assertions.py` | update | Add manifest policy checks for P44 non-automatic, real-Valkey requirement, 200-node cap, and no default >200 real execution. |
| `docs/codex/goal-loop/stages/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY.md` | maybe update | Only if the worker finds an ambiguity that must be strengthened; otherwise leave the stage doc as-is. 待验证 |
| `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/*` | generate | Required real, quant, analysis, report, timeline, client, observer, and dry-run projection artifacts. |

## Implementation plan

1. Add a package-level observer model:
   - `FailoverTimelineObserver` accepts endpoints, target logical/node IDs, expected replica ID, sample metadata, probe interval, and stop event.
   - It polls `CLUSTER INFO`, `CLUSTER NODES`, slot counters, node flags, role changes, and target endpoint reachability without waiting for the clean gate.
   - It records `observer_samples.jsonl`-ready rows with wall-clock and monotonic timestamps, `cluster_state`, `cluster_slots_assigned`, `cluster_slots_ok`, PFAIL/FAIL/handshake counts, role map snippets, target status, and promotion candidates.
   - It detects `first_pfail_seen_at_ms`, `first_fail_seen_at_ms`, `first_promotion_seen_at_ms`, `first_slots_covered_at_ms`, and `first_cluster_ok_at_ms` from observer samples only.
2. Add continuous client recovery probing:
   - Run a second concurrent loop against a key in the failed primary slot range.
   - Probe SET/GET at `client_probe_interval_ms` throughout fault active/recovery, follow MOVED/ASK redirects, count errors/timeouts/MOVED/ASK, and record first successful round trip after `fault_apply_at_ms`.
   - Emit `client_recovery_samples.jsonl` rows and derive `first_client_success_at_ms`, `first_success_after_fault_ms`, `error_count_before_recovery`, `timeout_count_before_recovery`, `moved_count`, and `ask_count`.
3. Add the P44 gate wrapper:
   - For each real scale, run resource preflight before runtime creation. Proposed coverage is one smoke sample at 10 nodes plus at least one real sample for each of 30/50/100/200. If the main agent wants prior curve parity, increase to three per scale. 待验证
   - Use existing `python3 -m valkey_scale_lab.cli gate scenario`, `fault apply`, `fault clear`, and `gate cleanup` commands; do not use host network mutation.
   - Start observer/client threads immediately before fault apply; capture `fault_apply_at_ms` before invoking fault apply; capture `target_process_gone_at_ms` from the first observer target-failure sample or the fault apply completion marker with source recorded.
   - Stop observer only after cluster/client recovery has been observed or timeout has expired, then run fault clear and the clean snapshot gate separately. Record `clean_snapshot_passed_at_ms` only after the post-clear stable cluster probe passes.
4. Derive timeline rows:
   - Required timestamps: `fault_apply_at_ms`, `target_process_gone_at_ms`, `first_pfail_seen_at_ms`, `first_fail_seen_at_ms`, `first_promotion_seen_at_ms`, `first_slots_covered_at_ms`, `first_cluster_ok_at_ms`, `first_client_success_at_ms`, `clean_snapshot_passed_at_ms`.
   - Derived metrics: `kill_to_pfail_ms`, `pfail_to_cluster_ok_ms`, `kill_to_client_recovered_ms`, `cluster_ok_to_client_success_ms`, `cluster_ok_to_clean_snapshot_ms`, and `kill_to_clean_snapshot_ms`.
   - If a required timestamp for a real sample is missing, mark the sample `FAIL`; do not encode required P44 core metrics as fake zeroes.
5. Build summary/report artifacts:
   - `failover_rto_summary.json` derives p50/p95/max from raw P44 timeline rows only and records `sample_count`, `timeout_config_ms`, `server_profile`, `nodehost_strategy`, `node_count`, and `scale`.
   - `phase_summary.json`, `quant_summary.json`, `analysis_summary.json`, and `report_index.json` cite raw input artifact paths, schema version, producer, and runtime claims.
   - `events.jsonl`, `metrics_timeseries.jsonl`, and `workload_windows.json` should include event IDs for observer start/stop, fault apply, PFAIL, FAIL, promotion, slot coverage, cluster OK, client recovery, clean snapshot, and cleanup.
6. Add dry-run projection:
   - Generate `dry_run_gt_200_projection.json` from `scale_1000_dryrun_optin.yaml` through planner dry-run only.
   - Include `dry_run: true`, `real_valkey: false`, `runtime_resources_created: false`, and an explicit projection-only reason.

## Harness, schema, and gate plan

- Add P44 to `codex/phase_manifest.json` after P43 as a non-automatic phase:
  - `automatic: false`
  - `fake_only_allowed: false`
  - `real_valkey_required: true`
  - `max_nodes: 200`
  - `objectives` matching the P44 stage doc.
- Suggested P44 manifest gates:
  - `python3 scripts/safety_scan.py`
  - `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 -m compileall -q scripts src`
  - `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 -m pytest -q tests/unit/test_failover_timeline_observer.py tests/failover/test_failover_timeline_assertions.py tests/integration/test_failover_timeline_artifacts.py tests/failover/test_failover_contract.py`
  - `python3 scripts/p44_failover_timeline_gate.py --phase P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY --artifact-dir artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY --scales 10,30,50,100,200 --require-data-path`
  - JSON/JSONL schema validation for all new P44 artifacts.
  - `python3 scripts/assert_failover_timeline_completeness.py --phase P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY --require-scales 30,50,100,200`
  - `python3 scripts/assert_rto_metric_semantics.py --phase P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY`
  - `python3 scripts/assert_no_rto_partial_coverage.py --phase P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY --require-scales 30,50,100,200 --require-dry-run-gt-200`
  - `python3 scripts/assert_cleanup.py --cleanup-report artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/cleanup_report.json`
- New schemas should be strict enough to require fields and status enums, while still allowing `MISSING`/`SKIPPED_WITH_REASON` objects for non-core ancillary fields. Required P44 real timestamps should be required and numeric for `status=PASS`; assertion scripts should enforce conditional semantics beyond JSON Schema.
- `scripts/assert_rto_metric_semantics.py` should recompute derived metrics from timestamps with a small tolerance and explicitly reject `pfail_to_cluster_ok_ms == kill_to_clean_snapshot_ms` unless timestamps genuinely make that true by arithmetic and clean snapshot is not part of the segment.
- `scripts/assert_no_rto_partial_coverage.py` should require at least one real observer-backed PASS sample for each of 30, 50, 100, and 200, plus one clearly marked dry-run-only >200 projection.

## Test plan

- Unit tests:
  - Derive all RTO metrics from a complete synthetic timeline.
  - Reject missing `first_pfail_seen_at_ms`, missing `first_client_success_at_ms`, non-monotonic timestamps, and clean-snapshot substitution.
  - Validate percentile helper output for one, three, and four samples.
  - Count client probe errors, timeouts, MOVED, and ASK before first recovery.
- Integration/fake aggregation tests:
  - Build fake observer/client/timeline rows into `failover_rto_summary.json` and validate schemas, with `real_valkey: false` or `execution_mode: fake_schema` so they cannot satisfy real coverage assertions.
  - Confirm assertion scripts fail if fake/schema tests are presented as P44 real evidence.
- Negative assertion tests:
  - Missing PFAIL timestamp.
  - Missing client recovery row.
  - `pfail_to_cluster_ok_ms` replaced by `kill_to_clean_snapshot_ms`.
  - Clean-gate time counted in `pfail_to_cluster_ok_ms`.
  - Only smoke or one scale present.
  - 30/50/100/200 scale absent.
- Real gate:
  - The P44 wrapper must run a bounded small Valkey primary-stop smoke path with the observer.
  - It must also run real 30/50/100/200 timeline paths after resource preflight. If preflight fails, write `BLOCKED.md` and do not pass.

## Required artifacts

P44 must produce these under `artifacts/phases/P44_FAILOVER_RTO_TIMELINE_OBSERVABILITY/`:

- `phase_summary.json`
- `valkey_e2e_evidence.json`
- `cleanup_report.json`
- `events.jsonl`
- `metrics_timeseries.jsonl`
- `workload_windows.json`
- `quant_summary.json`
- `analysis_summary.json`
- `report_index.json`
- `failover_timeline_samples.jsonl`
- `failover_rto_summary.json`
- `client_recovery_samples.jsonl`
- `observer_samples.jsonl`
- `dry_run_gt_200_projection.json`

Recommended additional artifacts:

- `resource_preflight_10.json`, `resource_preflight_30.json`, `resource_preflight_50.json`, `resource_preflight_100.json`, `resource_preflight_200.json`
- per-sample raw command logs under `_p44_samples/<scale>/<sample_id>/`
- per-sample state, fault apply/clear, and cleanup refs cited from the timeline rows.

## Safety considerations

- Fault injection must continue through owned project APIs (`fault apply`/`fault clear`) and owned Docker/container/process controls only.
- The observer must be read-only against Valkey endpoints and must never mutate host networking, firewall, routing, interfaces, or unrelated processes.
- The client probe can write only test keys with deterministic P44/sample prefixes and must record the key pattern; cleanup should not depend on deleting those keys unless the cluster is already being torn down.
- Observer/client threads must have deterministic stop/timeout handling so they do not survive cleanup.
- If cleanup fails or owned resources remain, P44 must fail or block; do not salvage a timeline PASS over cleanup failure without an explicit cleanup retry report.
- Greater-than-200 coverage must be dry-run projection only; no live endpoint proof, runtime resource creation, or real workload claim above 200.

## Resource considerations

- Real 200-node failover plus concurrent observer/client probes can be expensive. The wrapper should cap probe fanout, use a safe default interval, and prefer representative endpoints plus target/replica endpoints rather than probing all 200 nodes every tick. 待验证: exact fanout needed to detect PFAIL reliably at 200.
- Resource preflight must run before every 30/50/100/200 runtime path and must fail/block rather than downshift.
- P44 should not default to 1000 nodes and should not alter `default_max_nodes`.
- Running one sample per 30/50/100/200 scale is the lowest-cost interpretation of the P44 stage document; three samples per scale would align better with P20/P21 curve history but materially increases runtime. 待验证.
- Use timeouts consistent with P43 default `cluster-node-timeout` provenance and record `timeout_config_ms`, `server_profile`, and `nodehost_strategy` in summary artifacts.

## `待验证`

- Whether the main agent wants P44 to require one real sample per 30/50/100/200 scale or three samples per scale to mirror P20/P21 latency curve policy.
- Whether P44 should augment `scripts/fault_failover_gate.py` directly or keep the new behavior isolated in `scripts/p44_failover_timeline_gate.py`; isolated is lower-risk, but direct integration may reuse more existing setup paths.
- Whether `CLUSTER NODES` from representative endpoints is enough to reliably observe first PFAIL at 100/200 scale, or whether the observer must poll all endpoints during the short PFAIL window.
- Whether existing P20/P21/P33/P34/P35 artifacts may be cited as prior context only; they cannot satisfy P44 real observer evidence unless regenerated with P44 observer samples.
- Whether Docker resources are available in this session for 30/50/100/200 real P44 runs.
- Whether new P44 stage docs and scripts should be included in `codex/gate_lock.json` under the same lock coverage pattern as P15-P43.

## Worker instructions

- Implement only this stage.
- Do not commit.
- Do not weaken harness or safety rules.
- Keep P44 non-automatic unless the main agent explicitly changes policy.
- Do not represent fake/schema tests as real Valkey evidence.
- Do not calculate `pfail_to_cluster_ok_ms` from target-process-gone or clean-snapshot timestamps.
- Block, rather than pass, if resource preflight cannot support required real scales.
