#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ROWS = {"fake_schema_unit", "smoke_10", "real_30", "real_50", "real_100", "real_200", "dry_run_gt_200"}
REAL_ROWS = {"smoke_10": 10, "real_30": 30, "real_50": 50, "real_100": 100, "real_200": 200}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--artifact-dir")
    args = parser.parse_args()

    base = Path(args.artifact_dir) if args.artifact_dir else ROOT / "artifacts" / "phases" / args.phase
    errors: list[str] = []
    ledger = _load_json(base / "coverage_ledger.json", errors, "coverage_ledger")
    rows = ledger.get("rows", []) if ledger else []
    if not isinstance(rows, list):
        errors.append("coverage_ledger.rows must be a list")
        rows = []
    by_id = {row.get("coverage_id"): row for row in rows if isinstance(row, dict)}
    missing = sorted(REQUIRED_ROWS - set(by_id))
    if missing:
        errors.append(f"missing server profile coverage rows: {missing}")
    for coverage_id in sorted(REQUIRED_ROWS & set(by_id)):
        row = by_id[coverage_id]
        _validate_row(base, coverage_id, row, errors)
    real_passes = [coverage_id for coverage_id in REAL_ROWS if by_id.get(coverage_id, {}).get("status") == "PASS"]
    if set(real_passes) != set(REAL_ROWS):
        errors.append(f"all real server profile rows must PASS, got passing rows {sorted(real_passes)}")
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS no server profile partial coverage phase={args.phase}")
    return 0


def _validate_row(base: Path, coverage_id: str, row: dict[str, Any], errors: list[str]) -> None:
    status = row.get("status")
    refs = row.get("artifact_refs")
    if not isinstance(refs, list) or not refs:
        errors.append(f"{coverage_id}: artifact_refs required")
        refs = []
    if coverage_id in REAL_ROWS:
        expected_nodes = REAL_ROWS[coverage_id]
        if status != "PASS":
            errors.append(f"{coverage_id}: real Valkey coverage must be PASS, got {status!r}")
        if row.get("execution_mode") != "real_valkey":
            errors.append(f"{coverage_id}: execution_mode must be real_valkey")
        if not any(_real_evidence_ok(base, ref, expected_nodes, errors, coverage_id) for ref in refs):
            errors.append(f"{coverage_id}: no artifact_ref contains valid real Valkey server profile evidence for {expected_nodes} nodes")
    elif coverage_id == "fake_schema_unit":
        if status != "PASS":
            errors.append("fake_schema_unit: status must be PASS")
        if row.get("execution_mode") not in {"unit_schema", "fake_schema"}:
            errors.append("fake_schema_unit: execution_mode must be unit_schema")
    elif coverage_id == "dry_run_gt_200":
        if status not in {"PASS", "DRY_RUN_PASS"}:
            errors.append(f"dry_run_gt_200: status must be PASS or DRY_RUN_PASS, got {status!r}")
        if row.get("execution_mode") not in {"dry_run", "dry_run_projection"}:
            errors.append("dry_run_gt_200: execution_mode must be dry_run_projection")
        if not any(_dry_run_projection_ok(base, ref, errors) for ref in refs):
            errors.append("dry_run_gt_200: no valid greater-than-200 dry-run projection artifact")


