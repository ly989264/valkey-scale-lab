#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from codex_gate import validate_artifact  # noqa: E402
from schema_validator import load_json  # noqa: E402

EXPECTED = {
    "P20_FAILOVER_LATENCY_CURVE_30_50_100": {"rungs": {30, 50, 100}, "sample_file": "failover_latency_samples.jsonl", "curve_file": "failover_latency_curve.json"},
    "P21_FAILOVER_LATENCY_CURVE_200": {"rungs": {200}, "sample_file": "failover_latency_samples_200.jsonl", "curve_file": "failover_latency_curve_200.json"},
}
STRICT_FAULT_STAGES = {
    "P33_FAULT_FAILOVER_MATRIX_50_REAL": 50,
    "P34_FAULT_FAILOVER_MATRIX_100_REAL": 100,
    "P35_FAULT_FAILOVER_MATRIX_200_REAL": 200,
}
LATENCY_TIMESTAMP_TOLERANCE_MS = 1000.0


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return round(ordered[index], 3)


def require_numeric(sample: dict[str, Any], field: str, errors: list[str]) -> float | None:
    value = sample.get(field)
    if isinstance(value, (int, float)):
        return float(value)
    errors.append(f"{sample.get('sample_id')}: {field} must be numeric, got {value!r}")
    return None


def validate_p20_semantics(base: Path, samples: list[dict[str, Any]], curve: dict[str, Any], errors: list[str]) -> None:
    for rung in [30, 50, 100]:
        preflight = base / f"resource_preflight_{rung}.json"
        if not preflight.exists():
            errors.append(f"P20 requires resource_preflight_{rung}.json")
            continue
        report = load_json(preflight)
        if report.get("status") != "PASS" or report.get("can_run") is not True or report.get("node_count") != rung:
            errors.append(f"P20 resource preflight for rung {rung} must PASS with exact node_count")

    seen_sample_ids: set[str] = set()
    seen_run_ids: set[str] = set()
    seen_state_refs: set[str] = set()
    timing_signatures: set[tuple[Any, ...]] = set()
    samples_by_rung: dict[int, list[dict[str, Any]]] = {30: [], 50: [], 100: []}
    for sample in samples:
        sample_id = str(sample.get("sample_id", ""))
        node_count = sample.get("node_count")
        if sample_id in seen_sample_ids:
            errors.append(f"duplicate sample_id {sample_id}")
        seen_sample_ids.add(sample_id)
        if sample.get("status") != "PASS":
            errors.append(f"{sample_id}: status must be PASS")
        if sample.get("real_valkey") is not True:
            errors.append(f"{sample_id}: real_valkey must be true")
        if node_count not in samples_by_rung:
            errors.append(f"{sample_id}: unexpected node_count={node_count}")
            continue
        if node_count == 100 and sample.get("rung") != 100:
            errors.append(f"{sample_id}: 100-node sample must have rung=100")
        samples_by_rung[int(node_count)].append(sample)
        for field in [
            "run_id",
            "state_ref",
            "evidence_ref",
            "cleanup_ref",
            "target_primary_node_id",
            "target_primary_az_id",
            "target_primary_host_id",
            "fault_injection_method",
            "promotion_detection_method",
            "slot_coverage_detection_method",
            "workload_impact_ref",
        ]:
            if not sample.get(field) or sample.get(field) == "MISSING":
                errors.append(f"{sample_id}: {field} required")
        if sample.get("cleanup_status") != "PASS":
            errors.append(f"{sample_id}: cleanup_status must be PASS")
        if not sample.get("replica_candidates"):
            errors.append(f"{sample_id}: replica_candidates required")
        run_id = str(sample.get("run_id", ""))
        state_ref = str(sample.get("state_ref", ""))
        if run_id in seen_run_ids:
            errors.append(f"{sample_id}: run_id reused: {run_id}")
        if state_ref in seen_state_refs:
            errors.append(f"{sample_id}: state_ref reused: {state_ref}")
        seen_run_ids.add(run_id)
        seen_state_refs.add(state_ref)

        fault = require_numeric(sample, "fault_injected_at_ms", errors)
        promoted = require_numeric(sample, "replica_promoted_at_ms", errors)
        coverage = require_numeric(sample, "slot_coverage_ok_at_ms", errors)
        first_read = require_numeric(sample, "first_successful_read_at_ms", errors)
        first_write = require_numeric(sample, "first_successful_write_at_ms", errors)
        promotion_latency = require_numeric(sample, "promotion_latency_ms", errors)
        recovery_latency = require_numeric(sample, "cluster_recovery_latency_ms", errors)
        if None not in {fault, promoted, coverage, first_read, first_write, promotion_latency, recovery_latency}:
            if not (fault <= promoted <= coverage <= max(first_read, first_write, coverage)):
                errors.append(f"{sample_id}: timestamps are not ordered from fault to recovery/data path")
            if abs((promoted - fault) - promotion_latency) > LATENCY_TIMESTAMP_TOLERANCE_MS:
                errors.append(f"{sample_id}: promotion_latency_ms does not match timestamps")
            if abs((coverage - fault) - recovery_latency) > LATENCY_TIMESTAMP_TOLERANCE_MS:
                errors.append(f"{sample_id}: cluster_recovery_latency_ms does not match timestamps")
            signature = (node_count, promoted, coverage, first_read, first_write)
            if signature in timing_signatures:
                errors.append(f"{sample_id}: duplicate timing signature suggests sample reuse")
            timing_signatures.add(signature)

    for rung, rung_samples in samples_by_rung.items():
        if len(rung_samples) < 3:
            errors.append(f"rung {rung} requires at least 3 samples, got {len(rung_samples)}")

    if set(curve.get("sample_refs", [])) != seen_sample_ids:
        errors.append("curve sample_refs must exactly match raw sample IDs")
    derived = curve.get("derived_series", [])
    if not isinstance(derived, list):
        errors.append("curve derived_series must be a list")
        return
    series_by_key = {(item.get("rung"), item.get("metric")): item for item in derived if isinstance(item, dict)}
    for rung, rung_samples in samples_by_rung.items():
        for metric in ["promotion_latency_ms", "cluster_recovery_latency_ms"]:
            values = [float(sample[metric]) for sample in rung_samples if isinstance(sample.get(metric), (int, float))]
            series = series_by_key.get((rung, metric))
            if not series:
                errors.append(f"curve missing derived series for rung={rung} metric={metric}")
                continue
            if int(series.get("sample_count", -1)) != len(values):
                errors.append(f"curve {rung}/{metric}: sample_count must match raw samples")
            expected = {
                "p50_ms": percentile(values, 0.50),
                "p95_ms": percentile(values, 0.95),
                "max_ms": round(max(values), 3),
            }
            for field, value in expected.items():
                if round(float(series.get(field, -1)), 3) != value:
                    errors.append(f"curve {rung}/{metric}: {field}={series.get(field)!r} does not match raw {value}")


