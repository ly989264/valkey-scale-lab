#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from codex_gate import validate_artifact  # noqa: E402
from schema_validator import load_json  # noqa: E402

WINDOWS = {"baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"}
METRICS = {
    "requested_qps",
    "achieved_qps",
    "ok_ops",
    "error_ops",
    "error_rate",
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_p99_ms",
    "timeout_count",
    "moved_redirection_count",
    "ask_redirection_count",
}
P25_SOURCE_STAGES = {
    "P17_MANAGEMENT_REMOVE_NODE",
    "P18_MANAGEMENT_RESHARD_REBALANCE",
    "P19_MANAGEMENT_ROLLING_RESTART",
    "P20_FAILOVER_LATENCY_CURVE_30_50_100",
    "P21_FAILOVER_LATENCY_CURVE_200",
    "P22_FAULT_REPLICA_HOST_AZ_STOP",
    "P23_FAULT_NETWORK_DELAY_LOSS_FLAP",
    "P24_PARTITION_SPLIT_BRAIN_MATRIX",
}
P25_DERIVED_FIELDS = {
    "fault_or_operation_qps_ratio",
    "post_recovery_qps_ratio",
    "latency_p50_delta_ms",
    "latency_p95_delta_ms",
    "latency_p99_delta_ms",
    "error_rate_delta",
    "recovery_duration_ms",
}
P25_CSV_TABLES = {
    "operation": "workload_impact_by_operation.csv",
    "fault": "workload_impact_by_fault.csv",
    "latency": "latency_delta_table.csv",
    "error": "error_delta_table.csv",
    "recovery": "recovery_duration_table.csv",
}


def candidate_path(base: Path) -> Path | None:
    for name in ["workload_impact_report.json", "management_workload_impact.json", "workload_impact_cross_stage.json"]:
        path = base / name
        if path.exists():
            return path
    return None


def metric_missing_reason(metrics: dict[str, Any], field: str) -> bool:
    reasons = metrics.get("missing_reasons", {})
    return isinstance(reasons, dict) and bool(reasons.get(field))


def csv_data_row_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as f:
        return sum(1 for _row in csv.DictReader(f))


