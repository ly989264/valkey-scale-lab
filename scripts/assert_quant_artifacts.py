#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from codex_gate import phase_by_id, validate_artifact  # noqa: E402
from schema_validator import load_json  # noqa: E402

CANONICAL_WINDOWS = ["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]
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


def require_reason(row: dict[str, Any], label: str, errors: list[str]) -> None:
    status = row.get("status")
    if status in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"} and not row.get("reason"):
        errors.append(f"{label}: {status} requires reason")


def read_jsonl(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        errors.append(f"jsonl missing: {path}")
        return rows
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        errors.append(f"jsonl empty: {path}")
        return rows
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{lineno}: invalid JSON: {exc}")
            continue
        if not isinstance(obj, dict):
            errors.append(f"{path}:{lineno}: JSONL row must be an object")
            continue
        rows.append(obj)
    return rows


def assert_workload_missing_reasons(windows: list[dict[str, Any]], errors: list[str]) -> None:
    for window in windows:
        name = window.get("window_name", "MISSING")
        metrics = window.get("metrics", {})
        if not isinstance(metrics, dict):
            errors.append(f"workload window {name}: metrics must be object")
            continue
        missing_reasons = metrics.get("missing_reasons", {})
        if not isinstance(missing_reasons, dict):
            errors.append(f"workload window {name}: missing_reasons must be object")
            missing_reasons = {}
        for key, value in metrics.items():
            if key == "missing_reasons":
                continue
            if value == "MISSING" and not missing_reasons.get(key):
                errors.append(f"workload window {name}: MISSING metric {key} requires missing_reasons[{key}]")


def assert_p16_semantics(base: Path, errors: list[str]) -> None:
    events = read_jsonl(base / "events.jsonl", errors)
    metrics = read_jsonl(base / "metrics_timeseries.jsonl", errors)
    event_ids = {str(row.get("event_id")) for row in events if row.get("event_id")}
    if not events:
        errors.append("P16 events.jsonl must contain at least one event")
    if not metrics:
        errors.append("P16 metrics_timeseries.jsonl must contain at least one metric")

    for idx, event in enumerate(events, start=1):
        if event.get("phase_id") != "P16_QUANT_TELEMETRY_UNIFICATION":
            errors.append(f"events.jsonl:{idx}: phase_id must be P16_QUANT_TELEMETRY_UNIFICATION")
        if event.get("severity") not in {"DEBUG", "INFO", "WARN", "ERROR"}:
            errors.append(f"events.jsonl:{idx}: invalid severity {event.get('severity')!r}")

    for idx, metric in enumerate(metrics, start=1):
        if metric.get("phase_id") != "P16_QUANT_TELEMETRY_UNIFICATION":
            errors.append(f"metrics_timeseries.jsonl:{idx}: phase_id must be P16_QUANT_TELEMETRY_UNIFICATION")
        if metric.get("metric_value") == "MISSING" and not metric.get("missing_reason"):
            errors.append(f"metrics_timeseries.jsonl:{idx}: MISSING metric_value requires missing_reason")
        if metric.get("metric_value") != "MISSING" and metric.get("missing_reason"):
            errors.append(f"metrics_timeseries.jsonl:{idx}: non-MISSING metric_value must not carry missing_reason")

    evidence_path = base / "valkey_e2e_evidence.json"
    live_node_ids: set[str] = set()
    if evidence_path.exists():
        evidence = load_json(evidence_path)
        for probe in evidence.get("probes", []):
            if isinstance(probe, dict) and probe.get("status") == "PASS" and probe.get("logical_id"):
                live_node_ids.add(str(probe["logical_id"]))
        if evidence.get("status") != "PASS":
            errors.append("P16 valkey_e2e_evidence status must be PASS")
        if int(evidence.get("nodes_observed", 0) or 0) < 6:
            errors.append("P16 valkey_e2e_evidence must observe at least 6 nodes")
    else:
        errors.append("P16 valkey_e2e_evidence.json missing")

    info_sample_ids = {
        str(metric.get("source_id"))
        for metric in metrics
        if metric.get("source_type") == "valkey_info"
        and metric.get("metric_name") == "valkey_info_sample"
        and metric.get("metric_value") is True
    }
    if live_node_ids and not live_node_ids.issubset(info_sample_ids):
        missing = sorted(live_node_ids - info_sample_ids)
        errors.append(f"P16 requires at least one valkey_info metric per live node; missing {missing}")
    if len(info_sample_ids) < 6:
        errors.append(f"P16 requires valkey_info samples for 6 nodes, got {len(info_sample_ids)}")

    for required_source in ["cluster_info", "cluster_nodes", "workload"]:
        if not any(metric.get("source_type") == required_source for metric in metrics):
            errors.append(f"P16 metrics_timeseries.jsonl must include source_type={required_source}")

    windows_path = base / "workload_windows.json"
    if windows_path.exists():
        workload = load_json(windows_path)
        windows = workload.get("windows", [])
        names = [window.get("window_name") for window in windows]
        if names != CANONICAL_WINDOWS:
            errors.append(f"P16 workload windows must be exactly {CANONICAL_WINDOWS}, got {names}")
        nonzero = [
            window.get("window_name")
            for window in windows
            if isinstance(window.get("metrics"), dict) and int(window["metrics"].get("sample_count", 0) or 0) > 0
        ]
        if not nonzero:
            errors.append("P16 requires at least one workload window with non-zero sample_count")
        for window in windows:
            name = window.get("window_name", "MISSING")
            start_event_id = str(window.get("start_event_id", ""))
            end_event_id = str(window.get("end_event_id", ""))
            if start_event_id not in event_ids:
                errors.append(f"workload window {name}: start_event_id {start_event_id!r} not present in events.jsonl")
            if end_event_id not in event_ids:
                errors.append(f"workload window {name}: end_event_id {end_event_id!r} not present in events.jsonl")
            metrics_obj = window.get("metrics", {})
            for field in [
                "requested_qps",
                "achieved_qps",
                "ok_ops",
                "error_ops",
                "error_rate",
                "latency_p50_ms",
                "latency_p90_ms",
                "latency_p95_ms",
                "latency_p99_ms",
                "latency_p999_ms",
                "timeout_count",
                "connection_error_count",
                "moved_redirection_count",
                "ask_redirection_count",
                "cluster_down_error_count",
                "readonly_error_count",
                "tryagain_error_count",
                "unknown_error_count",
                "sample_count",
            ]:
                if not isinstance(metrics_obj, dict) or field not in metrics_obj:
                    errors.append(f"workload window {name}: missing metric {field}")
        assert_workload_missing_reasons(windows, errors)
    else:
        errors.append("P16 workload_windows.json missing")

    quant_path = base / "quant_summary.json"
    if quant_path.exists():
        quant = load_json(quant_path)
        counts = quant.get("counts", {})
        if counts.get("event_count") != len(events):
            errors.append("P16 quant_summary counts.event_count must match events.jsonl line count")
        if counts.get("metric_count") != len(metrics):
            errors.append("P16 quant_summary counts.metric_count must match metrics_timeseries.jsonl line count")
        claims = quant.get("runtime_claims", {})
        if claims.get("real_valkey_claimed") is not True:
            errors.append("P16 quant_summary must claim real Valkey telemetry")
        if claims.get("management_runtime_claimed") is not False or claims.get("fault_runtime_claimed") is not False:
            errors.append("P16 quant_summary must not claim management or fault runtime behavior")


def assert_p20_semantics(base: Path, errors: list[str]) -> None:
    events = read_jsonl(base / "events.jsonl", errors)
    metrics = read_jsonl(base / "metrics_timeseries.jsonl", errors)
    samples = read_jsonl(base / "failover_latency_samples.jsonl", errors)
    sample_ids = {str(sample.get("sample_id")) for sample in samples if sample.get("sample_id")}
    if len(sample_ids) != 9:
        errors.append(f"P20 requires exactly 9 failover sample IDs, got {len(sample_ids)}")
    event_sample_ids = {str(event.get("sample_id")) for event in events if event.get("sample_id")}
    metric_sample_ids = {str(metric.get("sample_id")) for metric in metrics if metric.get("sample_id")}
    missing_events = sorted(sample_ids - event_sample_ids)
    missing_metrics = sorted(sample_ids - metric_sample_ids)
    if missing_events:
        errors.append(f"P20 events.jsonl missing sample IDs: {missing_events}")
    if missing_metrics:
        errors.append(f"P20 metrics_timeseries.jsonl missing sample IDs: {missing_metrics}")
    for idx, event in enumerate(events, start=1):
        if event.get("phase_id") != "P20_FAILOVER_LATENCY_CURVE_30_50_100":
            errors.append(f"P20 events.jsonl:{idx}: wrong phase_id {event.get('phase_id')!r}")
    for idx, metric in enumerate(metrics, start=1):
        if metric.get("phase_id") != "P20_FAILOVER_LATENCY_CURVE_30_50_100":
            errors.append(f"P20 metrics_timeseries.jsonl:{idx}: wrong phase_id {metric.get('phase_id')!r}")
        if metric.get("metric_value") == "MISSING" and not metric.get("missing_reason"):
            errors.append(f"P20 metrics_timeseries.jsonl:{idx}: MISSING metric_value requires missing_reason")
    quant_path = base / "quant_summary.json"
    if quant_path.exists():
        quant = load_json(quant_path)
        counts = quant.get("counts", {})
        if counts.get("event_count") != len(events):
            errors.append("P20 quant_summary counts.event_count must match events.jsonl line count")
        if counts.get("metric_count") != len(metrics):
            errors.append("P20 quant_summary counts.metric_count must match metrics_timeseries.jsonl line count")
        if counts.get("sample_count") != len(samples):
            errors.append("P20 quant_summary counts.sample_count must match failover_latency_samples.jsonl line count")
        claims = quant.get("runtime_claims", {})
        if claims.get("real_valkey_claimed") is not True or claims.get("fault_runtime_claimed") is not True:
            errors.append("P20 quant_summary must claim real Valkey fault runtime")


def assert_p21_semantics(base: Path, errors: list[str]) -> None:
    events = read_jsonl(base / "events.jsonl", errors)
    metrics = read_jsonl(base / "metrics_timeseries.jsonl", errors)
    samples = read_jsonl(base / "failover_latency_samples_200.jsonl", errors)
    expected_ids = {f"rung-200-sample-{idx:02d}" for idx in [1, 2, 3]}
    sample_ids = {str(sample.get("sample_id")) for sample in samples if sample.get("sample_id")}
    if sample_ids != expected_ids or len(samples) != 3:
        errors.append(f"P21 requires exactly 3 200-node failover sample IDs, got {sorted(sample_ids)} rows={len(samples)}")
    for sample in samples:
        sid = sample.get("sample_id", "MISSING")
        if sample.get("phase_id") != "P21_FAILOVER_LATENCY_CURVE_200":
            errors.append(f"{sid}: wrong phase_id {sample.get('phase_id')!r}")
        if sample.get("node_count") != 200 or sample.get("rung") != 200:
            errors.append(f"{sid}: P21 sample must record node_count=rung=200")
        if sample.get("real_valkey") is not True:
            errors.append(f"{sid}: P21 sample must be real Valkey evidence")
        if sample.get("cleanup_status") != "PASS":
            errors.append(f"{sid}: cleanup_status must be PASS")
    event_sample_ids = {str(event.get("sample_id")) for event in events if event.get("sample_id")}
    metric_sample_ids = {str(metric.get("sample_id")) for metric in metrics if metric.get("sample_id")}
    missing_events = sorted(sample_ids - event_sample_ids)
    missing_metrics = sorted(sample_ids - metric_sample_ids)
    if missing_events:
        errors.append(f"P21 events.jsonl missing sample IDs: {missing_events}")
    if missing_metrics:
        errors.append(f"P21 metrics_timeseries.jsonl missing sample IDs: {missing_metrics}")
    for idx, event in enumerate(events, start=1):
        if event.get("phase_id") != "P21_FAILOVER_LATENCY_CURVE_200":
            errors.append(f"P21 events.jsonl:{idx}: wrong phase_id {event.get('phase_id')!r}")
        if event.get("sample_id") and event.get("sample_id") not in expected_ids:
            errors.append(f"P21 events.jsonl:{idx}: unexpected sample_id {event.get('sample_id')!r}")
    for idx, metric in enumerate(metrics, start=1):
        if metric.get("phase_id") != "P21_FAILOVER_LATENCY_CURVE_200":
            errors.append(f"P21 metrics_timeseries.jsonl:{idx}: wrong phase_id {metric.get('phase_id')!r}")
        if metric.get("sample_id") and metric.get("sample_id") not in expected_ids:
            errors.append(f"P21 metrics_timeseries.jsonl:{idx}: unexpected sample_id {metric.get('sample_id')!r}")
        if metric.get("metric_value") == "MISSING" and not metric.get("missing_reason"):
            errors.append(f"P21 metrics_timeseries.jsonl:{idx}: MISSING metric_value requires missing_reason")
    preflight_path = base / "resource_preflight_200.json"
    if preflight_path.exists():
        preflight = load_json(preflight_path)
        if preflight.get("status") != "PASS" or preflight.get("can_run") is not True:
            errors.append("P21 resource_preflight_200 must PASS")
        if preflight.get("dry_run") is not False:
            errors.append("P21 resource_preflight_200 must be non-dry-run")
        if preflight.get("node_count") != 200:
            errors.append("P21 resource_preflight_200 must record node_count=200")
    else:
        errors.append("P21 resource_preflight_200.json missing")
    evidence_path = base / "valkey_e2e_evidence.json"
    if evidence_path.exists():
        evidence = load_json(evidence_path)
        if evidence.get("status") != "PASS":
            errors.append("P21 valkey_e2e_evidence status must be PASS")
        if evidence.get("real_valkey") is not True:
            errors.append("P21 valkey_e2e_evidence must be real Valkey")
        if int(evidence.get("nodes_observed", 0) or 0) != 200:
            errors.append("P21 valkey_e2e_evidence must observe exactly 200 nodes")
        if len(evidence.get("sample_refs", [])) != 3:
            errors.append("P21 valkey_e2e_evidence must reference exactly 3 samples")
    else:
        errors.append("P21 valkey_e2e_evidence.json missing")
    quant_path = base / "quant_summary.json"
    if quant_path.exists():
        quant = load_json(quant_path)
        counts = quant.get("counts", {})
        if counts.get("event_count") != len(events):
            errors.append("P21 quant_summary counts.event_count must match events.jsonl line count")
        if counts.get("metric_count") != len(metrics):
            errors.append("P21 quant_summary counts.metric_count must match metrics_timeseries.jsonl line count")
        if counts.get("sample_count") != len(samples) or counts.get("sample_count") != 3:
            errors.append("P21 quant_summary counts.sample_count must be 3 and match samples")
        if counts.get("node_count") != 200:
            errors.append("P21 quant_summary counts.node_count must be 200")
        claims = quant.get("runtime_claims", {})
        if claims.get("real_valkey_claimed") is not True or claims.get("fault_runtime_claimed") is not True:
            errors.append("P21 quant_summary must claim real Valkey fault runtime")


def assert_p22_semantics(base: Path, errors: list[str]) -> None:
    events = read_jsonl(base / "events.jsonl", errors)
    metrics = read_jsonl(base / "metrics_timeseries.jsonl", errors)
    fault_rows = read_jsonl(base / "fault_results.jsonl", errors)
    snapshots = read_jsonl(base / "fault_topology_snapshots.jsonl", errors)
    required_faults = {"replica_stop", "node_host_stop", "az_stop"}
    real_rows = [row for row in fault_rows if row.get("status") != "SKIPPED_WITH_REASON"]
    real_sample_ids = {str(row.get("sample_id")) for row in real_rows if row.get("sample_id")}
    required_pairs = {(fault_type, count) for fault_type in required_faults for count in [6, 10]}
    observed_pairs = {(row.get("fault_type"), row.get("node_count")) for row in real_rows}
    missing_pairs = sorted(required_pairs - observed_pairs)
    if missing_pairs:
        errors.append(f"P22 quant missing required real fault pairs: {missing_pairs}")
    if any(row.get("node_count") == 200 for row in fault_rows):
        errors.append("P22 quant artifacts must not contain 200-node rows")
    event_sample_ids = {str(event.get("sample_id")) for event in events if event.get("sample_id")}
    metric_sample_ids = {str(metric.get("sample_id")) for metric in metrics if metric.get("sample_id")}
    snapshot_sample_ids = {str(snapshot.get("sample_id")) for snapshot in snapshots if snapshot.get("sample_id")}
    missing_event_samples = sorted(real_sample_ids - event_sample_ids)
    missing_metric_samples = sorted(real_sample_ids - metric_sample_ids)
    missing_snapshot_samples = sorted(real_sample_ids - snapshot_sample_ids)
    if missing_event_samples:
        errors.append(f"P22 events.jsonl missing sample IDs: {missing_event_samples}")
    if missing_metric_samples:
        errors.append(f"P22 metrics_timeseries.jsonl missing sample IDs: {missing_metric_samples}")
    if missing_snapshot_samples:
        errors.append(f"P22 topology snapshots missing sample IDs: {missing_snapshot_samples}")
    fault_ids = {str(row.get("fault_id")) for row in real_rows if row.get("fault_id")}
    event_fault_ids = {str(event.get("fault_id")) for event in events if event.get("fault_id")}
    metric_fault_ids = {str(metric.get("source_id")) for metric in metrics if metric.get("source_type") == "harness"}
    if not fault_ids.issubset(event_fault_ids):
        errors.append(f"P22 events missing fault IDs: {sorted(fault_ids - event_fault_ids)}")
    if not fault_ids.issubset(metric_fault_ids):
        errors.append(f"P22 harness metrics missing fault IDs: {sorted(fault_ids - metric_fault_ids)}")
    for idx, event in enumerate(events, start=1):
        if event.get("phase_id") != "P22_FAULT_REPLICA_HOST_AZ_STOP":
            errors.append(f"P22 events.jsonl:{idx}: wrong phase_id {event.get('phase_id')!r}")
    for idx, metric in enumerate(metrics, start=1):
        if metric.get("phase_id") != "P22_FAULT_REPLICA_HOST_AZ_STOP":
            errors.append(f"P22 metrics_timeseries.jsonl:{idx}: wrong phase_id {metric.get('phase_id')!r}")
        if metric.get("metric_value") == "MISSING" and not metric.get("missing_reason"):
            errors.append(f"P22 metrics_timeseries.jsonl:{idx}: MISSING metric_value requires missing_reason")
    for idx, row in enumerate(fault_rows, start=1):
        if row.get("phase_id") != "P22_FAULT_REPLICA_HOST_AZ_STOP":
            errors.append(f"P22 fault_results.jsonl:{idx}: wrong phase_id {row.get('phase_id')!r}")
        if row.get("status") == "SKIPPED_WITH_REASON" and not row.get("reason"):
            errors.append(f"P22 fault_results.jsonl:{idx}: skipped row requires reason")
    evidence_path = base / "valkey_e2e_evidence.json"
    if evidence_path.exists():
        evidence = load_json(evidence_path)
        if evidence.get("status") != "PASS":
            errors.append("P22 valkey_e2e_evidence status must be PASS")
        if evidence.get("real_valkey") is not True:
            errors.append("P22 valkey_e2e_evidence must be real Valkey")
        if int(evidence.get("nodes_observed", 0) or 0) < 10:
            errors.append("P22 valkey_e2e_evidence must observe at least the 10-node mandatory row")
    else:
        errors.append("P22 valkey_e2e_evidence.json missing")
    quant_path = base / "quant_summary.json"
    if quant_path.exists():
        quant = load_json(quant_path)
        counts = quant.get("counts", {})
        if counts.get("event_count") != len(events):
            errors.append("P22 quant_summary counts.event_count must match events.jsonl line count")
        if counts.get("metric_count") != len(metrics):
            errors.append("P22 quant_summary counts.metric_count must match metrics_timeseries.jsonl line count")
        if counts.get("fault_result_count") != len(fault_rows):
            errors.append("P22 quant_summary counts.fault_result_count must match fault_results.jsonl line count")
        if counts.get("topology_snapshot_count") != len(snapshots):
            errors.append("P22 quant_summary counts.topology_snapshot_count must match topology snapshot line count")
        if counts.get("sample_count") != len(real_rows):
            errors.append("P22 quant_summary counts.sample_count must match non-skipped fault rows")
        claims = quant.get("runtime_claims", {})
        if claims.get("real_valkey_claimed") is not True or claims.get("fault_runtime_claimed") is not True:
            errors.append("P22 quant_summary must claim real Valkey fault runtime")
    else:
        errors.append("P22 quant_summary.json missing")


def assert_p23_semantics(base: Path, errors: list[str]) -> None:
    events = read_jsonl(base / "events.jsonl", errors)
    metrics = read_jsonl(base / "metrics_timeseries.jsonl", errors)
    fault_rows = read_jsonl(base / "fault_results.jsonl", errors)
    command_rows = read_jsonl(base / "network_fault_command_log.jsonl", errors)
    required_faults = {"network_delay", "network_loss", "network_flap"}
    real_rows = [row for row in fault_rows if row.get("status") != "SKIPPED_WITH_REASON"]
    real_sample_ids = {str(row.get("sample_id")) for row in real_rows if row.get("sample_id")}
    required_pairs = {(fault_type, count) for fault_type in required_faults for count in [6, 10]}
    observed_pairs = {(row.get("fault_type"), row.get("node_count")) for row in real_rows}
    missing_pairs = sorted(required_pairs - observed_pairs)
    if missing_pairs:
        errors.append(f"P23 quant missing required real fault pairs: {missing_pairs}")
    if any(row.get("node_count") == 200 for row in fault_rows):
        errors.append("P23 quant artifacts must not contain 200-node rows")
    event_sample_ids = {str(event.get("sample_id")) for event in events if event.get("sample_id")}
    metric_sample_ids = {str(metric.get("sample_id")) for metric in metrics if metric.get("sample_id")}
    missing_event_samples = sorted(real_sample_ids - event_sample_ids)
    missing_metric_samples = sorted(real_sample_ids - metric_sample_ids)
    if missing_event_samples:
        errors.append(f"P23 events.jsonl missing sample IDs: {missing_event_samples}")
    if missing_metric_samples:
        errors.append(f"P23 metrics_timeseries.jsonl missing sample IDs: {missing_metric_samples}")
    fault_ids = {str(row.get("fault_id")) for row in real_rows if row.get("fault_id")}
    event_fault_ids = {str(event.get("fault_id")) for event in events if event.get("fault_id")}
    metric_fault_ids = {str(metric.get("source_id")) for metric in metrics if metric.get("source_type") == "harness"}
    command_fault_ids = {str(command.get("fault_id")) for command in command_rows if command.get("fault_id")}
    if not fault_ids.issubset(event_fault_ids):
        errors.append(f"P23 events missing fault IDs: {sorted(fault_ids - event_fault_ids)}")
    if not fault_ids.issubset(metric_fault_ids):
        errors.append(f"P23 harness metrics missing fault IDs: {sorted(fault_ids - metric_fault_ids)}")
    if not fault_ids.issubset(command_fault_ids):
        errors.append(f"P23 command log missing fault IDs: {sorted(fault_ids - command_fault_ids)}")
    for idx, event in enumerate(events, start=1):
        if event.get("phase_id") != "P23_FAULT_NETWORK_DELAY_LOSS_FLAP":
            errors.append(f"P23 events.jsonl:{idx}: wrong phase_id {event.get('phase_id')!r}")
    for idx, metric in enumerate(metrics, start=1):
        if metric.get("phase_id") != "P23_FAULT_NETWORK_DELAY_LOSS_FLAP":
            errors.append(f"P23 metrics_timeseries.jsonl:{idx}: wrong phase_id {metric.get('phase_id')!r}")
        if metric.get("metric_value") == "MISSING" and not metric.get("missing_reason"):
            errors.append(f"P23 metrics_timeseries.jsonl:{idx}: MISSING metric_value requires missing_reason")
    for idx, row in enumerate(fault_rows, start=1):
        if row.get("phase_id") != "P23_FAULT_NETWORK_DELAY_LOSS_FLAP":
            errors.append(f"P23 fault_results.jsonl:{idx}: wrong phase_id {row.get('phase_id')!r}")
        if row.get("status") != "PASS":
            errors.append(f"P23 fault_results.jsonl:{idx}: mandatory row status must be PASS")
        if row.get("implementation_path") != "sandbox_proxy":
            errors.append(f"P23 fault_results.jsonl:{idx}: expected sandbox_proxy implementation path")
    evidence_path = base / "valkey_e2e_evidence.json"
    if evidence_path.exists():
        evidence = load_json(evidence_path)
        if evidence.get("status") != "PASS":
            errors.append("P23 valkey_e2e_evidence status must be PASS")
        if evidence.get("real_valkey") is not True:
            errors.append("P23 valkey_e2e_evidence must be real Valkey")
        if int(evidence.get("nodes_observed", 0) or 0) < 10:
            errors.append("P23 valkey_e2e_evidence must observe at least the 10-node mandatory row")
        versions = evidence.get("valkey_versions", [])
        if not versions or any(not str(version).startswith("9.1.") for version in versions):
            errors.append("P23 valkey_e2e_evidence must include Valkey 9.1.x versions")
    else:
        errors.append("P23 valkey_e2e_evidence.json missing")
    network_path = base / "network_fault_report.json"
    if network_path.exists():
        network = load_json(network_path)
        if network.get("status") != "PASS":
            errors.append("P23 network_fault_report status must be PASS")
        if set(network.get("safe_paths_exercised", [])) != {"sandbox_proxy"}:
            errors.append("P23 network_fault_report safe_paths_exercised must be exactly sandbox_proxy")
    else:
        errors.append("P23 network_fault_report.json missing")
    quant_path = base / "quant_summary.json"
    if quant_path.exists():
        quant = load_json(quant_path)
        counts = quant.get("counts", {})
        if counts.get("event_count") != len(events):
            errors.append("P23 quant_summary counts.event_count must match events.jsonl line count")
        if counts.get("metric_count") != len(metrics):
            errors.append("P23 quant_summary counts.metric_count must match metrics_timeseries.jsonl line count")
        if counts.get("fault_result_count") != len(fault_rows):
            errors.append("P23 quant_summary counts.fault_result_count must match fault_results.jsonl line count")
        if counts.get("command_log_count") != len(command_rows):
            errors.append("P23 quant_summary counts.command_log_count must match command log line count")
        if counts.get("sample_count") != len(real_rows):
            errors.append("P23 quant_summary counts.sample_count must match non-skipped fault rows")
        claims = quant.get("runtime_claims", {})
        if claims.get("real_valkey_claimed") is not True or claims.get("fault_runtime_claimed") is not True:
            errors.append("P23 quant_summary must claim real Valkey fault runtime")
    else:
        errors.append("P23 quant_summary.json missing")


def assert_p24_semantics(base: Path, errors: list[str]) -> None:
    events = read_jsonl(base / "events.jsonl", errors)
    metrics = read_jsonl(base / "metrics_timeseries.jsonl", errors)
    fault_rows = read_jsonl(base / "fault_results.jsonl", errors)
    snapshots = read_jsonl(base / "fault_topology_snapshots.jsonl", errors)
    command_rows = read_jsonl(base / "network_partition_command_log.jsonl", errors)
    required_faults = {"network_partition_minority", "network_partition_majority", "split_brain_window_detection"}
    real_rows = [row for row in fault_rows if row.get("status") != "SKIPPED_WITH_REASON"]
    real_sample_ids = {str(row.get("sample_id")) for row in real_rows if row.get("sample_id")}
    required_pairs = {(fault_type, count) for fault_type in required_faults for count in [6, 10]}
    observed_pairs = {(row.get("fault_type"), row.get("node_count")) for row in real_rows}
    missing_pairs = sorted(required_pairs - observed_pairs)
    if missing_pairs:
        errors.append(f"P24 quant missing required real fault pairs: {missing_pairs}")
    if any(row.get("node_count") in {200, 1000} for row in fault_rows):
        errors.append("P24 quant artifacts must not contain 200/1000-node rows")

    event_sample_ids = {str(event.get("sample_id")) for event in events if event.get("sample_id")}
    metric_sample_ids = {str(metric.get("sample_id")) for metric in metrics if metric.get("sample_id")}
    snapshot_sample_ids = {str(snapshot.get("sample_id")) for snapshot in snapshots if snapshot.get("sample_id")}
    missing_event_samples = sorted(real_sample_ids - event_sample_ids)
    missing_metric_samples = sorted(real_sample_ids - metric_sample_ids)
    missing_snapshot_samples = sorted(real_sample_ids - snapshot_sample_ids)
    if missing_event_samples:
        errors.append(f"P24 events.jsonl missing sample IDs: {missing_event_samples}")
    if missing_metric_samples:
        errors.append(f"P24 metrics_timeseries.jsonl missing sample IDs: {missing_metric_samples}")
    if missing_snapshot_samples:
        errors.append(f"P24 topology snapshots missing sample IDs: {missing_snapshot_samples}")

    fault_ids = {str(row.get("fault_id")) for row in real_rows if row.get("fault_id")}
    event_fault_ids = {str(event.get("fault_id")) for event in events if event.get("fault_id")}
    metric_fault_ids = {str(metric.get("source_id")) for metric in metrics if metric.get("source_type") == "harness"}
    command_fault_ids = {str(command.get("fault_id")) for command in command_rows if command.get("fault_id")}
    if not fault_ids.issubset(event_fault_ids):
        errors.append(f"P24 events missing fault IDs: {sorted(fault_ids - event_fault_ids)}")
    if not fault_ids.issubset(metric_fault_ids):
        errors.append(f"P24 harness metrics missing fault IDs: {sorted(fault_ids - metric_fault_ids)}")
    if not fault_ids.issubset(command_fault_ids):
        errors.append(f"P24 command log missing fault IDs: {sorted(fault_ids - command_fault_ids)}")

    for idx, event in enumerate(events, start=1):
        if event.get("phase_id") != "P24_PARTITION_SPLIT_BRAIN_MATRIX":
            errors.append(f"P24 events.jsonl:{idx}: wrong phase_id {event.get('phase_id')!r}")
    for idx, metric in enumerate(metrics, start=1):
        if metric.get("phase_id") != "P24_PARTITION_SPLIT_BRAIN_MATRIX":
            errors.append(f"P24 metrics_timeseries.jsonl:{idx}: wrong phase_id {metric.get('phase_id')!r}")
        if metric.get("metric_value") == "MISSING" and not metric.get("missing_reason"):
            errors.append(f"P24 metrics_timeseries.jsonl:{idx}: MISSING metric_value requires missing_reason")
    for idx, row in enumerate(fault_rows, start=1):
        if row.get("phase_id") != "P24_PARTITION_SPLIT_BRAIN_MATRIX":
            errors.append(f"P24 fault_results.jsonl:{idx}: wrong phase_id {row.get('phase_id')!r}")
        if row.get("status") != "PASS":
            errors.append(f"P24 fault_results.jsonl:{idx}: mandatory row status must be PASS")
        if row.get("implementation_path") != "owned_docker_network_control":
            errors.append(f"P24 fault_results.jsonl:{idx}: expected owned_docker_network_control implementation path")
        if row.get("host_network_mutated") is not False or row.get("global_firewall_mutated") is not False:
            errors.append(f"P24 fault_results.jsonl:{idx}: host/global network mutation flags must be false")
    for idx, command in enumerate(command_rows, start=1):
        if command.get("implementation_path") != "owned_docker_network_control":
            errors.append(f"P24 network_partition_command_log.jsonl:{idx}: expected owned_docker_network_control")
        if command.get("host_network_mutated") is not False or command.get("global_firewall_mutated") is not False:
            errors.append(f"P24 network_partition_command_log.jsonl:{idx}: host/global network mutation flags must be false")

    evidence_path = base / "valkey_e2e_evidence.json"
    if evidence_path.exists():
        evidence = load_json(evidence_path)
        if evidence.get("status") != "PASS":
            errors.append("P24 valkey_e2e_evidence status must be PASS")
        if evidence.get("real_valkey") is not True:
            errors.append("P24 valkey_e2e_evidence must be real Valkey")
        if int(evidence.get("nodes_observed", 0) or 0) < 10:
            errors.append("P24 valkey_e2e_evidence must observe at least the 10-node mandatory row")
        versions = evidence.get("valkey_versions", [])
        if not versions or any(not str(version).startswith("9.1.") for version in versions):
            errors.append("P24 valkey_e2e_evidence must include Valkey 9.1.x versions")
    else:
        errors.append("P24 valkey_e2e_evidence.json missing")

    partition_path = base / "partition_report.json"
    if partition_path.exists():
        partition = load_json(partition_path)
        if partition.get("status") != "PASS":
            errors.append("P24 partition_report status must be PASS")
        sample_ids = {str(sample.get("sample_id")) for sample in partition.get("samples", []) if isinstance(sample, dict)}
        if not real_sample_ids.issubset(sample_ids):
            errors.append(f"P24 partition_report missing samples: {sorted(real_sample_ids - sample_ids)}")
        safety = partition.get("safety_scope", {})
        if safety.get("host_network_mutated") is not False or safety.get("global_firewall_mutated") is not False:
            errors.append("P24 partition_report safety_scope must prove no host/global mutation")
    else:
        errors.append("P24 partition_report.json missing")

    split_path = base / "split_brain_report.json"
    if split_path.exists():
        split = load_json(split_path)
        if split.get("status") != "PASS":
            errors.append("P24 split_brain_report status must be PASS")
        split_sample_ids = {str(sample.get("sample_id")) for sample in split.get("samples", []) if isinstance(sample, dict)}
        if not real_sample_ids.issubset(split_sample_ids):
            errors.append(f"P24 split_brain_report missing samples: {sorted(real_sample_ids - split_sample_ids)}")
        if not split.get("detectors_run"):
            errors.append("P24 split_brain_report must include detectors_run")
    else:
        errors.append("P24 split_brain_report.json missing")

    quant_path = base / "quant_summary.json"
    if quant_path.exists():
        quant = load_json(quant_path)
        counts = quant.get("counts", {})
        if counts.get("event_count") != len(events):
            errors.append("P24 quant_summary counts.event_count must match events.jsonl line count")
        if counts.get("metric_count") != len(metrics):
            errors.append("P24 quant_summary counts.metric_count must match metrics_timeseries.jsonl line count")
        if counts.get("fault_result_count") != len(fault_rows):
            errors.append("P24 quant_summary counts.fault_result_count must match fault_results.jsonl line count")
        if counts.get("topology_snapshot_count") != len(snapshots):
            errors.append("P24 quant_summary counts.topology_snapshot_count must match topology snapshot line count")
        if counts.get("command_log_count") != len(command_rows):
            errors.append("P24 quant_summary counts.command_log_count must match command log line count")
        if counts.get("sample_count") != len(real_rows):
            errors.append("P24 quant_summary counts.sample_count must match non-skipped fault rows")
        claims = quant.get("runtime_claims", {})
        if claims.get("real_valkey_claimed") is not True or claims.get("fault_runtime_claimed") is not True:
            errors.append("P24 quant_summary must claim real Valkey fault runtime")
    else:
        errors.append("P24 quant_summary.json missing")


def assert_p25_semantics(base: Path, errors: list[str]) -> None:
    events = read_jsonl(base / "events.jsonl", errors)
    metrics = read_jsonl(base / "metrics_timeseries.jsonl", errors)
    cross_path = base / "workload_impact_cross_stage.json"
    missing_path = base / "missing_data_summary.json"
    csv_index_path = base / "csv_export_index.json"
    quant_path = base / "quant_summary.json"
    workload_path = base / "workload_windows.json"
    if not cross_path.exists():
        errors.append("P25 workload_impact_cross_stage.json missing")
        return
    if not missing_path.exists():
        errors.append("P25 missing_data_summary.json missing")
        return
    if not csv_index_path.exists():
        errors.append("P25 csv_export_index.json missing")
        return
    if not quant_path.exists():
        errors.append("P25 quant_summary.json missing")
        return

    cross = load_json(cross_path)
    missing = load_json(missing_path)
    csv_index = load_json(csv_index_path)
    quant = load_json(quant_path)
    rows = cross.get("rows", [])
    statuses = cross.get("source_stage_statuses", [])
    status_ids = {status.get("stage_id") for status in statuses if isinstance(status, dict)}
    missing_stages = sorted(P25_SOURCE_STAGES - status_ids)
    if missing_stages:
        errors.append(f"P25 cross-stage source coverage missing stages: {missing_stages}")
    row_counts = cross.get("row_counts", {})
    expected_total = len(rows)
    if row_counts.get("total") != expected_total:
        errors.append("P25 workload_impact_cross_stage row_counts.total must match rows length")
    if row_counts.get("management") != sum(1 for row in rows if row.get("category") == "management"):
        errors.append("P25 management row count mismatch")
    if row_counts.get("failover") != sum(1 for row in rows if row.get("category") == "failover"):
        errors.append("P25 failover row count mismatch")
    if row_counts.get("fault") != sum(1 for row in rows if row.get("category") == "fault"):
        errors.append("P25 fault row count mismatch")

    for idx, event in enumerate(events, start=1):
        if event.get("phase_id") != "P25_FAULT_WORKLOAD_IMPACT_ANALYSIS":
            errors.append(f"P25 events.jsonl:{idx}: wrong phase_id {event.get('phase_id')!r}")
    for idx, metric in enumerate(metrics, start=1):
        if metric.get("phase_id") != "P25_FAULT_WORKLOAD_IMPACT_ANALYSIS":
            errors.append(f"P25 metrics_timeseries.jsonl:{idx}: wrong phase_id {metric.get('phase_id')!r}")
        if metric.get("metric_value") == "MISSING" and not metric.get("missing_reason"):
            errors.append(f"P25 metrics_timeseries.jsonl:{idx}: MISSING metric_value requires missing_reason")

    if missing.get("item_count") != len(missing.get("items", [])):
        errors.append("P25 missing_data_summary item_count must match item length")
    for idx, item in enumerate(missing.get("items", [])):
        if item.get("status") in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"} and not item.get("reason"):
            errors.append(f"P25 missing_data_summary.items[{idx}]: status requires reason")
        if item.get("source_stage_id") not in P25_SOURCE_STAGES:
            errors.append(f"P25 missing_data_summary.items[{idx}]: invalid source_stage_id {item.get('source_stage_id')!r}")

    table_names = {item.get("table_name") for item in csv_index.get("exports", []) if isinstance(item, dict)}
    if table_names != {"operation", "fault", "latency", "error", "recovery"}:
        errors.append(f"P25 csv_export_index must include exact export set, got {sorted(str(item) for item in table_names)}")
    for export in csv_index.get("exports", []):
        if not isinstance(export, dict):
            errors.append("P25 csv_export_index exports must be objects")
            continue
        if export.get("row_count") != export.get("json_source_count"):
            errors.append(f"P25 csv export {export.get('table_name')}: row_count must equal json_source_count")
        if not export.get("sha256"):
            errors.append(f"P25 csv export {export.get('table_name')}: sha256 required")

    counts = quant.get("counts", {})
    if counts.get("event_count") != len(events):
        errors.append("P25 quant_summary counts.event_count must match events.jsonl line count")
    if counts.get("metric_count") != len(metrics):
        errors.append("P25 quant_summary counts.metric_count must match metrics_timeseries.jsonl line count")
    if counts.get("total") != expected_total:
        errors.append("P25 quant_summary counts.total must match cross-stage rows")
    if counts.get("missing_data_item_count") != missing.get("item_count"):
        errors.append("P25 quant_summary missing_data_item_count must match missing summary")
    refs = set(str(ref) for ref in quant.get("artifact_refs", []))
    for required in [
        "workload_impact_cross_stage.json",
        "workload_impact_by_operation.csv",
        "workload_impact_by_fault.csv",
        "latency_delta_table.csv",
        "error_delta_table.csv",
        "recovery_duration_table.csv",
        "csv_export_index.json",
        "missing_data_summary.json",
    ]:
        if not any(required in ref for ref in refs):
            errors.append(f"P25 quant_summary artifact_refs missing {required}")
    for stage_id in P25_SOURCE_STAGES:
        if not any(stage_id in ref for ref in refs):
            errors.append(f"P25 quant_summary artifact_refs missing source stage {stage_id}")
    claims = quant.get("runtime_claims", {})
    if claims.get("real_valkey_claimed") is not True:
        errors.append("P25 quant_summary must claim real Valkey smoke evidence")
    if claims.get("management_runtime_claimed") is not False or claims.get("fault_runtime_claimed") is not False:
        errors.append("P25 quant_summary must not claim it reran management/fault runtime behavior")
    if claims.get("source_runtime_behavior_rerun") is not False:
        errors.append("P25 quant_summary must record source_runtime_behavior_rerun=false")

    if workload_path.exists():
        workload = load_json(workload_path)
        names = [window.get("window_name") for window in workload.get("windows", [])]
        if names != CANONICAL_WINDOWS:
            errors.append(f"P25 workload_windows must be canonical analysis windows, got {names}")
        for window in workload.get("windows", []):
            if window.get("status") == "SKIPPED_WITH_REASON" and not window.get("reason"):
                errors.append(f"P25 workload window {window.get('window_name')}: skip requires reason")
    else:
        errors.append("P25 workload_windows.json missing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()

    manifest = load_json(ROOT / "codex" / "phase_manifest.json")
    phase = phase_by_id(manifest, args.phase)
    errors: list[str] = []
    for artifact in phase.get("required_artifacts", []):
        if artifact.get("required", True):
            errors.extend(validate_artifact(ROOT / artifact["path"], ROOT / artifact["schema"]))

    base = ROOT / "artifacts" / "phases" / args.phase
    quant_path = base / "quant_summary.json"
    if quant_path.exists():
        quant = load_json(quant_path)
        for idx, item in enumerate(quant.get("missing_data", [])):
            require_reason(item, f"quant_summary.missing_data[{idx}]", errors)
    phase_summary_path = base / "phase_summary.json"
    if phase_summary_path.exists():
        phase_summary = load_json(phase_summary_path)
        for idx, item in enumerate(phase_summary.get("missing_metrics", [])):
            status = item.get("status")
            if status in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"} and not item.get("reason"):
                errors.append(f"phase_summary.missing_metrics[{idx}]: {status} requires reason")
    if phase.get("real_valkey_required"):
        for name in ["events.jsonl", "metrics_timeseries.jsonl", "workload_windows.json", "cleanup_report.json", "valkey_e2e_evidence.json"]:
            if not (base / name).exists():
                errors.append(f"{args.phase}: required real-stage artifact missing: {name}")
        if (base / "cleanup_report.json").exists():
            cleanup = load_json(base / "cleanup_report.json")
            if cleanup.get("status") != "PASS":
                errors.append("cleanup_report status must be PASS")
            if cleanup.get("resources_remaining"):
                errors.append("cleanup_report resources_remaining must be empty")
    if (base / "events.jsonl").exists():
        errors.extend(validate_artifact(base / "events.jsonl", ROOT / "schemas/artifact/goal_loop_event.schema.json"))
    if (base / "metrics_timeseries.jsonl").exists():
        errors.extend(validate_artifact(base / "metrics_timeseries.jsonl", ROOT / "schemas/artifact/goal_loop_metric_sample.schema.json"))
        for lineno, line in enumerate((base / "metrics_timeseries.jsonl").read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("metric_value") == "MISSING" and not obj.get("missing_reason"):
                errors.append(f"metrics_timeseries.jsonl:{lineno}: MISSING metric_value requires missing_reason")
    if args.phase == "P16_QUANT_TELEMETRY_UNIFICATION":
        assert_p16_semantics(base, errors)
    if args.phase == "P20_FAILOVER_LATENCY_CURVE_30_50_100":
        assert_p20_semantics(base, errors)
    if args.phase == "P21_FAILOVER_LATENCY_CURVE_200":
        assert_p21_semantics(base, errors)
    if args.phase == "P22_FAULT_REPLICA_HOST_AZ_STOP":
        assert_p22_semantics(base, errors)
    if args.phase == "P23_FAULT_NETWORK_DELAY_LOSS_FLAP":
        assert_p23_semantics(base, errors)
    if args.phase == "P24_PARTITION_SPLIT_BRAIN_MATRIX":
        assert_p24_semantics(base, errors)
    if args.phase == "P25_FAULT_WORKLOAD_IMPACT_ANALYSIS":
        assert_p25_semantics(base, errors)

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS quant artifacts phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
