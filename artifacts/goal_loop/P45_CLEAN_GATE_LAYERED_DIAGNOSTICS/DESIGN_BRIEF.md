# DESIGN_BRIEF — P45_CLEAN_GATE_LAYERED_DIAGNOSTICS

## Objective

Keep the clean gate as the final harness PASS/stability endpoint while separating it from failover RTO metrics. P45 must emit real, schema-validated 30/50/100/200 Valkey evidence with three independent layers: Level 1 observer recovery, Level 2 continuous client recovery, and Level 3 clean-gate snapshot diagnostics.

## Repository findings

- P45 is not yet in `codex/phase_manifest.json`; current status shows only the new P45 stage document, context reload, and harness exception as untracked files.
- P44 added `src/valkey_scale_lab/observer/failover_timeline.py`, `scripts/fault_failover_timeline_gate.py`, timeline schemas, and real 10/30/50/100/200 artifacts. These are the right base, but P44 still writes `clean_snapshot_passed_at_ms` as a single final timestamp and does not emit `clean_gate_diagnostics.json`, `clean_gate_probe_rounds.jsonl`, `layered_recovery_summary.json`, or `recovery_endpoint_summary.json`.
- Level 1 is already mostly source-separated: `FailoverTimelineObserver` records `first_pfail_seen_at_ms`, `first_slots_covered_at_ms`, and `first_cluster_ok_at_ms` from observer samples, and `derive_rto_metrics()` rejects obvious clean-gate substitution.
- Level 2 is mostly present as `client_recovery_samples.jsonl`, but the P44 loop starts client sampling only after `fault apply` returns. P45 should make the source and timestamp contract explicit and assert it was not reconstructed after the clean gate.
- Level 3 currently uses `wait_for_stable_cluster_ok()` in `scripts/fault_failover_gate.py`, which wraps `scripts/valkey_probe_lib.py::wait_for_cluster_ok()`. That helper records coarse timing if passed a `timing` dict, but it does not expose per-round `probe_start_ms`, `probe_end_ms`, `sample_scope`, `failed_reason`, or `slowest_node`.
- The process-runtime clean gate in `src/valkey_scale_lab/runtime/docker_runtime.py` is `_wait_process_snapshot_clean()` -> `_wait_process_predicate()`. It records timing entries for representative/final/diagnostic probes, but not P45 diagnostic rows. It should become diagnostics-capable without changing existing call semantics.
- Existing schemas are permissive (`additionalProperties: true`) for P44 timeline rows, so P45 correctness must be enforced by new fail-closed assertions, not schemas alone.
- P44 manifest/gate-lock patterns are the template for P45: add the phase as non-automatic, add locked scripts/schemas/docs, and refresh hashes transparently. `待验证`: whether the main agent wants P45 non-automatic like P44 or automatic; current request is explicit stage work, not a new automatic loop.

## Files expected to change

