#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from schema_validator import load_json  # noqa: E402

GOAL_STAGES: list[dict[str, Any]] = [
    {"id": "P15_GOAL_REBASE_HARNESS_EXTENSION", "real": False, "max_nodes": 0},
    {"id": "P16_QUANT_TELEMETRY_UNIFICATION", "real": True, "max_nodes": 6},
    {"id": "P17_MANAGEMENT_REMOVE_NODE", "real": True, "max_nodes": 10},
    {"id": "P18_MANAGEMENT_RESHARD_REBALANCE", "real": True, "max_nodes": 10},
    {"id": "P19_MANAGEMENT_ROLLING_RESTART", "real": True, "max_nodes": 10},
    {"id": "P20_FAILOVER_LATENCY_CURVE_30_50_100", "real": True, "max_nodes": 100},
    {"id": "P21_FAILOVER_LATENCY_CURVE_200", "real": True, "max_nodes": 200},
    {"id": "P22_FAULT_REPLICA_HOST_AZ_STOP", "real": True, "max_nodes": 100},
    {"id": "P23_FAULT_NETWORK_DELAY_LOSS_FLAP", "real": True, "max_nodes": 100},
    {"id": "P24_PARTITION_SPLIT_BRAIN_MATRIX", "real": True, "max_nodes": 100},
    {"id": "P25_FAULT_WORKLOAD_IMPACT_ANALYSIS", "real": True, "max_nodes": 100},
    {"id": "P26_FINAL_REPORT_REGRESSION", "real": True, "max_nodes": 100},
]

COMMON_GATE_NAMES = {
    "harness_precheck",
    "safety_static_scan",
    "scripts_compile",
    "unit_integration_tests",
    "goal_loop_stage_assertion",
}

COMMON_REAL_ARTIFACTS = {
    "phase_summary.json",
    "valkey_e2e_evidence.json",
    "cleanup_report.json",
    "events.jsonl",
    "metrics_timeseries.jsonl",
    "workload_windows.json",
    "quant_summary.json",
}


def phase_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {phase["id"]: phase for phase in manifest.get("phases", [])}


