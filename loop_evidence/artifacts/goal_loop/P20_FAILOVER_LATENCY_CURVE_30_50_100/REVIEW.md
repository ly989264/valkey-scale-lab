# REVIEW - P20_FAILOVER_LATENCY_CURVE_30_50_100

Decision: PASS

Fresh context reviewer: fresh-context-codex-reviewer
Review time: 2026-07-02T18:58:49Z

## Evidence Inspected

- `AGENTS.md`
- `codex/phase_manifest.json`
- `docs/codex/02_PHASES.md`
- `docs/codex/04_AUDITOR.md`
- `docs/codex/goal-loop/stages/P20_FAILOVER_LATENCY_CURVE_30_50_100.md`
- `artifacts/goal_loop/P20_FAILOVER_LATENCY_CURVE_30_50_100/CONTEXT_RELOAD.md`
- `artifacts/goal_loop/P20_FAILOVER_LATENCY_CURVE_30_50_100/DESIGN_BRIEF.md`
- `artifacts/goal_loop/P20_FAILOVER_LATENCY_CURVE_30_50_100/WORKER_SUMMARY.md`
- `artifacts/goal_loop/P20_FAILOVER_LATENCY_CURVE_30_50_100/COMPLETION.md`
- `artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/gate_result.json`
- `artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/stdout/*.log`
- `artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/stderr/*.log`
- Required P20 artifacts under `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/`
- Relevant source and test diffs in `scripts/fault_failover_gate.py`, `scripts/assert_failover_latency_curve.py`, `scripts/assert_quant_artifacts.py`, `scripts/assert_workload_impact.py`, `src/valkey_scale_lab/runtime/docker_runtime.py`, and tests.
- Relevant schemas under `schemas/artifact/`.

## Gate Result

- Path: `artifacts/gates/P20_FAILOVER_LATENCY_CURVE_30_50_100/gate_result.json`
- SHA256: `06c86ab895b8f3a2810bb7d2506f4067941c17499ebfbaff4f5b4421376a7ccd`
- Manifest SHA256 recorded in gate result matches current `codex/phase_manifest.json`: `3e23e6820b6fc067709118fb95a5c931ee4bbf2fc4a9ed923c73d2ea9a64cd38`
- All ten manifest gates are recorded as `PASS`, exit code `0`, and command text matches the manifest.
- All recorded stdout/stderr log files exist and their SHA256 hashes match `gate_result.json`.

## Artifact Checks

Required artifacts exist and validate against manifest schemas, including line-by-line JSONL validation:

- `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/phase_summary.json` SHA256 `081f9bffa18e5824236bf890aabaf0e103215fa5c70e3d4489d20ccd831726c2`
- `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/valkey_e2e_evidence.json` SHA256 `3cda9dcd65fafb1b9b04e375b9629385c13b77fd7fc8f8bde673f697aea7a6d4`
- `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/cleanup_report.json` SHA256 `0d0a6a4eebb37e0f0b50f6a1a4a2c1679e82cdfafa127f46403dc813e4ebaa00`
- `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/events.jsonl` SHA256 `cea852c4d81c44f8abe8d29d4c8d783ac9727c855e6e87212253285c38b5f8e8`
- `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/metrics_timeseries.jsonl` SHA256 `c0143a9909174c592c82a70cc6b48c214cb0352413ae193d1b59a2704d9b67dd`
- `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/workload_windows.json` SHA256 `3a95e34263798c89aa7b542b61dccecd4af8f9ca5342e62e4ed2cc29496eb080`
- `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/quant_summary.json` SHA256 `5be21b53ff9846a2ddce4ebb95a6d737e0a923ccdd0b07615e07a341d05e4f1a`
- `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/failover_latency_samples.jsonl` SHA256 `0f5533b1ca9c25c546712adf08adfc6ad765f59987454856c5d7c9c473c96063`
- `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/failover_latency_curve.json` SHA256 `7e6d459beb96587f54bf92f3802a169cf694605f8499efa73098c612b947f1a7`
- `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/fault_matrix_report.json` SHA256 `b6d1f89b3de252cb15dc2a0c2c9a7c3b718618450f299640523053822eb315cc`
- `artifacts/phases/P20_FAILOVER_LATENCY_CURVE_30_50_100/workload_impact_report.json` SHA256 `b8d5c6360ad1d44d79678d5c2cd01f3e32baf249443bd9ca5242e148a90d1cf8`

## P20 Findings

- `artifacts/goal_loop/P20_FAILOVER_LATENCY_CURVE_30_50_100/BLOCKED.md` is absent.
- `failover_latency_samples.jsonl` contains exactly nine samples: three each for rungs 30, 50, and 100. Every sample reports `status=PASS`, `real_valkey=true`, exact `node_count`, a promoted node, numeric promotion/recovery/read/write timestamps, a workload impact reference, and `cleanup_status=PASS`.
- Per-sample evidence files record live probe `PASS`, data-path `PASS`, Valkey version `9.1.0`, exact observed known-node counts 30, 50, or 100, live `CLUSTER NODES` views, and cleanup `PASS` with no resources remaining.
- `failover_latency_curve.json` derives p50/p95/max promotion and recovery series from raw sample values and references exactly the nine raw sample IDs.
- `workload_impact_report.json` covers all nine sample IDs with canonical workload windows and comparisons.
- `resource_preflight_30.json`, `resource_preflight_50.json`, and `resource_preflight_100.json` each report `status=PASS`, `can_run=true`, and exact `node_count`.

## Safety

- Safety static scan gate passed.
- P20 faults are scoped to `owned_container_or_process` through the project fault API / owned runtime control.
- No host interface, route, firewall, PF, nftables, iptables, OS network service, or sudo default path was introduced in the inspected diffs.
- Scale configs remain capped at `default_max_nodes: 100`, use `valkey/valkey:9.1.0`, and keep `allow_1000_nodes: false`.
- Aggregate cleanup reports `status=PASS`, nine sample cleanup actions, and no `resources_remaining`; every child cleanup report also reports `PASS` with no leftovers.

## Rationale

All manifest gates ran and passed with matching command text and log hashes. Required artifacts exist, validate against schema, and pass P20 semantic assertions. Real Valkey evidence proves live Valkey `9.1.0` for exact 30/50/100 rungs with three real samples per rung. Cleanup and safety evidence are sufficient, and stale blocked evidence is absent.