| Path | Change type | Reason |
|---|---|---|
| `codex/phase_manifest.json` | update | Add P45 with real gate, schema gates, assertions, required artifacts, audit paths. |
| `codex/gate_lock.json` | update | Refresh hashes and include new/changed harness scripts, schemas, and P45 stage doc. |
| `src/valkey_scale_lab/observer/failover_timeline.py` | update | Add layered recovery summary builders, clean-gate diagnostic aggregation, and stricter source metadata helpers. |
| `src/valkey_scale_lab/runtime/docker_runtime.py` | update | Make process-runtime clean checks diagnostics-capable while preserving final clean predicate. Add P45 scale/scenario allowance and 200-node exception. |
| `scripts/valkey_probe_lib.py` | update | Add optional clean-gate probe-round collection for representative/all-node rounds without weakening `wait_for_cluster_ok()`. |
| `scripts/fault_failover_gate.py` | update | Let `wait_for_stable_cluster_ok()` return or fill clean diagnostics for gate callers. Preserve old callers. |
| `scripts/fault_failover_timeline_gate.py` | update | Support P45 phase/scenarios and emit P45 clean diagnostics, layered summaries, and recovery endpoint summaries. Keep P44 behavior compatible. |
| `scripts/assert_clean_gate_diagnostics.py` | add | Fail closed on missing clean diagnostic totals, probe rounds, slowest probe, timeout count, and last failing reason. |
| `scripts/assert_layered_recovery_semantics.py` | add | Verify Level 1/2/3 sources, timestamps, and derived layer metrics. |
| `scripts/assert_no_clean_gate_rto_conflation.py` | add | Reject using clean snapshot time for `pfail_to_cluster_ok_ms` or Level 1 recovery. |
| `scripts/assert_no_clean_gate_partial_coverage.py` | add | Require real layered evidence for 30/50/100/200 and reject report-only or historical-only coverage. |
| `schemas/artifact/clean_gate_diagnostics.schema.json` | add | Validate `clean_gate_diagnostics.json`. |
| `schemas/artifact/clean_gate_probe_round.schema.json` | add | Validate `clean_gate_probe_rounds.jsonl`. |
| `schemas/artifact/layered_recovery_summary.schema.json` | add | Validate `layered_recovery_summary.json`. |
| `schemas/artifact/recovery_endpoint_summary.schema.json` | add | Validate `recovery_endpoint_summary.json`. |
| `schemas/artifact/failover_timeline_sample.schema.json` | update | Require or at least describe P45 layer source fields where practical. Assertions enforce conditional semantics. |
| `schemas/artifact/observer_sample.schema.json` | update | Add optional/source fields for Level 1 endpoint evidence if needed. |
| `tests/unit/test_failover_timeline_observer.py` | update | Cover layered derivation and clean-gate conflation rejection. |
| `tests/unit/test_clean_gate_diagnostics.py` | add | Unit tests for aggregation, last failing reason, slowest probe, monotonicity, and missing fields. |
| `tests/failover/test_clean_gate_layered_assertions.py` | add | Positive/negative tests for the four new assertion scripts. |
| `tests/integration/test_failover_timeline_artifacts.py` | update | Ensure fake/schema P45 artifacts validate but cannot satisfy real coverage. |
| `tests/integration/test_docker_runtime_contract.py` | update | Assert P45 exact scale process runtime, 200-node exception, and diagnostics-capable clean gate behavior. |
| `tests/unit/test_goal_loop_assertions.py` | update | Assert P45 manifest policy, gates, required artifacts, and no >200 real runtime default. |
| `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/*` | generate | Real P45 gate output and required schema-validated artifacts. |
| `audit/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/*` | generate | Fresh-context audit artifacts required by postcheck. |

## Implementation plan

1. Add P45 runtime/scenario support.
   - Introduce `P45_STAGE = "P45_CLEAN_GATE_LAYERED_DIAGNOSTICS"` in runtime/resource code.
   - Add `_p45_clean_gate_layered_node_count()` for `p45_scale_(10|30|50|100|200)_layered_sample_\d+`.
   - Include P45 in process-runtime selection, exact node-count validation, resource preflight exact-200 exception, and bounded-exception phase checks.

2. Add clean-gate probe round diagnostics.
   - In `scripts/valkey_probe_lib.py`, add optional `diagnostic_rounds` collection to `wait_for_cluster_ok()` or add a wrapper that returns `(ok, probes, rounds)`.
   - Each round should record `probe_start_ms`, `probe_end_ms`, `probe_duration_ms`, `sample_scope`, `sample_count`, `failed_reason`, `slowest_node`, `slowest_probe_ms`, status counts, and whether all slots were covered and all nodes were clean.
   - Preserve current PASS condition: representative success must still be followed by all-node final verification.
   - In `docker_runtime.py`, add equivalent optional round recording to `_wait_process_predicate()` so process setup and future management/fault clean paths are diagnostics-capable without changing existing callers.

3. Extend the P44 timeline gate into P45 layered mode.
   - Keep P44 output compatibility.
   - For `--phase P45_CLEAN_GATE_LAYERED_DIAGNOSTICS`, use P45 scenario names, P45 blocked text, and P45 artifact names.
   - Start the observer before fault apply; run the client probe during fault/recovery; run clean-gate sampling as the Level 3 endpoint and record every clean-gate round.
   - Do not derive Level 1 or Level 2 after Level 3. The P45 row should carry explicit source fields such as `level_1_source=runtime_observer`, `level_2_source=continuous_client_probe`, and `level_3_source=clean_gate_probe_rounds`.