def artifact_names(phase: dict[str, Any]) -> set[str]:
    prefix = f"artifacts/phases/{phase['id']}/"
    return {str(item.get("path", "")).removeprefix(prefix) for item in phase.get("required_artifacts", [])}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--require-worker", action="store_true")
    parser.add_argument("--require-review", action="store_true")
    args = parser.parse_args()

    manifest = load_json(ROOT / "codex" / "phase_manifest.json")
    phases = phase_map(manifest)
    errors: list[str] = []

    if manifest.get("default_max_nodes") != 100:
        errors.append("default_max_nodes must remain exactly 100")
    if manifest.get("automatic_stop_after") != "P26_FINAL_REPORT_REGRESSION":
        errors.append("automatic_stop_after must be P26_FINAL_REPORT_REGRESSION")

    all_ids = [phase.get("id") for phase in manifest.get("phases", [])]
    expected_ids = [stage["id"] for stage in GOAL_STAGES]
    positions = [all_ids.index(stage_id) for stage_id in expected_ids if stage_id in all_ids]
    missing = [stage_id for stage_id in expected_ids if stage_id not in all_ids]
    if missing:
        errors.append(f"missing goal-loop stages: {missing}")
    elif positions != sorted(positions):
        errors.append("goal-loop stages are not in required P15-P26 order")

    p14 = phases.get("P14_SCALE_1000_OPTIN_DRYRUN")
    if not p14:
        errors.append("P14_SCALE_1000_OPTIN_DRYRUN missing")
    else:
        if p14.get("automatic") is not False:
            errors.append("P14 must remain non-automatic")
        if int(p14.get("max_nodes", 0)) != 1000:
            errors.append("P14 max_nodes must remain the opt-in 1000 dry-run")

    for stage in GOAL_STAGES:
        stage_id = stage["id"]
        doc = ROOT / "docs" / "codex" / "goal-loop" / "stages" / f"{stage_id}.md"
        if not doc.exists():
            errors.append(f"{stage_id}: stage document missing: {doc.relative_to(ROOT)}")
        phase = phases.get(stage_id)
        if not phase:
            continue
        if phase.get("automatic") is not True:
            errors.append(f"{stage_id}: goal-loop stages must be automatic")
        if phase.get("real_valkey_required") is not stage["real"]:
            errors.append(f"{stage_id}: real_valkey_required must be {stage['real']}")
        if int(phase.get("max_nodes", -1)) != int(stage["max_nodes"]):
            errors.append(f"{stage_id}: max_nodes must be {stage['max_nodes']}")
        if stage_id == "P15_GOAL_REBASE_HARNESS_EXTENSION" and phase.get("fake_only_allowed") is not True:
            errors.append("P15 must be fake_only_allowed because it is harness-only")
        if stage_id != "P15_GOAL_REBASE_HARNESS_EXTENSION" and phase.get("fake_only_allowed") is not False:
            errors.append(f"{stage_id}: future runtime stages must not be fake-only")

        gate_names = {gate.get("name") for gate in phase.get("gates", [])}
        missing_gates = sorted(COMMON_GATE_NAMES - gate_names)
        if missing_gates:
            errors.append(f"{stage_id}: missing common gates {missing_gates}")
        for gate in phase.get("gates", []):
            command = str(gate.get("command", ""))
            if "scripts/codex_gate.py run" in command or "scripts/codex_gate.py postcheck" in command:
                errors.append(f"{stage_id}/{gate.get('name')}: recursive codex_gate run/postcheck is forbidden")
            if gate.get("real_valkey") and "scripts/valkey_e2e_gate.py" not in command and "scripts/fault_" not in command:
                errors.append(f"{stage_id}/{gate.get('name')}: real_valkey gate must use a real wrapper")
            if stage_id == "P21_FAILOVER_LATENCY_CURVE_200" and gate.get("real_valkey"):
                if "scale_100.yaml" in command or "--min-nodes 200" not in command:
                    errors.append("P21 real gate must target an explicit 200-node config and --min-nodes 200")
        if stage["real"] and not any(gate.get("real_valkey") for gate in phase.get("gates", [])):
            errors.append(f"{stage_id}: missing real_valkey wrapper gate")

        names = artifact_names(phase)
        if stage_id == "P15_GOAL_REBASE_HARNESS_EXTENSION":
            if names != {"phase_summary.json", "quant_summary.json"}:
                errors.append(f"P15 must require only harness phase/quant summaries, got {sorted(names)}")
        else:
            missing_artifacts = sorted(COMMON_REAL_ARTIFACTS - names)
            if missing_artifacts:
                errors.append(f"{stage_id}: missing common real artifacts {missing_artifacts}")
        for artifact in phase.get("required_artifacts", []):
            schema = artifact.get("schema")
            if schema and not (ROOT / schema).exists():
                errors.append(f"{stage_id}: schema missing for {artifact.get('path')}: {schema}")

    if args.phase not in phases:
        errors.append(f"unknown phase: {args.phase}")
    handoff_dir = ROOT / "artifacts" / "goal_loop" / args.phase
    required_handoff = ["CONTEXT_RELOAD.md", "DESIGN_BRIEF.md"]
    if args.require_worker:
        required_handoff.append("WORKER_SUMMARY.md")
    if args.require_review:
        required_handoff.append("REVIEW.md")
    for name in required_handoff:
        path = handoff_dir / name
        if not path.exists():
            errors.append(f"{args.phase}: handoff file missing: {path.relative_to(ROOT)}")
    if args.require_review and (handoff_dir / "REVIEW.md").exists():
        text = (handoff_dir / "REVIEW.md").read_text(encoding="utf-8")
        if "Decision: PASS" not in text:
            errors.append(f"{args.phase}: REVIEW.md must contain exact Decision: PASS")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS goal-loop stage assertion phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