def validate_p21_semantics(base: Path, samples: list[dict[str, Any]], curve: dict[str, Any], errors: list[str]) -> None:
    preflight = base / "resource_preflight_200.json"
    if not preflight.exists():
        errors.append("P21 requires resource_preflight_200.json")
    else:
        report = load_json(preflight)
        if report.get("status") != "PASS" or report.get("can_run") is not True or report.get("node_count") != 200:
            errors.append("P21 resource preflight must PASS with exact node_count=200")
        if report.get("dry_run") is not False:
            errors.append("P21 resource preflight must be non-dry-run")

    expected_ids = {f"rung-200-sample-{idx:02d}" for idx in [1, 2, 3]}
    sample_ids = {str(sample.get("sample_id")) for sample in samples if sample.get("sample_id")}
    if sample_ids != expected_ids:
        errors.append(f"P21 requires exactly sample IDs {sorted(expected_ids)}, got {sorted(sample_ids)}")
    if len(samples) != 3:
        errors.append(f"P21 requires exactly 3 sample rows, got {len(samples)}")

    seen_run_ids: set[str] = set()
    seen_state_refs: set[str] = set()
    timing_signatures: set[tuple[Any, ...]] = set()
    for sample in samples:
        sample_id = str(sample.get("sample_id", "MISSING"))
        if sample.get("phase_id") != "P21_FAILOVER_LATENCY_CURVE_200":
            errors.append(f"{sample_id}: phase_id must be P21_FAILOVER_LATENCY_CURVE_200")
        if sample.get("status") != "PASS":
            errors.append(f"{sample_id}: status must be PASS")
        if sample.get("real_valkey") is not True:
            errors.append(f"{sample_id}: real_valkey must be true")
        if sample.get("node_count") != 200 or sample.get("rung") != 200:
            errors.append(f"{sample_id}: node_count and rung must both be 200")
        try:
            sample_index = int(sample.get("sample_index", 0) or 0)
        except (TypeError, ValueError):
            sample_index = 0
        if sample.get("scenario_name") != f"scale_200_sample_{sample_index:02d}_fault_failover":
            errors.append(f"{sample_id}: scenario_name must match the sample index")
        for field in [
            "run_id",
            "state_ref",
            "evidence_ref",
            "cleanup_ref",
            "target_primary_node_id",
            "target_primary_az_id",
            "target_primary_host_id",
            "fault_injection_method",
            "promotion_detection_method",
            "slot_coverage_detection_method",
            "workload_impact_ref",
        ]:
            if not sample.get(field) or sample.get(field) == "MISSING":
                errors.append(f"{sample_id}: {field} required")
        if sample.get("cleanup_status") != "PASS":
            errors.append(f"{sample_id}: cleanup_status must be PASS")
        if not sample.get("replica_candidates"):
            errors.append(f"{sample_id}: replica_candidates required")
        run_id = str(sample.get("run_id", ""))
        state_ref = str(sample.get("state_ref", ""))
        if run_id in seen_run_ids:
            errors.append(f"{sample_id}: run_id reused: {run_id}")
        if state_ref in seen_state_refs:
            errors.append(f"{sample_id}: state_ref reused: {state_ref}")
        seen_run_ids.add(run_id)
        seen_state_refs.add(state_ref)

        fault = require_numeric(sample, "fault_injected_at_ms", errors)
        promoted = require_numeric(sample, "replica_promoted_at_ms", errors)
        coverage = require_numeric(sample, "slot_coverage_ok_at_ms", errors)
        first_read = require_numeric(sample, "first_successful_read_at_ms", errors)
        first_write = require_numeric(sample, "first_successful_write_at_ms", errors)
        promotion_latency = require_numeric(sample, "promotion_latency_ms", errors)
        recovery_latency = require_numeric(sample, "cluster_recovery_latency_ms", errors)
        if None not in {fault, promoted, coverage, first_read, first_write, promotion_latency, recovery_latency}:
            if not (fault <= promoted <= coverage <= max(first_read, first_write, coverage)):
                errors.append(f"{sample_id}: timestamps are not ordered from fault to recovery/data path")
            if abs((promoted - fault) - promotion_latency) > LATENCY_TIMESTAMP_TOLERANCE_MS:
                errors.append(f"{sample_id}: promotion_latency_ms does not match timestamps")
            if abs((coverage - fault) - recovery_latency) > LATENCY_TIMESTAMP_TOLERANCE_MS:
                errors.append(f"{sample_id}: cluster_recovery_latency_ms does not match timestamps")
            signature = (promoted, coverage, first_read, first_write)
            if signature in timing_signatures:
                errors.append(f"{sample_id}: duplicate timing signature suggests sample reuse")
            timing_signatures.add(signature)

    if set(curve.get("sample_refs", [])) != sample_ids:
        errors.append("P21 curve sample_refs must exactly match raw sample IDs")
    if curve.get("status") != "PASS":
        errors.append("P21 curve status must be PASS")
    if curve.get("rungs") != [200]:
        errors.append("P21 curve rungs must be [200]")
    derived = curve.get("derived_series", [])
    if not isinstance(derived, list):
        errors.append("P21 curve derived_series must be a list")
        return
    series_by_key = {(item.get("rung"), item.get("metric")): item for item in derived if isinstance(item, dict)}
    for metric in ["promotion_latency_ms", "cluster_recovery_latency_ms"]:
        values = [float(sample[metric]) for sample in samples if isinstance(sample.get(metric), (int, float))]
        series = series_by_key.get((200, metric))
        if not series:
            errors.append(f"P21 curve missing derived series for metric={metric}")
            continue
        if int(series.get("sample_count", -1)) != 3:
            errors.append(f"P21 curve {metric}: sample_count must be 3")
        if set(series.get("sample_refs", [])) != sample_ids:
            errors.append(f"P21 curve {metric}: sample_refs must match samples")
        expected = {
            "p50_ms": percentile(values, 0.50),
            "p95_ms": percentile(values, 0.95),
            "max_ms": round(max(values), 3),
        }
        for field, value in expected.items():
            if round(float(series.get(field, -1)), 3) != value:
                errors.append(f"P21 curve {metric}: {field}={series.get(field)!r} does not match raw {value}")

    validate_p21_combined_curve(base, curve, errors)