def assert_p25_cross_stage(base: Path, report: dict[str, Any], errors: list[str]) -> None:
    statuses = report.get("source_stage_statuses", [])
    status_ids = {item.get("stage_id") for item in statuses if isinstance(item, dict)}
    missing_statuses = sorted(P25_SOURCE_STAGES - status_ids)
    if missing_statuses:
        errors.append(f"P25 source_stage_statuses missing required stages: {missing_statuses}")
    for item in statuses:
        if not isinstance(item, dict):
            errors.append("P25 source_stage_statuses entries must be objects")
            continue
        if item.get("status") in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"} and not item.get("reason"):
            errors.append(f"P25 source stage {item.get('stage_id')}: missing/skipped status requires reason")
    rules = report.get("derivation_rules", {})
    if rules.get("log_parsing") is not False:
        errors.append("P25 derivation_rules.log_parsing must be false")
    if rules.get("source_scenarios_rerun") is not False:
        errors.append("P25 derivation_rules.source_scenarios_rerun must be false")

    rows = report.get("rows", [])
    if not rows:
        errors.append("P25 rows must not be empty")
        return
    row_counts = report.get("row_counts", {})
    expected_counts = {
        "total": len(rows),
        "management": sum(1 for row in rows if row.get("category") == "management"),
        "failover": sum(1 for row in rows if row.get("category") == "failover"),
        "fault": sum(1 for row in rows if row.get("category") == "fault"),
        "missing_rows": sum(1 for row in rows if row.get("status") != "PASS"),
        "p24_rows": sum(1 for row in rows if row.get("source_stage_id") == "P24_PARTITION_SPLIT_BRAIN_MATRIX"),
    }
    for key, value in expected_counts.items():
        if row_counts.get(key) != value:
            errors.append(f"P25 row_counts.{key} expected {value}, got {row_counts.get(key)!r}")

    for row in rows:
        label = str(row.get("row_id", "MISSING"))
        if row.get("source_stage_id") not in P25_SOURCE_STAGES:
            errors.append(f"{label}: invalid or missing source_stage_id {row.get('source_stage_id')!r}")
        if row.get("status") in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON", "FAIL"} and not row.get("reason"):
            errors.append(f"{label}: non-PASS status requires reason")
        refs = row.get("source_refs", [])
        if row.get("status") == "PASS" and len(refs) < 2:
            errors.append(f"{label}: PASS rows require metadata and workload source refs")
        for ref in refs:
            if not isinstance(ref, dict) or not ref.get("artifact") or not ref.get("sha256"):
                errors.append(f"{label}: source ref must include artifact and sha256")
        if row.get("status") != "PASS":
            continue
        windows = row.get("windows", {})
        window_refs = row.get("window_refs", {})
        for window_name in ["baseline", "event", "recovery", "post_recovery"]:
            if window_name not in windows:
                errors.append(f"{label}: missing required window {window_name}")
                continue
            window = windows[window_name]
            if window.get("status") == "MISSING" and not window.get("reason"):
                errors.append(f"{label}: MISSING window {window_name} requires reason")
            if window_name not in window_refs:
                errors.append(f"{label}: missing window_refs.{window_name}")
        derived = row.get("derived", {})
        missing_reasons = derived.get("missing_reasons", {})
        for field in P25_DERIVED_FIELDS:
            if field not in derived:
                errors.append(f"{label}: missing derived field {field}")
            elif derived[field] == "MISSING" and not missing_reasons and row.get("status") == "PASS":
                errors.append(f"{label}: MISSING derived {field} requires a missing reason")
        if row.get("source_stage_id") == "P24_PARTITION_SPLIT_BRAIN_MATRIX":
            taxonomy = row.get("error_taxonomy", {})
            for window_name, counts in taxonomy.items():
                if not isinstance(counts, dict):
                    errors.append(f"{label}: P24 taxonomy {window_name} must be object")
                    continue
                classified = sum(int(counts.get(field, 0) or 0) for field in [
                    "timeout_count",
                    "connection_error_count",
                    "cluster_down_error_count",
                    "readonly_error_count",
                    "tryagain_error_count",
                    "unknown_error_count",
                ])
                if classified != int(counts.get("error_ops", 0) or 0):
                    errors.append(f"{label}: P24 taxonomy {window_name} classified errors must equal error_ops")
                source_metrics = windows.get(window_name, {}).get("metrics", {})
                if int(source_metrics.get("cluster_down_error_count", 0) or 0) != int(counts.get("cluster_down_error_count", 0) or 0):
                    errors.append(f"{label}: P24 taxonomy {window_name} must preserve cluster_down_error_count")

    exports = report.get("csv_exports", [])
    index_path = base / "csv_export_index.json"
    if not index_path.exists():
        errors.append("P25 csv_export_index.json missing")
        index = {}
    else:
        index = load_json(index_path)
    index_exports = {item.get("table_name"): item for item in index.get("exports", []) if isinstance(item, dict)}
    export_by_table = {item.get("table_name"): item for item in exports if isinstance(item, dict)}
    expected_json_counts = {
        "operation": expected_counts["management"],
        "fault": expected_counts["failover"] + expected_counts["fault"],
        "latency": expected_counts["total"],
        "error": expected_counts["total"],
        "recovery": expected_counts["total"],
    }
    for table_name, filename in P25_CSV_TABLES.items():
        export = export_by_table.get(table_name)
        index_export = index_exports.get(table_name)
        csv_path = base / filename
        if export is None:
            errors.append(f"P25 csv_exports missing table {table_name}")
            continue
        if index_export is None:
            errors.append(f"P25 csv_export_index missing table {table_name}")
        if not csv_path.exists():
            errors.append(f"P25 CSV missing: {filename}")
            continue
        actual_rows = csv_data_row_count(csv_path)
        expected = expected_json_counts[table_name]
        if actual_rows != expected:
            errors.append(f"P25 CSV {filename} row count expected {expected}, got {actual_rows}")
        if export.get("row_count") != actual_rows or export.get("json_source_count") != expected:
            errors.append(f"P25 csv_exports.{table_name} row/json counts do not match JSON rows")
        if index_export and (index_export.get("row_count") != actual_rows or index_export.get("json_source_count") != expected):
            errors.append(f"P25 csv_export_index.{table_name} row/json counts do not match JSON rows")

    missing_path = base / "missing_data_summary.json"
    if not missing_path.exists():
        errors.append("P25 missing_data_summary.json missing")
    else:
        missing = load_json(missing_path)
        if missing.get("item_count") != len(missing.get("items", [])):
            errors.append("P25 missing_data_summary.item_count must match items length")
        for idx, item in enumerate(missing.get("items", [])):
            if not item.get("source_stage_id") or not item.get("artifact") or not item.get("field") or not item.get("reason"):
                errors.append(f"P25 missing_data_summary.items[{idx}] requires source_stage_id, artifact, field, and reason")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    base = ROOT / "artifacts" / "phases" / args.phase
    path = candidate_path(base)
    if path is None:
        print(f"FAIL: no workload impact artifact found for {args.phase}", file=sys.stderr)
        return 1

    schema = ROOT / "schemas/artifact/workload_impact_cross_stage.schema.json" if path.name == "workload_impact_cross_stage.json" else ROOT / "schemas/artifact/workload_impact_report.schema.json"
    errors = validate_artifact(path, schema)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    report = load_json(path)
    if args.phase == "P25_FAULT_WORKLOAD_IMPACT_ANALYSIS":
        assert_p25_cross_stage(base, report, errors)
        if errors:
            for error in errors:
                print(f"FAIL: {error}", file=sys.stderr)
            return 1
        print(f"PASS workload impact phase={args.phase}")
        return 0
    rows = report.get("windows", report.get("rows", []))
    observed = {row.get("window_name") for row in rows}
    missing_windows = sorted(WINDOWS - observed)
    if missing_windows:
        errors.append(f"missing workload windows: {missing_windows}")
    for row in rows:
        name = row.get("window_name", "unknown")
        metrics = row.get("metrics", row)
        for field in METRICS:
            if field not in metrics:
                errors.append(f"{name}: missing metric {field}")
            elif metrics.get(field) == "MISSING" and not metric_missing_reason(metrics, field):
                errors.append(f"{name}: MISSING {field} requires missing_reasons.{field}")
    if args.phase == "P20_FAILOVER_LATENCY_CURVE_30_50_100":
        sample_ids = {row.get("sample_id") for row in rows if row.get("sample_id")}
        if len(sample_ids) != 9:
            errors.append(f"P20 workload impact must cover 9 sample IDs, got {len(sample_ids)}")
        for row in rows:
            if row.get("rung") not in {30, 50, 100}:
                errors.append(f"{row.get('window_name', 'unknown')}: invalid P20 rung {row.get('rung')!r}")
            if not row.get("sample_id"):
                errors.append(f"{row.get('window_name', 'unknown')}: P20 sample_id required")
        comparisons = report.get("comparisons", [])
        comparison_ids = {item.get("sample_id") for item in comparisons if isinstance(item, dict)}
        missing_comparisons = sorted(sample_ids - comparison_ids)
        if missing_comparisons:
            errors.append(f"P20 comparisons missing sample IDs: {missing_comparisons}")
    if args.phase == "P21_FAILOVER_LATENCY_CURVE_200":
        expected_ids = {f"rung-200-sample-{idx:02d}" for idx in [1, 2, 3]}
        sample_ids = {row.get("sample_id") for row in rows if row.get("sample_id")}
        if sample_ids != expected_ids:
            errors.append(f"P21 workload impact must cover exactly {sorted(expected_ids)}, got {sorted(sample_ids)}")
        windows_by_sample: dict[Any, set[Any]] = {}
        for row in rows:
            sid = row.get("sample_id")
            if row.get("rung") != 200 or row.get("node_count") != 200:
                errors.append(f"{row.get('window_name', 'unknown')}: invalid P21 rung/node_count {row.get('rung')!r}/{row.get('node_count')!r}")
            if sid not in expected_ids:
                errors.append(f"{row.get('window_name', 'unknown')}: unexpected P21 sample_id {sid!r}")
            windows_by_sample.setdefault(sid, set()).add(row.get("window_name"))
        for sid in expected_ids:
            missing = sorted(WINDOWS - windows_by_sample.get(sid, set()))
            if missing:
                errors.append(f"P21 sample {sid} missing workload windows: {missing}")
        comparisons = report.get("comparisons", [])
        comparison_ids = {item.get("sample_id") for item in comparisons if isinstance(item, dict)}
        missing_comparisons = sorted(expected_ids - comparison_ids)
        if missing_comparisons:
            errors.append(f"P21 comparisons missing sample IDs: {missing_comparisons}")
        for item in comparisons:
            if isinstance(item, dict) and (item.get("rung") != 200 or item.get("node_count") != 200):
                errors.append(f"P21 comparison {item.get('sample_id')}: rung/node_count must be 200")
    if args.phase == "P22_FAULT_REPLICA_HOST_AZ_STOP":
        required_faults = {"replica_stop", "node_host_stop", "az_stop"}
        sample_ids = {row.get("sample_id") for row in rows if row.get("sample_id")}
        by_sample: dict[Any, list[dict[str, Any]]] = {}
        for row in rows:
            by_sample.setdefault(row.get("sample_id"), []).append(row)
            if row.get("fault_type") not in required_faults:
                errors.append(f"{row.get('sample_id')}: unexpected P22 fault_type {row.get('fault_type')!r}")
            if row.get("node_count") == 200:
                errors.append(f"{row.get('sample_id')}: P22 workload must not use 200-node rows")
            if not row.get("fault_id"):
                errors.append(f"{row.get('sample_id')}: P22 workload row requires fault_id")
        required_sample_pairs = {
            (fault_type, node_count)
            for fault_type in required_faults
            for node_count in [6, 10]
        }
        observed_pairs = {
            (items[0].get("fault_type"), items[0].get("node_count"))
            for items in by_sample.values()
            if items
        }
        missing_pairs = sorted(required_sample_pairs - observed_pairs)
        if missing_pairs:
            errors.append(f"P22 workload missing required real sample pairs: {missing_pairs}")
        for sid, items in by_sample.items():
            names = {item.get("window_name") for item in items}
            missing = sorted(WINDOWS - names)
            if missing:
                errors.append(f"P22 sample {sid} missing workload windows: {missing}")
        comparisons = report.get("comparisons", [])
        comparison_ids = {item.get("sample_id") for item in comparisons if isinstance(item, dict)}
        missing_comparisons = sorted(str(item) for item in sample_ids - comparison_ids)
        if missing_comparisons:
            errors.append(f"P22 comparisons missing sample IDs: {missing_comparisons}")
        for item in comparisons:
            if not isinstance(item, dict):
                continue
            for field in [
                "fault_window_qps_ratio",
                "fault_window_p99_delta_ms",
                "fault_window_error_rate_delta",
                "recovery_window_duration_ms",
                "post_recovery_qps_ratio",
            ]:
                if field not in item:
                    errors.append(f"P22 comparison {item.get('sample_id')}: missing {field}")
    if args.phase == "P23_FAULT_NETWORK_DELAY_LOSS_FLAP":
        required_faults = {"network_delay", "network_loss", "network_flap"}
        sample_ids = {row.get("sample_id") for row in rows if row.get("sample_id")}
        by_sample: dict[Any, list[dict[str, Any]]] = {}
        for row in rows:
            by_sample.setdefault(row.get("sample_id"), []).append(row)
            if row.get("fault_type") not in required_faults:
                errors.append(f"{row.get('sample_id')}: unexpected P23 fault_type {row.get('fault_type')!r}")
            if row.get("node_count") == 200:
                errors.append(f"{row.get('sample_id')}: P23 workload must not use 200-node rows")
            if not row.get("fault_id"):
                errors.append(f"{row.get('sample_id')}: P23 workload row requires fault_id")
        required_sample_pairs = {
            (fault_type, node_count)
            for fault_type in required_faults
            for node_count in [6, 10]
        }
        observed_pairs = {
            (items[0].get("fault_type"), items[0].get("node_count"))
            for items in by_sample.values()
            if items
        }
        missing_pairs = sorted(required_sample_pairs - observed_pairs)
        if missing_pairs:
            errors.append(f"P23 workload missing required real sample pairs: {missing_pairs}")
        for sid, items in by_sample.items():
            names = {item.get("window_name") for item in items}
            missing = sorted(WINDOWS - names)
            if missing:
                errors.append(f"P23 sample {sid} missing workload windows: {missing}")
            event = next((item for item in items if item.get("window_name") == "event"), {})
            metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
            if metrics.get("sample_count", 0) == 0:
                errors.append(f"P23 sample {sid} event window must contain attempted workload samples")
        comparisons = report.get("comparisons", [])
        comparison_ids = {item.get("sample_id") for item in comparisons if isinstance(item, dict)}
        missing_comparisons = sorted(str(item) for item in sample_ids - comparison_ids)
        if missing_comparisons:
            errors.append(f"P23 comparisons missing sample IDs: {missing_comparisons}")
        for item in comparisons:
            if not isinstance(item, dict):
                continue
            for field in [
                "fault_window_qps_ratio",
                "fault_window_p99_delta_ms",
                "fault_window_error_rate_delta",
                "recovery_window_duration_ms",
                "post_recovery_qps_ratio",
            ]:
                if field not in item:
                    errors.append(f"P23 comparison {item.get('sample_id')}: missing {field}")
    if args.phase == "P24_PARTITION_SPLIT_BRAIN_MATRIX":
        required_faults = {"network_partition_minority", "network_partition_majority", "split_brain_window_detection"}
        sample_ids = {row.get("sample_id") for row in rows if row.get("sample_id")}
        by_sample: dict[Any, list[dict[str, Any]]] = {}
        for row in rows:
            by_sample.setdefault(row.get("sample_id"), []).append(row)
            if row.get("fault_type") not in required_faults:
                errors.append(f"{row.get('sample_id')}: unexpected P24 fault_type {row.get('fault_type')!r}")
            if row.get("node_count") in {200, 1000}:
                errors.append(f"{row.get('sample_id')}: P24 workload must not use 200/1000-node rows")
            if not row.get("fault_id"):
                errors.append(f"{row.get('sample_id')}: P24 workload row requires fault_id")
            if not row.get("side_label"):
                errors.append(f"{row.get('sample_id')}: P24 workload row requires side_label")
        required_sample_pairs = {
            (fault_type, node_count)
            for fault_type in required_faults
            for node_count in [6, 10]
        }
        observed_pairs = {
            (items[0].get("fault_type"), items[0].get("node_count"))
            for items in by_sample.values()
            if items
        }
        missing_pairs = sorted(required_sample_pairs - observed_pairs)
        if missing_pairs:
            errors.append(f"P24 workload missing required real sample pairs: {missing_pairs}")
        for sid, items in by_sample.items():
            names = {item.get("window_name") for item in items}
            missing = sorted(WINDOWS - names)
            if missing:
                errors.append(f"P24 sample {sid} missing workload windows: {missing}")
            event = next((item for item in items if item.get("window_name") == "event"), {})
            metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
            if int(metrics.get("sample_count", 0) or 0) == 0:
                errors.append(f"P24 sample {sid} event window must contain attempted workload samples")
            for item in items:
                item_metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
                classified_errors = sum(int(item_metrics.get(field, 0) or 0) for field in [
                    "timeout_count",
                    "connection_error_count",
                    "cluster_down_error_count",
                    "readonly_error_count",
                    "tryagain_error_count",
                    "unknown_error_count",
                ])
                if classified_errors != int(item_metrics.get("error_ops", 0) or 0):
                    errors.append(f"P24 sample {sid} {item.get('window_name')}: error taxonomy counts must equal error_ops")
                has_clusterdown_sample = any(
                    isinstance(sample, dict) and "clusterdown" in str(sample.get("error", "")).lower()
                    for sample in item.get("samples", [])
                )
                if has_clusterdown_sample and int(item_metrics.get("cluster_down_error_count", 0) or 0) <= 0:
                    errors.append(f"P24 sample {sid} {item.get('window_name')}: CLUSTERDOWN samples require cluster_down_error_count")
                if item.get("window_name") == "all_run" and int(item_metrics.get("ok_ops", 0) or 0) > 0:
                    for latency_field in ["latency_p50_ms", "latency_p90_ms", "latency_p95_ms", "latency_p99_ms"]:
                        if item_metrics.get(latency_field) == "MISSING":
                            errors.append(f"P24 sample {sid} all_run: {latency_field} must be derived when ok_ops > 0")
                    if any("No successful workload operations" in str(reason) for reason in item_metrics.get("missing_reasons", {}).values()):
                        errors.append(f"P24 sample {sid} all_run: missing reasons must not contradict ok_ops > 0")
            side_labels = {item.get("side_label") for item in items}
            invalid_side_labels = side_labels - {"minority", "majority", "aggregate"}
            if invalid_side_labels:
                errors.append(f"P24 sample {sid} has invalid side labels {sorted(str(item) for item in invalid_side_labels)}")
        comparisons = report.get("comparisons", [])
        comparison_ids = {item.get("sample_id") for item in comparisons if isinstance(item, dict)}
        missing_comparisons = sorted(str(item) for item in sample_ids - comparison_ids)
        if missing_comparisons:
            errors.append(f"P24 comparisons missing sample IDs: {missing_comparisons}")
        for item in comparisons:
            if not isinstance(item, dict):
                continue
            for field in [
                "fault_window_qps_ratio",
                "fault_window_p99_delta_ms",
                "fault_window_error_rate_delta",
                "recovery_window_duration_ms",
                "post_recovery_qps_ratio",
            ]:
                if field not in item:
                    errors.append(f"P24 comparison {item.get('sample_id')}: missing {field}")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS workload impact phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