def _real_evidence_ok(base: Path, ref: str, expected_nodes: int, errors: list[str], coverage_id: str) -> bool:
    path = _resolve_path(base, str(ref))
    if not path.exists() or path.suffix != ".json":
        return False
    evidence = _load_json(path, errors, f"{coverage_id}:{ref}")
    if not evidence:
        return False
    if evidence.get("artifact_type") != "valkey_e2e_evidence":
        return False
    if evidence.get("status") != "PASS" or evidence.get("probe_result") != "PASS":
        errors.append(f"{coverage_id}: evidence {ref} did not PASS")
        return False
    if evidence.get("real_valkey") is not True:
        errors.append(f"{coverage_id}: evidence {ref} does not declare real_valkey=true")
        return False
    observed = _int(evidence.get("nodes_observed"), 0)
    requested = _int(evidence.get("nodes_requested", evidence.get("min_nodes_requested")), 0)
    if observed < expected_nodes or requested < expected_nodes:
        errors.append(f"{coverage_id}: evidence {ref} observed/requested {observed}/{requested}, expected at least {expected_nodes}")
        return False
    versions = evidence.get("valkey_versions", [])
    if not isinstance(versions, list) or not versions or not all(str(version).startswith("9.1.") for version in versions):
        errors.append(f"{coverage_id}: evidence {ref} lacks Valkey 9.1.x versions")
        return False
    runtime = evidence.get("runtime", {})
    if not _has_profile(runtime):
        errors.append(f"{coverage_id}: evidence {ref} runtime lacks server profile fields")
        return False
    processes = evidence.get("node_processes", [])
    if not isinstance(processes, list) or len(processes) < expected_nodes:
        errors.append(f"{coverage_id}: evidence {ref} node_processes missing expected nodes")
        return False
    for index, process in enumerate(processes[:expected_nodes]):
        if not isinstance(process, dict):
            errors.append(f"{coverage_id}: evidence {ref} node_processes[{index}] must be object")
            return False
        if _int(process.get("effective_io_threads"), 0) < 1:
            errors.append(f"{coverage_id}: evidence {ref} node_processes[{index}] missing effective_io_threads")
            return False
        if _int(process.get("effective_node_memory_limit_mb"), 0) != 64:
            errors.append(f"{coverage_id}: evidence {ref} node_processes[{index}] must use 64 MB")
            return False
    return True


def _dry_run_projection_ok(base: Path, ref: str, errors: list[str]) -> bool:
    path = _resolve_path(base, str(ref))
    if not path.exists() or path.suffix != ".json":
        return False
    projection = _load_json(path, errors, f"dry_run_gt_200:{ref}")
    if not projection:
        return False
    node_count = _int(projection.get("node_count", projection.get("nodes_requested")), 0)
    if node_count <= 200:
        errors.append(f"dry_run_gt_200: projection {ref} must cover more than 200 nodes")
        return False
    runtime = projection.get("runtime", {})
    if projection.get("real_valkey") is True or projection.get("runtime_resources_created") is True or runtime.get("real_valkey") is True:
        errors.append(f"dry_run_gt_200: projection {ref} must not claim real runtime evidence")
        return False
    if runtime.get("dry_run") is not True and projection.get("dry_run") is not True:
        errors.append(f"dry_run_gt_200: projection {ref} must declare dry_run=true")
        return False
    profile = projection.get("effective_server_profile") or runtime.get("server_profile") or projection.get("server_profile")
    if not isinstance(profile, dict) or _int(profile.get("effective_node_memory_limit_mb"), 0) != 64:
        errors.append(f"dry_run_gt_200: projection {ref} lacks 64 MB effective server profile")
        return False
    if _int(profile.get("total_valkey_threads"), 0) > _int(profile.get("io_threads_max_total"), 0):
        errors.append(f"dry_run_gt_200: projection {ref} exceeds io-thread budget")
        return False
    return True


def _has_profile(runtime: Any) -> bool:
    if not isinstance(runtime, dict):
        return False
    profile = runtime.get("server_profile")
    if isinstance(profile, dict):
        return _int(profile.get("effective_io_threads"), 0) >= 1 and _int(profile.get("effective_node_memory_limit_mb"), 0) == 64
    return _int(runtime.get("effective_io_threads"), 0) >= 1 and _int(runtime.get("effective_node_memory_limit_mb"), 0) == 64


def _load_json(path: Path, errors: list[str], label: str) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"{label} missing: {path}")
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{label}: invalid JSON: {exc}")
        return {}
    if not isinstance(obj, dict):
        errors.append(f"{label}: must be JSON object")
        return {}
    return obj


def _resolve_path(base: Path, ref: str) -> Path:
    path = Path(ref)
    if path.is_absolute():
        return path
    for candidate in [ROOT / path, base / path]:
        if candidate.exists():
            return candidate
    return ROOT / path


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    raise SystemExit(main())