4. Build P45 summaries from raw rows only.
   - `clean_gate_diagnostics.json`: aggregate first representative/all-node clean times, total clean gate time, counts, timeout count, slowest probe info, first PFAIL/FAIL/promotion/cluster/client markers, and `last_failing_reason`.
   - `clean_gate_probe_rounds.jsonl`: one row per representative/full/diagnostic round.
   - `layered_recovery_summary.json`: include `kill_to_pfail_ms`, `pfail_to_cluster_ok_ms`, `cluster_ok_to_client_success_ms`, `cluster_ok_to_clean_snapshot_ms`, `kill_to_clean_snapshot_ms`, `level_1`, `level_2`, `level_3`, and `clean_gate`.
   - `recovery_endpoint_summary.json`: summarize raw endpoint timestamps and source artifact refs per sample and scale.
   - Keep `failover_timeline_samples.jsonl`, `observer_samples.jsonl`, and `client_recovery_samples.jsonl` as raw source artifacts.

5. Add fail-closed assertions.
   - `assert_clean_gate_diagnostics.py` checks required fields, count consistency with JSONL rounds, slowest probe derivation, timeout counts, and last failing reason when the first round did not pass.
   - `assert_layered_recovery_semantics.py` recomputes all layered durations from raw timestamps and verifies Level 1/2/3 source artifacts.
   - `assert_no_clean_gate_rto_conflation.py` rejects Level 1 metrics sourced from `clean_snapshot`, `clean_gate`, report-only fields, or values equal to clean-snapshot duration without identical endpoint timestamps.
   - `assert_no_clean_gate_partial_coverage.py` requires 30/50/100/200 PASS samples for phase P45, checks real Valkey evidence, rejects fake/schema rows as real, and verifies greater-than-200 is dry-run only.

6. Add schemas and manifest gates.
   - Add P45 after P44, likely `automatic: false`, `real_valkey_required: true`, `fake_only_allowed: false`, `max_nodes: 200`.
   - Gate order should mirror P44 plus new schemas/assertions: safety scan, compile, focused tests, real timeline gate for `10,30,50,100,200`, schema validation for all required JSON/JSONL, four P45 assertions, cleanup assertion.
   - Include all stage-doc required artifacts in `required_artifacts`; `failover_rto_summary.json` may remain an extra compatibility artifact but should not replace `layered_recovery_summary.json`.

## Harness, schema, and gate plan

- New schemas:
  - `clean_gate_diagnostics.schema.json`
  - `clean_gate_probe_round.schema.json`
  - `layered_recovery_summary.schema.json`
  - `recovery_endpoint_summary.schema.json`
- Manifest gate suggestions:
  - `python3 scripts/safety_scan.py`
  - `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 -m compileall -q scripts src`
  - `PYTHONPYCACHEPREFIX=/tmp/vslab_pyc python3 -m pytest -q tests/unit/test_failover_timeline_observer.py tests/unit/test_clean_gate_diagnostics.py tests/failover/test_clean_gate_layered_assertions.py tests/integration/test_failover_timeline_artifacts.py tests/integration/test_docker_runtime_contract.py`
  - `python3 scripts/fault_failover_timeline_gate.py --phase P45_CLEAN_GATE_LAYERED_DIAGNOSTICS --artifact-dir artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS --scales 10,30,50,100,200 --samples-per-scale 1 --require-data-path`
  - Schema validation for `failover_timeline_samples.jsonl`, `observer_samples.jsonl`, `client_recovery_samples.jsonl`, `clean_gate_probe_rounds.jsonl`, `clean_gate_diagnostics.json`, `layered_recovery_summary.json`, `recovery_endpoint_summary.json`, common quant artifacts, and `dry_run_gt_200_projection.json`.
  - The four new P45 assertion scripts plus `scripts/assert_cleanup.py`.
- Gate-lock update must be transparent. Do not hand-edit gate results or state files to pass P45.

## Test plan

- Unit tests:
  - Clean-gate aggregation derives first representative/all-node clean timestamps, totals, counts, timeout count, slowest node, and last failing reason.
  - Layered summary derives Level 1 only from observer timestamps and Level 2 only from client rows.
  - Timestamp monotonicity rejects Level 3 preceding Level 1/2 unless marked `MISSING` with a reason and sample status is not PASS.
  - Missing required clean fields fail closed.
