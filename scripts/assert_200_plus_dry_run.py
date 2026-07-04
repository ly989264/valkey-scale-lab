#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import load_json, load_jsonl, phase_dir, print_errors, require_json, split_csv  # noqa: E402

REQUIRED_STEPS = [
    "config_validate",
    "resource_estimate",
    "plan_cluster",
    "host_az_placement_schedule",
    "port_directory_collision_check",
    "artifact_schema_projection",
    "report_projection",
    "no_runtime_created_proof",
]
REQUIRED_ROWS = [
    "config_validate_dry_run",
    "resource_preflight_dry_run",
    "plan_cluster_dry_run",
    "placement_schedule_dry_run",
    "port_directory_collision_check_dry_run",
    "artifact_schema_projection_dry_run",
    "no_runtime_created_proof",
    "report_projection_dry_run",
]


def rel_path(value: str) -> Path:
    return ROOT / value


def add_claim_errors(obj: Any, errors: list[str], label: str, path: str = "$") -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            lowered = key.lower()
            here = f"{path}.{key}"
            if key == "execution_mode" and value != "dry_run":
                errors.append(f"{label}{here}: execution_mode must be dry_run")
            if lowered in {"real_valkey", "real_valkey_claimed", "live_endpoint_claimed", "workload_executed", "runtime_resources_created"} and value not in {False, 0}:
                errors.append(f"{label}{here}: forbidden live/runtime/workload claim value {value!r}")
            if lowered == "probe_result" and value == "PASS":
                errors.append(f"{label}{here}: live probe PASS claims are forbidden in P37 dry-run artifacts")
            if "endpoint" in lowered and value not in {False, 0, "MISSING"} and not (
                isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON"}
            ):
                errors.append(f"{label}{here}: endpoint claims are forbidden in P37 dry-run artifacts")
            add_claim_errors(value, errors, label, here)
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            add_claim_errors(value, errors, label, f"{path}[{idx}]")


def require_ref(ref: str, errors: list[str], label: str) -> dict[str, Any] | None:
    if not ref:
        errors.append(f"{label}: missing artifact ref")
        return None
    path = rel_path(ref)
    if not path.exists():
        errors.append(f"{label}: referenced artifact missing: {ref}")
        return None
    if path.suffix == ".json":
        try:
            obj = load_json(path)
        except Exception as exc:
            errors.append(f"{label}: referenced JSON invalid {ref}: {exc}")
            return None
        if isinstance(obj, dict):
            add_claim_errors(obj, errors, f"{ref}:")
            if ref.endswith("coverage_ledger.json"):
                for row in obj.get("rows", []):
                    if row.get("execution_mode") != "dry_run":
                        errors.append(f"{ref}: coverage row {row.get('coverage_id')} must be dry_run")
            elif obj.get("execution_mode") != "dry_run":
                errors.append(f"{ref}: top-level execution_mode must be dry_run")
            return obj
    return None