def validate_p21_combined_curve(base: Path, curve_200: dict[str, Any], errors: list[str]) -> None:
    combined_path = base / "failover_latency_curve_combined_30_50_100_200.json"
    if not combined_path.exists():
        errors.append("P21 requires failover_latency_curve_combined_30_50_100_200.json")
        return
    errors.extend(validate_artifact(combined_path, ROOT / "schemas/artifact/failover_latency_curve.schema.json"))
    combined = load_json(combined_path)
    if combined.get("status") != "PASS":
        errors.append("P21 combined curve status must be PASS")
    if combined.get("rungs") != [30, 50, 100, 200]:
        errors.append("P21 combined curve rungs must be [30, 50, 100, 200]")
    p20_path = ROOT / "artifacts" / "phases" / "P20_FAILOVER_LATENCY_CURVE_30_50_100" / "failover_latency_curve.json"
    if not p20_path.exists():
        errors.append("P21 combined curve requires P20 failover_latency_curve.json")
        return
    p20_curve = load_json(p20_path)
    if p20_curve.get("rungs") != [30, 50, 100] or p20_curve.get("status") not in {"PASS", None}:
        errors.append("P21 combined curve source P20 curve must contain rungs [30, 50, 100]")
    expected_series = list(p20_curve.get("derived_series", [])) + list(curve_200.get("derived_series", []))
    if combined.get("derived_series") != expected_series:
        errors.append("P21 combined curve derived_series must preserve P20 series and append P21 200 series")
    expected_refs = list(p20_curve.get("sample_refs", [])) + list(curve_200.get("sample_refs", []))
    if combined.get("sample_refs") != expected_refs:
        errors.append("P21 combined curve sample_refs must preserve P20 refs and append P21 refs")
    sources = combined.get("source_artifacts", [])
    if not isinstance(sources, list) or len(sources) != 2:
        errors.append("P21 combined curve must record exactly two source_artifacts")


