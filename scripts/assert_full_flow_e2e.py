#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import load_jsonl, phase_dir, print_errors, require_json, split_csv  # noqa: E402

REQUIRED_STEPS = [
    "config_validate",
    "resource_preflight",
    "plan_cluster",
    "create_cluster",
    "meet_nodes",
    "assign_slots",
    "add_replica",
    "baseline_workload",
    "telemetry_collect",
    "analysis_build",
    "report_render",
    "cleanup_verify",
]


def _repo_path_exists(ref: str) -> bool:
    return bool(ref) and not Path(ref).is_absolute() and ".." not in Path(ref).parts and (ROOT / ref).exists()


def _assert_refs(label: str, refs: Any, errors: list[str]) -> None:
    if not isinstance(refs, list) or not refs:
        errors.append(f"{label}: non-empty refs required")
        return
    for ref in refs:
        if not isinstance(ref, str) or not _repo_path_exists(ref):
            errors.append(f"{label}: referenced artifact missing or unsafe: {ref!r}")


def _assert_result_row(row: dict[str, Any], expected_scale: int, errors: list[str]) -> None:
    label = f"scale {expected_scale}"
    if row.get("status") != "PASS":
        errors.append(f"{label}: full-flow status must be PASS")
    for key in ["scale", "node_count", "nodes_requested", "nodes_observed"]:
        if row.get(key) != expected_scale:
            errors.append(f"{label}: {key} must be exactly {expected_scale}, got {row.get(key)!r}")
    if row.get("real_valkey") is not True:
        errors.append(f"{label}: real_valkey must be true")
    if row.get("data_path_result") != "PASS":
        errors.append(f"{label}: data_path_result must be PASS")
    expected_scenario = f"strict_full_flow_{expected_scale}"
    if row.get("scenario_name") != expected_scenario:
        errors.append(f"{label}: scenario_name must be {expected_scenario}")
    if int(row.get("scale", 0) or 0) == 200 and row.get("nodes_observed") != 200:
        errors.append("scale 200: 200-node full flow must not downshift")
    steps = row.get("steps")
    if not isinstance(steps, list):
        errors.append(f"{label}: steps must be a list")
        steps = []
    by_step = {str(step.get("step_name")): step for step in steps if isinstance(step, dict)}
    missing_steps = sorted(set(REQUIRED_STEPS) - set(by_step))
    if missing_steps:
        errors.append(f"{label}: missing required steps {missing_steps}")
    for step_name in REQUIRED_STEPS:
        step = by_step.get(step_name)
        if not isinstance(step, dict):
            continue
        if step.get("status") != "PASS":
            errors.append(f"{label}:{step_name}: status must be PASS")
        if step.get("coverage_id") != f"{expected_scale}.lifecycle.{step_name}":
            errors.append(f"{label}:{step_name}: coverage_id must be {expected_scale}.lifecycle.{step_name}")
        _assert_refs(f"{label}:{step_name}:source_evidence_refs", step.get("source_evidence_refs"), errors)
    _assert_refs(f"{label}:management_execution_refs", row.get("management_execution_refs"), errors)
    _assert_refs(f"{label}:fault_execution_refs", row.get("fault_execution_refs"), errors)
    for key in ["analysis_ref", "report_ref", "evidence_ref", "cleanup_ref"]:
        ref = row.get(key)
        if not isinstance(ref, str) or not _repo_path_exists(ref):
            errors.append(f"{label}: {key} missing or does not exist: {ref!r}")
        elif f"artifacts/phases/{row.get('phase_id') or 'P36_FULL_FLOW_E2E_50_100_200_REAL'}/full_flow_{expected_scale}/" not in ref and key in {"analysis_ref", "report_ref", "evidence_ref", "cleanup_ref"}:
            errors.append(f"{label}: {key} must point to the scoped full_flow_{expected_scale} artifact")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--scales", required=True)
    args = parser.parse_args()
    scales = [int(value) for value in split_csv(args.scales)]
    base = phase_dir(args.phase)
    errors: list[str] = []
    matrix = require_json(base / "full_flow_matrix.json", errors, "full-flow matrix")
    try:
        results = load_jsonl(base / "full_flow_results.jsonl")
    except Exception as exc:
        results = []
        errors.append(f"full_flow_results.jsonl: {exc}")
    if matrix:
        matrix_scales = {int(row.get("scale", 0)) for row in matrix.get("scales", []) if isinstance(row, dict)}
        missing = sorted(set(scales) - matrix_scales)
        if missing:
            errors.append(f"full_flow_matrix missing scales {missing}")
        if matrix.get("status") != "PASS":
            errors.append("full_flow_matrix status must be PASS")
        required_steps = matrix.get("required_steps")
        if required_steps != REQUIRED_STEPS:
            errors.append(f"full_flow_matrix required_steps must be {REQUIRED_STEPS}")
    result_scales = {int(row.get("scale", 0)) for row in results if isinstance(row, dict)}
    for scale in scales:
        if scale not in result_scales:
            errors.append(f"full_flow_results missing scale {scale}")
    by_scale = {int(row.get("scale", 0)): row for row in results if isinstance(row, dict)}
    for scale in scales:
        row = by_scale.get(scale)
        if isinstance(row, dict):
            _assert_result_row(row, scale, errors)
    if errors:
        return print_errors(errors)
    print(f"PASS full-flow e2e phase={args.phase} scales={args.scales}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