def proof_errors(proof: dict[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    if proof.get("status") != "PASS":
        errors.append(f"{label}: status must be PASS")
    if proof.get("execution_mode") != "dry_run":
        errors.append(f"{label}: execution_mode must be dry_run")
    if proof.get("runtime_resources_created") not in {False, 0}:
        errors.append(f"{label}: runtime_resources_created must be false")
    created = proof.get("created_resources", [])
    if created is not None and created != [] and created != ():
        errors.append(f"{label}: created_resources must be empty")
    for key in ["before_inventory", "after_inventory"]:
        if not isinstance(proof.get(key), dict):
            errors.append(f"{label}: {key} must be an object")
    return errors


def coverage_errors(phase: str, targets: set[int], base: Path) -> list[str]:
    errors: list[str] = []
    registry_path = ROOT / "artifacts" / "coverage" / "strict_coverage_registry.json"
    ledger_path = base / "coverage_ledger.json"
    try:
        registry = load_json(registry_path)
    except Exception as exc:
        return [f"coverage registry invalid: {exc}"]
    ledger = require_json(ledger_path, errors, "P37 coverage ledger")
    registry_rows = {row.get("coverage_id"): row for row in registry.get("rows", []) if isinstance(row, dict)}
    ledger_rows = {row.get("coverage_id"): row for row in (ledger or {}).get("rows", []) if isinstance(row, dict)}
    expected_ids = {f"{target}.dry_run.{row}" for target in targets for row in REQUIRED_ROWS}
    missing_registry = sorted(expected_ids - set(registry_rows))
    missing_ledger = sorted(expected_ids - set(ledger_rows))
    if missing_registry:
        errors.append(f"coverage registry missing P37 IDs: {missing_registry}")
    if missing_ledger:
        errors.append(f"coverage ledger missing P37 IDs: {missing_ledger}")
    for coverage_id in sorted(expected_ids):
        for source, rows in [("registry", registry_rows), ("ledger", ledger_rows)]:
            row = rows.get(coverage_id)
            if not row:
                continue
            if row.get("stage_owner") != phase:
                errors.append(f"{source}:{coverage_id}: stage_owner must be {phase}")
            if row.get("execution_mode") != "dry_run":
                errors.append(f"{source}:{coverage_id}: execution_mode must be dry_run")
            if row.get("status") != "DRY_RUN_PASS":
                errors.append(f"{source}:{coverage_id}: status must be DRY_RUN_PASS")
            joined_validation = " ".join(row.get("validation_artifacts", []))
            if "no_runtime_created_proof" not in joined_validation:
                errors.append(f"{source}:{coverage_id}: validation_artifacts must include no-runtime proof")
            if not row.get("review_ref"):
                errors.append(f"{source}:{coverage_id}: review_ref placeholder is required")
    return errors


def validate_phase(phase: str, min_targets: set[int]) -> list[str]:
    base = phase_dir(phase)
    errors: list[str] = []
    target_doc = require_json(base / "dry_run_targets.json", errors, "dry-run targets")
    proof = require_json(base / "no_runtime_created_proof.json", errors, "no-runtime proof")
    required_json = [
        "phase_summary.json",
        "dry_run_targets.json",
        "resource_estimates.json",
        "placement_schedules.json",
        "no_runtime_created_proof.json",
        "report_projection_index.json",
        "coverage_ledger.json",
        "quant_summary.json",
    ]
    for name in required_json:
        obj = require_json(base / name, errors, name)
        if obj:
            add_claim_errors(obj, errors, f"{name}:")
            if name != "coverage_ledger.json" and obj.get("execution_mode") != "dry_run":
                errors.append(f"{name}: execution_mode must be dry_run")
    try:
        rows = load_jsonl(base / "dry_run_results.jsonl")
    except Exception as exc:
        rows = []
        errors.append(f"dry_run_results.jsonl: {exc}")
    if target_doc:
        observed = set()
        for value in target_doc.get("targets", []):
            try:
                target = int(value)
            except Exception:
                errors.append(f"dry_run_targets.json: non-integer target {value!r}")
                continue
            if target <= 200:
                errors.append(f"dry_run_targets.json: target must be above 200: {target}")
            observed.add(target)
        missing = sorted(min_targets - observed)
        if missing:
            errors.append(f"missing dry-run targets above 200: {missing}")
    if proof:
        errors.extend(proof_errors(proof, "no_runtime_created_proof.json"))
    by_target: dict[int, dict[str, Any]] = {}
    for row in rows:
        add_claim_errors(row, errors, "dry_run_results.jsonl:")
        if row.get("execution_mode") != "dry_run":
            errors.append(f"{row.get('target_nodes')}: execution_mode must be dry_run")
        try:
            target = int(row.get("target_nodes", 0))
        except Exception:
            errors.append(f"{row.get('target_nodes')}: target_nodes must be an integer")
            continue
        if target <= 200:
            errors.append(f"{target}: target must be above 200")
        if target in by_target:
            errors.append(f"{target}: duplicate dry_run_results row")
        by_target[target] = row
        steps = row.get("sequence_steps")
        if not isinstance(steps, list):
            errors.append(f"{target}: sequence_steps must be a list")
            continue
        observed_steps = [step.get("name") for step in steps if isinstance(step, dict)]
        if observed_steps != REQUIRED_STEPS:
            errors.append(f"{target}: sequence_steps must be exactly {REQUIRED_STEPS}, got {observed_steps}")
        for step in steps:
            if not isinstance(step, dict):
                errors.append(f"{target}: sequence step must be an object")
                continue
            status = step.get("status")
            if status not in {"PASS", "DRY_RUN_PASS"}:
                errors.append(f"{target}/{step.get('name')}: status must be PASS or DRY_RUN_PASS")
            require_ref(str(step.get("artifact_ref", "")), errors, f"{target}/{step.get('name')}")
        for key in [
            "config_validation_ref",
            "resource_estimate_ref",
            "plan_ref",
            "placement_schedule_ref",
            "collision_check_ref",
            "artifact_schema_projection_ref",
            "report_projection_ref",
            "no_runtime_created_proof_ref",
        ]:
            require_ref(str(row.get(key, "")), errors, f"{target}/{key}")
        target_proof_ref = str(row.get("no_runtime_created_proof_ref", ""))
        target_proof = require_ref(target_proof_ref, errors, f"{target}/no_runtime_created_proof_ref")
        if target_proof:
            errors.extend(proof_errors(target_proof, target_proof_ref))
    missing_rows = sorted(min_targets - set(by_target))
    if missing_rows:
        errors.append(f"dry_run_results.jsonl missing targets: {missing_rows}")
    errors.extend(coverage_errors(phase, min_targets, base))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--min-targets", required=True)
    args = parser.parse_args()
    targets = {int(value) for value in split_csv(args.min_targets)}
    errors = validate_phase(args.phase, targets)
    if errors:
        return print_errors(errors)
    print(f"PASS 200-plus dry-run phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
