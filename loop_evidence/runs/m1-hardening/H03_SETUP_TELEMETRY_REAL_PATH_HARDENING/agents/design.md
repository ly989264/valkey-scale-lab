# H03 Design Brief

role: design
agent_invocation: real_subagent
stage_id: H03_SETUP_TELEMETRY_REAL_PATH_HARDENING
source_commit_before: 65089a70901e8ccb7be4af89bf0bee92ad4e2016

## Summary

H03 should harden setup telemetry acceptance so the stage can pass only by proving the gate fails closed. Current exact-scale setup claims must remain blocked: the repository has real legacy `runtime_timing_breakdown*.json` and `valkey_e2e_evidence.json` at 50/100/200, but no exact-scale M1-format `setup_telemetry.json` under the exact-scale phase paths. Legacy timing artifacts are useful source evidence, not PASS evidence for C06.

The intended H03 success shape is: `assert_setup_core_metrics` exits 0 because it proves there are no unsafe setup PASS claims, while the setup claims themselves stay `BLOCKED_WITH_REASON` until exact-scale M1 setup telemetry exists with numeric C06 core metrics and complete per-node samples.

## Sources Read

- `runs/m1-hardening/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING/handoff/CONTEXT_RELOAD.md`
- H02 handoff, review, worker, design, completion, next-stage input, and existing gate artifacts
- `codex_goal_loop_m1_hardening_v2/contracts/C06_SETUP_TELEMETRY_CONTRACT.md`
- `codex_goal_loop_m1_hardening_v2/stages/H03_SETUP_TELEMETRY_REAL_PATH_HARDENING.md`
- `codex_goal_loop_m1_hardening_v2/docs/03_EVIDENCE_TAXONOMY.md`, `04_HARD_GATE_ARCHITECTURE.md`, `09_NO_SHORTCUT_RULES.md`, and `10_ACCEPTANCE_MATRIX.md`
- `scripts/m1h/manifest.py`
- `scripts/m1h/capability_gate.py`
- `scripts/m1h/assert_setup_core_metrics.py`
- `src/valkey_scale_lab/runtime/setup_timeline.py`
- `schemas/artifact/setup_telemetry.schema.json`
- Existing setup artifacts, including `runs/m1-s02-local/artifacts/setup_telemetry.json`, setup telemetry fixtures, exact-scale `runtime_timing_breakdown*.json`, and exact-scale `valkey_e2e_evidence.json`

## Findings

- `manifest.py` currently treats any `runtime_timing_breakdown*.json` as `setup_core_metrics_present`. That is too weak for H03 because C06 requires M1-format `setup_telemetry.json` with numeric core metrics.
- 50/100/200 setup claims are currently `LEGACY_EVIDENCE_ONLY`; 30 is `INVALID`. That is conservative, but the semantic checks misleadingly mark `setup_core_metrics_present` and `m1_format_fields_complete` true for 50/100/200 even though only legacy timing evidence exists.
- `capability_gate.py` is generic. It reports blocked claims as a blocked gate result. For H03, `assert_setup_core_metrics.py` should become a setup-specific hardening gate that passes when unsafe PASS promotion is absent, and records setup claim status separately.
- `setup_timeline.py` and the schema allow structured `MISSING` or `SKIPPED_WITH_REASON` metric values. That remains valid for fixtures, dry-runs, blocked attempts, and small smoke, but must not be acceptable for exact-scale setup PASS.
- Existing M1 setup telemetry fixtures and `runs/m1-s02-local/artifacts/setup_telemetry.json` are 2-node artifacts and include `resource_preflight_ms: SKIPPED_WITH_REASON`; they are fixtures/small evidence only, not exact-scale PASS evidence.
- Exact-scale legacy `p13_timing_breakdown` files have useful timing names such as `nodehost_start`, `process_start`, `primary_cluster_create`, `replica_replicate`, and probes, but they are not `artifact_type: setup_telemetry`, do not carry the C06 per-node sample shape, and have cleanup/wrapper timings missing in some paths. Do not promote them by non-empty or timing-name checks.

## Precise Recommendations

1. Add a setup-specific C06 evaluator in `scripts/m1h/manifest.py` or a small helper imported by both manifest and gate code. It should define the C06 core metric list exactly:
   `nodehost_start_ms`, `node_config_generate_ms`, `node_config_distribute_ms`, `process_start_ms`, `process_ready_wait_ms`, `cluster_meet_ms`, `cluster_slots_assign_ms`, `replica_replicate_ms`, `cluster_convergence_probe_ms`, `full_cluster_probe_ms`, `cleanup_ms`, `total_setup_ms`.