def validate_strict_fault_semantics(
    phase: str,
    scale: int,
    min_samples: int,
    samples: list[dict[str, Any]],
    curve: dict[str, Any],
    errors: list[str],
) -> None:
    if STRICT_FAULT_STAGES[phase] != scale:
        errors.append(f"{phase} requires --scale {STRICT_FAULT_STAGES[phase]}")
    if len(samples) < min_samples:
        errors.append(f"{phase} requires at least {min_samples} failover samples, got {len(samples)}")
    sample_ids: set[str] = set()
    run_ids: set[str] = set()
    state_refs: set[str] = set()
    timing_signatures: set[tuple[Any, ...]] = set()
    for sample in samples:
        sample_id = str(sample.get("sample_id", "MISSING"))
        if sample_id in sample_ids:
            errors.append(f"duplicate sample_id {sample_id}")
        sample_ids.add(sample_id)
        if sample.get("phase_id") != phase or sample.get("stage_id") != phase:
            errors.append(f"{sample_id}: phase_id and stage_id must be {phase}")
        if sample.get("status") != "PASS":
            errors.append(f"{sample_id}: status must be PASS")
        if sample.get("real_valkey") is not True:
            errors.append(f"{sample_id}: real_valkey must be true")
        if sample.get("node_count") != scale or sample.get("scale") != scale or sample.get("rung") != scale:
            errors.append(f"{sample_id}: node_count, scale, and rung must be {scale}")
        for field in [
            "run_id",
            "state_ref",
            "evidence_ref",
            "cleanup_ref",
            "target_primary_logical_id",
            "target_primary_node_id",
            "target_primary_az_id",
            "target_primary_host_id",
            "fault_injection_method",
            "promotion_detection_method",
            "slot_coverage_detection_method",
            "workload_impact_ref",
            "split_brain_detector_ref",
        ]:
            if not sample.get(field) or sample.get(field) == "MISSING":
                errors.append(f"{sample_id}: {field} required")
        if sample.get("cleanup_status") != "PASS":
            errors.append(f"{sample_id}: cleanup_status must be PASS")
        if not sample.get("replica_candidates"):
            errors.append(f"{sample_id}: replica_candidates required")
        method = str(sample.get("fault_injection_method", ""))
        if "owned" not in method or "node_stop" not in method:
            errors.append(f"{sample_id}: fault_injection_method must record owned node_stop control")
        run_id = str(sample.get("run_id", ""))
        state_ref = str(sample.get("state_ref", ""))
        if run_id in run_ids:
            errors.append(f"{sample_id}: run_id reused: {run_id}")
        if state_ref in state_refs:
            errors.append(f"{sample_id}: state_ref reused: {state_ref}")
        run_ids.add(run_id)
        state_refs.add(state_ref)
        if sample.get("old_primary_rejoined_at_ms") == "MISSING" and not sample.get("old_primary_rejoined_missing_reason"):
            errors.append(f"{sample_id}: MISSING old_primary_rejoined_at_ms requires old_primary_rejoined_missing_reason")

        fault = require_numeric(sample, "fault_injected_at_ms", errors)
        promoted = require_numeric(sample, "replica_promoted_at_ms", errors)
        coverage = require_numeric(sample, "slot_coverage_ok_at_ms", errors)
        first_read = require_numeric(sample, "first_successful_read_at_ms", errors)
        first_write = require_numeric(sample, "first_successful_write_at_ms", errors)
        cleared = require_numeric(sample, "fault_cleared_at_ms", errors)
        promotion_latency = require_numeric(sample, "promotion_latency_ms", errors)
        recovery_latency = require_numeric(sample, "cluster_recovery_latency_ms", errors)
        if None not in {fault, promoted, coverage, first_read, first_write, cleared, promotion_latency, recovery_latency}:
            if not (fault <= promoted <= coverage and fault <= first_read and fault <= first_write and fault <= cleared):
                errors.append(f"{sample_id}: timestamps are not ordered from fault to recovery/data path")
            if abs((promoted - fault) - promotion_latency) > LATENCY_TIMESTAMP_TOLERANCE_MS:
                errors.append(f"{sample_id}: promotion_latency_ms does not match timestamps")
            if abs((coverage - fault) - recovery_latency) > LATENCY_TIMESTAMP_TOLERANCE_MS:
                errors.append(f"{sample_id}: cluster_recovery_latency_ms does not match timestamps")
            signature = (
                sample.get("target_primary_node_id"),
                promoted,
                coverage,
                first_read,
                first_write,
            )
            if signature in timing_signatures:
                errors.append(f"{sample_id}: duplicate timing signature suggests sample reuse")
            timing_signatures.add(signature)

    if curve.get("status") != "PASS":
        errors.append(f"{phase} failover_latency_curve status must be PASS")
    if curve.get("phase_id") != phase or curve.get("stage_id") != phase:
        errors.append(f"{phase} failover_latency_curve phase_id and stage_id must match phase")
    if curve.get("rungs") != [scale]:
        errors.append(f"{phase} failover_latency_curve rungs must be [{scale}]")
    if curve.get("scale") != scale or curve.get("node_count") != scale:
        errors.append(f"{phase} failover_latency_curve scale and node_count must be {scale}")
    if int(curve.get("sample_count", -1)) != len(samples):
        errors.append(f"{phase} failover_latency_curve sample_count must match failover_samples.jsonl")
    if set(curve.get("sample_refs", [])) != sample_ids:
        errors.append(f"{phase} failover_latency_curve sample_refs must exactly match raw sample IDs")
    if curve.get("sample_source") != "failover_samples.jsonl":
        errors.append(f"{phase} failover_latency_curve sample_source must be failover_samples.jsonl")
    derived = curve.get("derived_series", [])
    if not isinstance(derived, list):
        errors.append(f"{phase} failover_latency_curve derived_series must be a list")
        return
    series_by_key = {(item.get("rung"), item.get("metric")): item for item in derived if isinstance(item, dict)}
    for metric in ["promotion_latency_ms", "cluster_recovery_latency_ms"]:
        values = [float(sample[metric]) for sample in samples if isinstance(sample.get(metric), (int, float))]
        if not values:
            errors.append(f"{phase} failover_latency_curve has no numeric raw samples for metric={metric}")
            continue
        series = series_by_key.get((scale, metric))
        if not series:
            errors.append(f"{phase} failover_latency_curve missing derived series for metric={metric}")
            continue
        if int(series.get("sample_count", -1)) != len(values):
            errors.append(f"{phase} failover_latency_curve {metric}: sample_count must match raw samples")
        if set(series.get("sample_refs", [])) != sample_ids:
            errors.append(f"{phase} failover_latency_curve {metric}: sample_refs must match samples")
        expected = {
            "p50_ms": percentile(values, 0.50),
            "p95_ms": percentile(values, 0.95),
            "max_ms": round(max(values), 3),
        }
        for field, value in expected.items():
            if round(float(series.get(field, -1)), 3) != value:
                errors.append(f"{phase} failover_latency_curve {metric}: {field}={series.get(field)!r} does not match raw {value}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--scale", type=int)
    parser.add_argument("--min-samples", type=int, default=3)
    args = parser.parse_args()
    strict_scale = STRICT_FAULT_STAGES.get(args.phase)
    spec = EXPECTED.get(args.phase)
    if strict_scale is not None:
        if args.scale is None:
            print(f"FAIL: {args.phase} requires --scale {strict_scale}", file=sys.stderr)
            return 1
        base = ROOT / "artifacts" / "phases" / args.phase
        sample_path = base / "failover_samples.jsonl"
        curve_path = base / "failover_latency_curve.json"
        errors: list[str] = []
        errors.extend(validate_artifact(sample_path, ROOT / "schemas/artifact/failover_latency_sample.schema.json"))
        errors.extend(validate_artifact(curve_path, ROOT / "schemas/artifact/failover_latency_curve.schema.json"))
        if not errors:
            samples = load_jsonl(sample_path)
            curve = load_json(curve_path)
            validate_strict_fault_semantics(args.phase, args.scale, args.min_samples, samples, curve, errors)
        if errors:
            for error in errors:
                print(f"FAIL: {error}", file=sys.stderr)
            return 1
        print(f"PASS failover latency curve phase={args.phase} scale={args.scale}")
        return 0
    if not spec:
        print(f"PASS failover latency curve not required for phase={args.phase}")
        return 0

    base = ROOT / "artifacts" / "phases" / args.phase
    sample_path = base / spec["sample_file"]
    curve_path = base / spec["curve_file"]
    errors: list[str] = []
    errors.extend(validate_artifact(sample_path, ROOT / "schemas/artifact/failover_latency_sample.schema.json"))
    errors.extend(validate_artifact(curve_path, ROOT / "schemas/artifact/failover_latency_curve.schema.json"))
    if args.phase == "P21_FAILOVER_LATENCY_CURVE_200":
        preflight = base / "resource_preflight_200.json"
        if not preflight.exists():
            errors.append("P21 requires resource_preflight_200.json")
        elif load_json(preflight).get("status") != "PASS":
            errors.append("P21 resource preflight must PASS or the stage is blocked")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    samples = load_jsonl(sample_path)
    counts = {rung: 0 for rung in spec["rungs"]}
    for sample in samples:
        node_count = int(sample.get("node_count", -1))
        if node_count not in counts:
            errors.append(f"unexpected failover sample node_count={node_count}")
            continue
        counts[node_count] += 1
        for field in ["fault_injected_at_ms", "replica_promoted_at_ms", "slot_coverage_ok_at_ms", "first_successful_read_at_ms", "first_successful_write_at_ms"]:
            if sample.get(field) == "MISSING":
                errors.append(f"{sample.get('sample_id')}: required timestamp {field} is MISSING")
        if not sample.get("workload_impact_ref"):
            errors.append(f"{sample.get('sample_id')}: workload_impact_ref required")
    for rung, count in counts.items():
        if count < 3:
            errors.append(f"rung {rung} requires at least 3 samples, got {count}")
    curve = load_json(curve_path)
    if set(curve.get("rungs", [])) != spec["rungs"]:
        errors.append(f"curve rungs must be {sorted(spec['rungs'])}")
    if args.phase == "P21_FAILOVER_LATENCY_CURVE_200" and any(sample.get("node_count") != 200 for sample in samples):
        errors.append("P21 samples must not downshift below 200 nodes")
    if args.phase == "P20_FAILOVER_LATENCY_CURVE_30_50_100":
        validate_p20_semantics(base, samples, curve, errors)
    if args.phase == "P21_FAILOVER_LATENCY_CURVE_200":
        validate_p21_semantics(base, samples, curve, errors)

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS failover latency curve phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
