#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from codex_gate import validate_artifact  # noqa: E402
from schema_validator import load_json  # noqa: E402

REQUIRED_DETECTORS = {
    "primary_slot_assignment_overlap",
    "partition_side_cluster_view_divergence",
    "conflicting_write_probe",
    "old_primary_accepts_write_after_promotion",
}
STRICT_FAULT_STAGES = {
    "P33_FAULT_FAILOVER_MATRIX_50_REAL": 50,
    "P34_FAULT_FAILOVER_MATRIX_100_REAL": 100,
    "P35_FAULT_FAILOVER_MATRIX_200_REAL": 200,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--scale", type=int)
    args = parser.parse_args()
    strict_scale = STRICT_FAULT_STAGES.get(args.phase)
    if args.phase != "P24_PARTITION_SPLIT_BRAIN_MATRIX" and strict_scale is None:
        print(f"PASS split-brain report not required for phase={args.phase}")
        return 0

    path = ROOT / "artifacts" / "phases" / args.phase / "split_brain_report.json"
    errors = validate_artifact(path, ROOT / "schemas/artifact/split_brain_report.schema.json")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    report = load_json(path)
    if strict_scale is not None:
        if args.scale != strict_scale:
            errors.append(f"{args.phase} requires --scale {strict_scale}")
        if report.get("status") != "PASS":
            errors.append("strict split_brain_report status must be PASS")
        if report.get("phase_id") != args.phase or report.get("stage_id") != args.phase:
            errors.append(f"strict split_brain_report phase_id and stage_id must be {args.phase}")
        if report.get("scale") != strict_scale or report.get("node_count") != strict_scale:
            errors.append(f"strict split_brain_report scale and node_count must be {strict_scale}")
    detectors = report.get("detectors_run", [])
    detectors_set = set(detectors if isinstance(detectors, list) else [])
    missing_entries = report.get("missing_detectors_with_reason", [])
    missing_by_name = {item.get("detector"): item for item in missing_entries if isinstance(item, dict)}
    window = report.get("split_brain_window_ms")
    if window == 0 and not detectors:
        errors.append("split_brain_window_ms=0 requires at least one detector to have run")
    if window == "MISSING" and not report.get("missing_detectors_with_reason"):
        errors.append("MISSING split_brain_window_ms requires missing_detectors_with_reason")
    for detector in REQUIRED_DETECTORS:
        if detector not in detectors_set and detector not in missing_by_name:
            errors.append(f"required split-brain detector {detector!r} must run or have an explicit missing reason")
        if strict_scale is not None and detector not in detectors_set:
            errors.append(f"strict split-brain detector {detector!r} must actually run")
    for idx, missing in enumerate(report.get("missing_detectors_with_reason", [])):
        if not isinstance(missing, dict) or not missing.get("detector") or not missing.get("reason"):
            errors.append(f"missing_detectors_with_reason[{idx}] must include detector and reason")
        elif missing.get("status") not in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON", None}:
            errors.append(f"missing_detectors_with_reason[{idx}] has invalid status {missing.get('status')!r}")
    for field in ["indicator_start_ms", "indicator_end_ms"]:
        value = report.get(field)
        if value == "MISSING":
            if not report.get("missing_detectors_with_reason"):
                errors.append(f"{field}=MISSING requires missing_detectors_with_reason")
        elif not isinstance(value, (int, float)):
            errors.append(f"{field} must be numeric or MISSING with reason")
    detector_results = report.get("detector_results", [])
    if not isinstance(detector_results, list) or not detector_results:
        errors.append("split_brain_report.detector_results must be non-empty")
    for idx, detector in enumerate(detector_results):
        if not isinstance(detector, dict):
            errors.append(f"detector_results[{idx}] must be object")
            continue
        name = detector.get("detector")
        if not name:
            errors.append(f"detector_results[{idx}] missing detector name")
        if detector.get("ran") is not True:
            errors.append(f"detector_results[{idx}] must record ran=true")
        if detector.get("status") != "PASS":
            errors.append(f"detector_results[{idx}] must record status=PASS")
        if strict_scale is not None:
            if name not in REQUIRED_DETECTORS:
                errors.append(f"detector_results[{idx}] unexpected strict detector {name!r}")
            if not detector.get("evidence_ref") or detector.get("evidence_ref") == "MISSING":
                errors.append(f"detector_results[{idx}] evidence_ref required")
        for field in ["started_at_ms", "ended_at_ms"]:
            if not isinstance(detector.get(field), (int, float)):
                errors.append(f"detector_results[{idx}] {field} must be numeric")
    side_comparisons = report.get("side_view_comparisons", [])
    if not isinstance(side_comparisons, list) or not side_comparisons:
        errors.append("split_brain_report must include side_view_comparisons")
    else:
        for idx, comparison in enumerate(side_comparisons):
            if not isinstance(comparison, dict) or not comparison.get("majority") or not comparison.get("minority"):
                errors.append(f"side_view_comparisons[{idx}] must include majority and minority views")
            elif strict_scale is not None and comparison.get("status") != "PASS":
                errors.append(f"side_view_comparisons[{idx}] must record status=PASS")
    if window == 0:
        ran_core = {"primary_slot_assignment_overlap", "partition_side_cluster_view_divergence", "conflicting_write_probe"}.issubset(detectors_set)
        if not ran_core:
            errors.append("split_brain_window_ms=0 requires core detectors to have run, not just a missing-detector reason")
    if report.get("indicator_observed") is True:
        if not (report.get("conflicting_slots") or report.get("conflicting_nodes") or report.get("conflicting_write_keys")):
            errors.append("observed split-brain indicator requires conflicting slots, nodes, or write keys")
        if not isinstance(window, (int, float)) or window <= 0:
            errors.append("observed split-brain indicator requires positive split_brain_window_ms")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS split-brain report phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