2. For `setup_telemetry` claims, treat `setup_telemetry.json` as the only M1-format artifact that can satisfy `setup_core_metrics_present`. `runtime_timing_breakdown*.json` and `valkey_e2e_evidence.json` may remain source artifacts, but they should keep the claim `LEGACY_EVIDENCE_ONLY` or `BLOCKED_WITH_REASON` unless an explicit reconstruction artifact proves every C06 field without invention.

3. Exact-scale setup PASS must require:
   artifact type `setup_telemetry`, status `PASS`, `node_count >= scale`, non-fixture source path, real Valkey evidence for the same exact scale, Valkey version starting with `9.1.`, all C06 metrics numeric non-negative numbers, and no C06 metric encoded as `MISSING` or `SKIPPED_WITH_REASON`.

4. Exact-scale per-node PASS must require `per_node_samples` length at least the required scale. Every sampled node must include non-missing node id (`logical_id` or `node_id`), role (`node_role` or `role`), nodehost id, pid (`node_pid` or `pid`), a numeric ready metric (`node_ready_ms` or `node_ping_ready_ms`), cluster state, and known-node count (`node_cluster_known_nodes` or `known_nodes`). Structured skipped/missing placeholders in these fields must block the claim.

5. Add semantic checks such as `setup_telemetry_artifact_present`, `setup_telemetry_status_pass`, `setup_core_metrics_numeric`, and `setup_per_node_samples_complete`. `m1_format_fields_complete` for setup should be true only when those checks and the real exact-scale checks are true.

6. Change `assert_setup_core_metrics.py` from a generic blocked-capability wrapper into a setup hardening gate. It should exit 0 and write gate status `PASS` when all setup PASS claims satisfy C06 and all non-satisfying exact-scale claims are blocked with explicit reasons. It should fail if any setup claim is `PASS` with legacy-only, fixture-only, dry-run, skipped core metrics, missing per-node fields, or exact-scale mismatch.

7. Keep the current claims blocked until real exact-scale telemetry exists. The expected H03 gate artifact should include `setup_claim_status: BLOCKED_WITH_REASON`, `passed_claims: []`, and per-scale blocked reasons naming missing M1 `setup_telemetry.json`, non-numeric/skipped C06 metrics, or incomplete per-node samples.

8. Extend `assert_stage_exit.py` for H03 so the required gate set includes `build_evidence_manifest`, `assert_evidence_taxonomy`, `assert_setup_core_metrics`, `assert_no_fixture_fallback`, `assert_no_legacy_m1_pass`, and `assert_no_simulated_subagents`. Stage exit should require those gate result JSON files to have status `PASS`.

9. Add regression tests for:
   valid exact-scale setup telemetry passing;
   a C06 metric encoded as `SKIPPED_WITH_REASON` blocking/failing PASS;
   missing per-node pid/ready/cluster-state/known-node fields blocking/failing PASS;
   legacy `runtime_timing_breakdown*.json` plus real Valkey evidence staying blocked;
   fixture `setup_telemetry.json` never satisfying an exact-scale claim;
   H03 stage exit requiring `assert_setup_core_metrics`.

## Gate Sequence

```text
PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h03 python3 -m compileall -q scripts src tests
PYTHONPYCACHEPREFIX=/private/tmp/valkey-scale-lab-pycache-h03 python3 -m pytest -q tests/m1h tests/ci/test_milestone1_acceptance_gate.py
python3 scripts/m1h/build_evidence_manifest.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING --out runs/m1-hardening/evidence_manifest.json
python3 scripts/m1h/assert_evidence_taxonomy.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING
python3 scripts/m1h/assert_setup_core_metrics.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING
python3 scripts/m1h/assert_no_fixture_fallback.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING
python3 scripts/m1h/assert_no_legacy_m1_pass.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING
python3 scripts/m1h/assert_no_simulated_subagents.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING
python3 scripts/m1h/assert_stage_exit.py --stage H03_SETUP_TELEMETRY_REAL_PATH_HARDENING
```

## Acceptance Criteria

H03 passes when the hardening gate itself is green and machine-enforced, while exact-scale setup telemetry remains blocked unless a real exact-scale `setup_telemetry.json` has all numeric C06 core metrics and complete per-node samples. No fixture, legacy timing file, non-empty JSON, skipped metric, or small-smoke artifact may promote setup telemetry to PASS.