- Assertion tests:
  - PASS fixture with four required real scales.
  - Fail when `clean_gate_total_ms`, `probe_round_count`, or `full_probe_count` is missing.
  - Fail when `last_failing_reason` is missing after an initial failed clean round.
  - Fail when `pfail_to_cluster_ok_ms == kill_to_clean_snapshot_ms` without identical endpoint proof.
  - Fail when Level 1/2/3 lacks source refs or timestamps.
  - Fail when only P44/P35/P36 artifacts exist or rows have phase IDs other than P45.
- Integration tests:
  - Simulated slow clean gate with representative rounds passing before all-node rounds; verify Level 1/2 are preserved and Level 3 records the tail.
  - Fake/schema artifact validation that cannot satisfy real P45 assertions.
- Real gate:
  - Run smoke plus required 30/50/100/200 real samples after resource preflight. If resource preflight fails, write `BLOCKED.md` and do not pass.

## Required artifacts

P45 must emit under `artifacts/phases/P45_CLEAN_GATE_LAYERED_DIAGNOSTICS/`:

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
- `observer_samples.jsonl`
- `client_recovery_samples.jsonl`
- `clean_gate_diagnostics.json`
- `clean_gate_probe_rounds.jsonl`
- `layered_recovery_summary.json`
- `recovery_endpoint_summary.json`
- `dry_run_gt_200_projection.json`

Recommended supporting artifacts: `resource_preflight_10.json`, `resource_preflight_30.json`, `resource_preflight_50.json`, `resource_preflight_100.json`, `resource_preflight_200.json`, plus per-sample state/fault/cleanup/log files under `_p45_samples/`.

## Safety considerations

- Do not weaken the clean gate or final all-node clean condition to improve RTO numbers.
- All faults must continue through owned project fault APIs and owned Docker/process controls. No host firewall, route, interface, PF, nftables, iptables, or `sudo` network path.
- Observer and clean probes are read-only except the existing deterministic client SET/GET workload; test keys must include sample/run IDs.
- Threads/loops need deterministic stop conditions and cleanup in `finally`.
- Cleanup failure must fail/block the stage even if Level 1/2 metrics were captured.
- Greater-than-200 remains dry-run/schema proof only; do not hardcode 200 as a runtime ceiling for future policy, but do cap current real P45 evidence at 200.

## Resource considerations

- All-node clean-gate rounds at 100/200 nodes can add substantial latency. Keep representative polling cheap and all-node probes bounded, but do not skip final full coverage.
- Resource preflight must run before 30/50/100/200 real samples and must block instead of downshifting.
- Probe round JSONL can grow quickly if every round records embedded probe details. Store compact round summaries at top level and put large raw probes only in per-sample logs if needed. `待验证`: exact row volume at 200 nodes with current timeout settings.
- One sample per scale matches P44 and the P45 stage wording. `待验证`: whether the main agent wants three samples per scale for stronger statistical parity with P20/P21.

## `待验证`

- Whether P45 should remain non-automatic like P44 or be added to an automatic chain.
- Whether the existing P44 real gate can be safely generalized for P45 without making P44 assertions brittle.
- Whether `wait_for_cluster_ok()` should expose diagnostics via an optional mutable list or a new wrapper to minimize caller churn.
- Whether P45 real runs should include smoke scale 10 in addition to required 30/50/100/200; recommended yes for fast sanity and P44 parity.
- Whether first client success should mean first success after `fault_apply_at_ms` or first success after `first_cluster_ok_at_ms`; P45 wording names SIGKILL to first successful SET/GET recovery, while P44 currently stores first success at/after cluster OK for the main timestamp.
- Whether large-scale PFAIL and FAIL markers are always observable before clean recovery; assertions should fail closed if required markers are missing.

## Worker instructions

- Implement only P45.
- Do not commit.
- Do not weaken harness, clean gate, cleanup, or safety rules.
- Preserve P44 artifacts and tests while adding P45 behavior.
- Keep Level 1 sourced only from observer timestamps, Level 2 only from continuous client probe timestamps, and Level 3 only from clean-gate probe rounds.
- Block rather than pass if Docker/resource preflight cannot support required real scales.
