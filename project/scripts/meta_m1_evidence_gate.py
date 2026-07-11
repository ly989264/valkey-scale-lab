#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DEFAULT_EVIDENCE_ROOT = WORKSPACE_ROOT / "loop_evidence" / "meta_runs" / "milestone1-v2" / "evidence"
REQUIRED_LIFECYCLE = {
    "resource_preflight",
    "runtime_start",
    "cluster_form",
    "stabilize",
    "baseline_workload",
    "management_matrix",
    "fault_matrix",
    "recovery",
    "artifact_validation",
    "analysis",
    "report",
    "cleanup",
}
REQUIRED_SCENARIOS = {
    "add_remove_node",
    "reshard_rebalance",
    "rolling_restart",
    "bounded_stability",
    "primary_failover",
    "replica_stop",
    "node_host_stop",
    "az_stop",
    "network_delay",
    "network_loss",
    "network_partition",
    "network_flap",
    "minority_majority",
    "split_brain_detection",
}
REQUIRED_ARTIFACT_KINDS = {
    "run_metadata",
    "command_log",
    "events",
    "metrics",
    "workload_windows",
    "management_results",
    "fault_results",
    "cleanup_report",
    "analysis_summary",
    "report_index",
}
SOURCE_INPUTS = ("src", "scripts", "schemas", "config", "templates")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate exact-scale real Milestone 1 evidence")
    parser.add_argument("--scale", required=True, type=int, choices=(50, 200))
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    return parser


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_tree_digest(project_root: Path = PROJECT_ROOT) -> str:
    digest = hashlib.sha256()
    for name in SOURCE_INPUTS:
        root = project_root / name
        digest.update(name.encode())
        if not root.exists():
            digest.update(b"\0MISSING")
            continue
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
            if any(part in {"__pycache__", ".pytest_cache", ".mypy_cache"} for part in path.parts):
                continue
            digest.update(str(path.relative_to(project_root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def evaluate(scale: int, evidence_root: Path) -> list[str]:
    base = (evidence_root / f"scale-{scale}").resolve()
    admission_path = base / "admission.json"
    try:
        admission = _load(admission_path)
    except ValueError as exc:
        return [str(exc)]
    errors: list[str] = []
    expected_scalars = {
        "schema_version": "meta-m1-admission-v1",
        "execution_kind": "REAL_VALKEY_EXACT_SCALE",
        "requested_nodes": scale,
        "observed_nodes": scale,
        "status": "PASS",
    }
    for key, expected in expected_scalars.items():
        if admission.get(key) != expected:
            errors.append(f"{key} must be {expected!r}, got {admission.get(key)!r}")
    if not isinstance(admission.get("run_id"), str) or not admission["run_id"].strip():
        errors.append("run_id is required")
    if not re.fullmatch(r"[0-9a-f]{40}", str(admission.get("source_commit", ""))):
        errors.append("source_commit must be a full Git commit hash")
    expected_source_digest = source_tree_digest()
    if admission.get("source_tree_digest") != expected_source_digest:
        errors.append("source_tree_digest does not match the current product tree; evidence is stale")

    versions = admission.get("valkey_versions")
    if not isinstance(versions, list) or not versions or any(not re.fullmatch(r"9\.1(?:\.\d+)?", str(v)) for v in versions):
        errors.append("valkey_versions must contain only independently observed 9.1.x versions")

    preflight = admission.get("resource_preflight")
    if not isinstance(preflight, dict) or preflight.get("status") != "PASS" or preflight.get("requested_nodes") != scale:
        errors.append("resource_preflight must PASS for the exact requested scale")
    if scale == 200 and not isinstance(preflight, dict):
        errors.append("200-node admission requires resource preflight")

    probe = admission.get("independent_probe")
    if not isinstance(probe, dict):
        errors.append("independent_probe is required")
    else:
        expected_probe = {"status": "PASS", "observed_nodes": scale, "cluster_state": "ok", "slots_assigned": 16384, "slots_ok": 16384}
        for key, expected in expected_probe.items():
            if probe.get(key) != expected:
                errors.append(f"independent_probe.{key} must be {expected!r}")
        if not isinstance(probe.get("endpoint_count"), int) or probe["endpoint_count"] < 2:
            errors.append("independent_probe must use at least two endpoints")

    lifecycle = admission.get("lifecycle_steps")
    lifecycle_map = {str(item.get("id")): item for item in lifecycle if isinstance(item, dict)} if isinstance(lifecycle, list) else {}
    missing_lifecycle = sorted(REQUIRED_LIFECYCLE - lifecycle_map.keys())
    if missing_lifecycle:
        errors.append(f"missing lifecycle steps: {missing_lifecycle}")
    for step_id in sorted(REQUIRED_LIFECYCLE & lifecycle_map.keys()):
        step = lifecycle_map[step_id]
        if step.get("status") != "PASS" or not isinstance(step.get("duration_ms"), (int, float)) or step["duration_ms"] < 0:
            errors.append(f"lifecycle step {step_id} must PASS with non-negative duration_ms")

    scenarios = admission.get("scenario_matrix")
    scenario_map = {str(item.get("id")): item for item in scenarios if isinstance(item, dict)} if isinstance(scenarios, list) else {}
    missing_scenarios = sorted(REQUIRED_SCENARIOS - scenario_map.keys())
    if missing_scenarios:
        errors.append(f"missing real scenarios: {missing_scenarios}")
    for scenario_id in sorted(REQUIRED_SCENARIOS & scenario_map.keys()):
        if scenario_map[scenario_id].get("status") != "REAL_PASS":
            errors.append(f"scenario {scenario_id} must have status REAL_PASS")

    cleanup = admission.get("cleanup")
    if not isinstance(cleanup, dict) or cleanup.get("status") != "PASS" or cleanup.get("residual_owned_resources") != 0:
        errors.append("cleanup must PASS with zero residual owned resources")

    artifacts = admission.get("artifacts")
    artifact_items = artifacts if isinstance(artifacts, list) else []
    kinds = {str(item.get("kind")) for item in artifact_items if isinstance(item, dict)}
    missing_kinds = sorted(REQUIRED_ARTIFACT_KINDS - kinds)
    if missing_kinds:
        errors.append(f"missing artifact kinds: {missing_kinds}")
    for item in artifact_items:
        if not isinstance(item, dict):
            errors.append("artifact entries must be objects")
            continue
        raw_path = item.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            errors.append("artifact path is required")
            continue
        path = (base / raw_path).resolve()
        if not path.is_relative_to(base):
            errors.append(f"artifact escapes evidence directory: {raw_path}")
            continue
        if not path.is_file():
            errors.append(f"artifact is missing: {raw_path}")
            continue
        if item.get("sha256") != _sha256(path):
            errors.append(f"artifact hash mismatch: {raw_path}")
        lowered = raw_path.lower()
        if any(token in lowered for token in ("fixture", "fake", "synthetic", "example")):
            errors.append(f"artifact path is not admissible as real evidence: {raw_path}")

    return errors


def main() -> int:
    args = _parser().parse_args()
    errors = evaluate(args.scale, args.evidence_root)
    payload = {"status": "PASS" if not errors else "FAIL", "scale": args.scale, "errors": errors}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
