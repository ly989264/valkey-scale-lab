from __future__ import annotations

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

REQUIRED_TIMESTAMPS = [
    "fault_apply_at_ms",
    "target_process_gone_at_ms",
    "first_pfail_seen_at_ms",
    "first_fail_seen_at_ms",
    "first_promotion_seen_at_ms",
    "first_slots_covered_at_ms",
    "first_cluster_ok_at_ms",
    "first_client_success_at_ms",
    "clean_snapshot_passed_at_ms",
]

RTO_METRIC_FIELDS = [
    "kill_to_pfail_ms",
    "pfail_to_cluster_ok_ms",
    "kill_to_client_recovered_ms",
    "cluster_ok_to_client_success_ms",
    "cluster_ok_to_clean_snapshot_ms",
    "kill_to_clean_snapshot_ms",
]

LAYER_SOURCE_FIELDS = {
    "level_1": "observer",
    "level_2": "client_probe",
    "level_3": "clean_gate",
}

FULL_FLOW_TIMELINE_EVENTS = [
    "fault_planned",
    "fault_apply_started",
    "fault_apply_completed",
    "fault_effect_observed",
    "cluster_impact_started",
    "failover_started",
    "promotion_observed",
    "cluster_recovered",
    "workload_recovered",
    "fault_clear_started",
    "fault_clear_completed",
    "cleanup_verified",
]

FULL_FLOW_TIMELINE_METRICS = [
    "apply_duration_ms",
    "effect_observed_delay_ms",
    "cluster_impact_ms",
    "failover_latency_ms",
    "promotion_latency_ms",
    "client_unavailability_ms",
    "workload_recovery_ms",
    "clear_duration_ms",
    "cleanup_duration_ms",
    "split_brain_window_ms",
    "cluster_down_window_ms",
]

FULL_FLOW_FAULT_TYPES = [
    "primary_stop_failover",
    "replica_stop",
    "node_host_stop",
    "az_stop",
    "network_delay",
    "network_loss",
    "network_flap",
    "network_partition",
    "minority_partition",
    "majority_partition",
    "split_brain_window_detection",
    "fault_period_workload_impact",
]

FULL_FLOW_SCALE_RUNGS = ["small", "30", "50", "100", "200"]
FAULT_EVENT_STATUSES = {"OBSERVED", "MISSING", "SKIPPED_WITH_REASON", "BLOCKED_WITH_REASON", "FAIL"}


class FailoverTimelineError(ValueError):
    """Raised when FAILOVER_TIMELINE timeline inputs cannot support a real RTO metric."""


def missing_metric(reason: str, *, status: str = "MISSING", impact: str | None = None) -> dict[str, str]:
    if status not in {"MISSING", "SKIPPED_WITH_REASON", "BLOCKED_WITH_REASON"}:
        raise FailoverTimelineError(f"unsupported missing metric status: {status}")
    value = {"status": status, "reason": reason}
    if impact:
        value["impact"] = impact
    return value


def make_fault_timeline_event(
    *,
    capability_id: str,
    run_id: str,
    scenario_name: str,
    sample_id: str,
    fault_id: str,
    fault_type: str,
    node_count: int,
    scale_rung: str,
    event_name: str,
    event_status: str = "OBSERVED",
    timestamp_unix_ms: int | dict[str, Any] | str | None = None,
    monotonic_ms_value: float | dict[str, Any] | str | None = None,
    reason: str = "",
    source: str = "fault_timeline_contract",
    subject_type: str = "cluster",
    subject_id: str = "cluster",
    real_valkey: bool = False,
    execution_mode: str = "fake",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if event_name not in FULL_FLOW_TIMELINE_EVENTS:
        raise FailoverTimelineError(f"unsupported fault timeline event: {event_name}")
    if event_status not in FAULT_EVENT_STATUSES:
        raise FailoverTimelineError(f"unsupported fault timeline event status: {event_status}")
    if event_status != "OBSERVED" and not reason:
        raise FailoverTimelineError(f"{event_name} with {event_status} requires reason")
    if event_status == "OBSERVED" and not isinstance(timestamp_unix_ms, int):
        raise FailoverTimelineError(f"{event_name} OBSERVED requires integer timestamp_unix_ms")
    if event_status == "OBSERVED" and not isinstance(monotonic_ms_value, (int, float)):
        raise FailoverTimelineError(f"{event_name} OBSERVED requires numeric monotonic_ms")
    event = {
        "schema_version": "v1",
        "artifact_type": "fault_timeline_event",
        "capability_id": capability_id,
        "run_id": run_id,
        "scenario_name": scenario_name,
        "sample_id": sample_id,
        "fault_id": fault_id,
        "fault_type": fault_type,
        "node_count": node_count,
        "scale_rung": str(scale_rung),
        "event_name": event_name,
        "event_status": event_status,
        "timestamp_unix_ms": timestamp_unix_ms if timestamp_unix_ms is not None else missing_metric(reason or "event was not observed"),
        "monotonic_ms": monotonic_ms_value if monotonic_ms_value is not None else missing_metric(reason or "event was not observed"),
        "source": source,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "real_valkey": real_valkey,
        "execution_mode": execution_mode,
        "reason": reason,
    }
    if details:
        event["details"] = details
    return event


def derive_fault_timeline_metrics(events: list[dict[str, Any]], workload_windows: dict[str, Any] | None = None) -> dict[str, Any]:
    by_name = {str(event.get("event_name")): event for event in events}
    missing_events = [name for name in FULL_FLOW_TIMELINE_EVENTS if name not in by_name]
    if missing_events:
        raise FailoverTimelineError(f"timeline is missing required events: {', '.join(missing_events)}")
    observed = {
        name: float(event["monotonic_ms"])
        for name, event in by_name.items()
        if event.get("event_status") == "OBSERVED" and isinstance(event.get("monotonic_ms"), (int, float))
    }
    ordered = [observed[name] for name in FULL_FLOW_TIMELINE_EVENTS if name in observed]
    if any(left > right for left, right in zip(ordered, ordered[1:])):
        raise FailoverTimelineError("observed timeline events must be monotonic")

    def delta(name: str, start: str, end: str) -> Any:
        if start in observed and end in observed:
            value = observed[end] - observed[start]
            if value < 0:
                raise FailoverTimelineError(f"{name} derived to negative duration")
            return round(value, 3)
        return _missing_delta(name, start, end, by_name)

    metrics = {
        "apply_duration_ms": delta("apply_duration_ms", "fault_apply_started", "fault_apply_completed"),
        "effect_observed_delay_ms": delta("effect_observed_delay_ms", "fault_apply_completed", "fault_effect_observed"),
        "cluster_impact_ms": delta("cluster_impact_ms", "cluster_impact_started", "cluster_recovered"),
        "failover_latency_ms": delta("failover_latency_ms", "failover_started", "cluster_recovered"),
        "promotion_latency_ms": delta("promotion_latency_ms", "failover_started", "promotion_observed"),
        "workload_recovery_ms": delta("workload_recovery_ms", "cluster_recovered", "workload_recovered"),
        "clear_duration_ms": delta("clear_duration_ms", "fault_clear_started", "fault_clear_completed"),
        "cleanup_duration_ms": delta("cleanup_duration_ms", "fault_clear_completed", "cleanup_verified"),
        "split_brain_window_ms": _window_metric(workload_windows, "split_brain_window_ms"),
        "cluster_down_window_ms": _window_metric(workload_windows, "cluster_down_window_ms"),
        "client_unavailability_ms": _window_metric(workload_windows, "client_unavailability_ms"),
    }
    if (
        isinstance(metrics["failover_latency_ms"], (int, float))
        and isinstance(metrics["cleanup_duration_ms"], (int, float))
        and metrics["failover_latency_ms"] == metrics["cleanup_duration_ms"]
        and by_name["cluster_recovered"].get("monotonic_ms") != by_name["cleanup_verified"].get("monotonic_ms")
    ):
        raise FailoverTimelineError("failover latency must not be substituted with cleanup duration")
    return metrics


def build_failover_latency_sample_from_timeline(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row.get("metrics", {})
    if not isinstance(metrics, dict):
        raise FailoverTimelineError("timeline row metrics must be an object")
    return {
        "schema_version": "v1",
        "capability_id": row.get("capability_id", "FAILOVER_TIMELINE_FAULT_TIMELINE"),
        "node_count": row.get("node_count", 0),
        "sample_id": row.get("sample_id", "MISSING"),
        "target_primary_logical_id": row.get("target_logical_id", row.get("subject_id", "MISSING")),
        "fault_injected_at_ms": row.get("event_timestamps", {}).get("fault_apply_completed", "MISSING"),
        "replica_promoted_at_ms": row.get("event_timestamps", {}).get("promotion_observed", "MISSING"),
        "slot_coverage_ok_at_ms": row.get("event_timestamps", {}).get("cluster_recovered", "MISSING"),
        "first_successful_read_at_ms": row.get("event_timestamps", {}).get("workload_recovered", "MISSING"),
        "first_successful_write_at_ms": row.get("event_timestamps", {}).get("workload_recovered", "MISSING"),
        "promotion_latency_ms": metrics.get("promotion_latency_ms", missing_metric("promotion latency was not derivable from timeline")),
        "cluster_recovery_latency_ms": metrics.get("failover_latency_ms", missing_metric("failover latency was not derivable from timeline")),
        "read_unavailability_ms": metrics.get("client_unavailability_ms", missing_metric("client read unavailability was not measured")),
        "write_unavailability_ms": metrics.get("client_unavailability_ms", missing_metric("client write unavailability was not measured")),
        "workload_impact_ref": row.get("workload_impact_ref", "fault_workload_impact.json"),
        "timeline_ref": row.get("timeline_ref", f"fault_timeline_events.jsonl#{row.get('sample_id', 'MISSING')}"),
        "fault_type": row.get("fault_type", "MISSING"),
        "fault_id": row.get("fault_id", "MISSING"),
        "source_event_start": "failover_started",
        "source_event_end": "cluster_recovered",
        "derived_from_timeline": True,
        "workload_recovery_ref": row.get("workload_recovery_ref", "workload_windows.json"),
    }


def build_fault_timeline_report(
    events: list[dict[str, Any]],
    *,
    capability_id: str,
    run_id: str,
    workload_windows: dict[str, Any] | None = None,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event.get("sample_id", "MISSING")), []).append(event)
    rows: list[dict[str, Any]] = []
    missing_metrics: list[dict[str, Any]] = []
    for sample_id, sample_events in sorted(grouped.items()):
        first = sample_events[0]
        metrics = derive_fault_timeline_metrics(sample_events, _window_for_sample(workload_windows, sample_id))
        for name, value in metrics.items():
            if isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON", "BLOCKED_WITH_REASON"}:
                missing_metrics.append({"sample_id": sample_id, "metric": name, **value})
        event_timestamps = {
            str(event.get("event_name")): event.get("timestamp_unix_ms")
            for event in sample_events
            if event.get("event_status") == "OBSERVED"
        }
        status = _row_status(sample_events, metrics)
        rows.append({
            "schema_version": "v1",
            "capability_id": capability_id,
            "run_id": run_id,
            "scenario_name": first.get("scenario_name", "MISSING"),
            "sample_id": sample_id,
            "fault_id": first.get("fault_id", "MISSING"),
            "fault_type": first.get("fault_type", "MISSING"),
            "node_count": first.get("node_count", "MISSING"),
            "scale_rung": str(first.get("scale_rung", "MISSING")),
            "status": status,
            "timeline_status": status if status in {"PASS", "FAIL", "SKIPPED_WITH_REASON", "BLOCKED_WITH_REASON"} else "MISSING",
            "real_valkey": bool(first.get("real_valkey") is True),
            "execution_mode": first.get("execution_mode", "MISSING"),
            "metrics": metrics,
            "metric_sources": {name: "fault_timeline_events.jsonl+workload_windows.json" for name in FULL_FLOW_TIMELINE_METRICS},
            "timeline_ref": f"fault_timeline_events.jsonl#{sample_id}",
            "timeline_event_refs": [f"fault_timeline_events.jsonl#{sample_id}:{event}" for event in FULL_FLOW_TIMELINE_EVENTS],
            "event_timestamps": event_timestamps,
            "workload_window_refs": _workload_refs(workload_windows, sample_id),
            "cleanup_ref": "cleanup_report.json",
            "valkey_e2e_evidence_ref": "valkey_e2e_evidence.json",
            "clean_cluster_evidence": {"status": "PASS" if status == "PASS" else status, "ref": "cleanup_report.json"},
            "host_network_mutation": False,
        })
    return {
        "schema_version": "v1",
        "artifact_type": "fault_timeline_report",
        "capability_id": capability_id,
        "run_id": run_id,
        "status": "PASS" if rows and all(row["status"] == "PASS" for row in rows) else "PARTIAL",
        "fault_rows": rows,
        "timeline_events_ref": "fault_timeline_events.jsonl",
        "failover_latency_samples_ref": "failover_latency_samples.jsonl",
        "fault_workload_impact_ref": "fault_workload_impact.json",
        "required_fault_types": FULL_FLOW_FAULT_TYPES,
        "observed_fault_types": sorted({str(row.get("fault_type")) for row in rows}),
        "required_scale_rungs": FULL_FLOW_SCALE_RUNGS,
        "observed_scale_rungs": sorted({str(row.get("scale_rung")) for row in rows}),
        "missing_metrics": missing_metrics,
    }


def _missing_delta(name: str, start: str, end: str, by_name: dict[str, dict[str, Any]]) -> dict[str, str]:
    missing = []
    for event_name in [start, end]:
        event = by_name.get(event_name, {})
        if event.get("event_status") != "OBSERVED":
            missing.append(f"{event_name}={event.get('event_status', 'MISSING')}: {event.get('reason', '')}".strip())
    return missing_metric(
        f"{name} cannot be derived because {'; '.join(missing) or 'required events are absent'}",
        impact=f"{name} is excluded from percentile aggregation.",
    )


def _window_metric(workload_windows: dict[str, Any] | None, metric: str) -> Any:
    if not isinstance(workload_windows, dict):
        return missing_metric(f"{metric} requires workload/fault window input", status="SKIPPED_WITH_REASON")
    metrics = workload_windows.get("fault_metrics", {})
    if isinstance(metrics, dict) and isinstance(metrics.get(metric), (int, float)):
        return round(float(metrics[metric]), 3)
    for window in workload_windows.get("windows", []):
        if isinstance(window, dict) and isinstance(window.get(metric), (int, float)):
            return round(float(window[metric]), 3)
        window_metrics = window.get("metrics", {}) if isinstance(window, dict) else {}
        if isinstance(window_metrics, dict) and isinstance(window_metrics.get(metric), (int, float)):
            return round(float(window_metrics[metric]), 3)
    return missing_metric(f"{metric} was not present in workload/fault windows")


def _window_for_sample(workload_windows: dict[str, Any] | None, sample_id: str) -> dict[str, Any] | None:
    if not isinstance(workload_windows, dict):
        return None
    rows = [row for row in workload_windows.get("windows", []) if isinstance(row, dict) and str(row.get("sample_id", sample_id)) == sample_id]
    if rows:
        copy = dict(workload_windows)
        copy["windows"] = rows
        return copy
    return workload_windows


def _workload_refs(workload_windows: dict[str, Any] | None, sample_id: str) -> list[str]:
    if not isinstance(workload_windows, dict):
        return [{"status": "SKIPPED_WITH_REASON", "reason": "workload_windows.json was not provided"}]  # type: ignore[list-item]
    refs = []
    for window in workload_windows.get("windows", []):
        if isinstance(window, dict) and str(window.get("sample_id", sample_id)) == sample_id:
            refs.append(f"workload_windows.json#{window.get('window_name', 'window')}")
    return refs or ["workload_windows.json"]


def _row_status(events: list[dict[str, Any]], metrics: dict[str, Any]) -> str:
    statuses = {str(event.get("event_status")) for event in events}
    if "FAIL" in statuses:
        return "FAIL"
    if "BLOCKED_WITH_REASON" in statuses:
        return "BLOCKED_WITH_REASON"
    if any(isinstance(value, dict) and value.get("status") == "MISSING" for value in metrics.values()):
        return "PARTIAL"
    if "SKIPPED_WITH_REASON" in statuses:
        return "SKIPPED_WITH_REASON"
    return "PASS"


@dataclass(frozen=True)
class ObserverEndpoint:
    logical_id: str
    host: str
    port: int
    password: str | None = None
    az_id: str | None = None
    role: str | None = None
    container_ip: str | None = None

    @classmethod
    def from_node(cls, node: dict[str, Any]) -> "ObserverEndpoint":
        return cls(
            logical_id=str(node.get("logical_id") or node.get("id") or f"{node.get('host')}:{node.get('client_port')}"),
            host=str(node.get("host") or node.get("ip") or "127.0.0.1"),
            port=int(node.get("client_port") or node.get("port")),
            password=node.get("password"),
            az_id=node.get("az_id"),
            role=node.get("role"),
            container_ip=node.get("container_ip"),
        )


def unix_ms() -> int:
    return int(time.time() * 1000)


def monotonic_ms() -> float:
    return round(time.monotonic() * 1000, 3)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        raise FailoverTimelineError("cannot compute percentile for empty values")
    ordered = sorted(float(v) for v in values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return round(ordered[index], 3)


def _require_number(row: dict[str, Any], field: str) -> float:
    value = row.get(field)
    if isinstance(value, (int, float)):
        return float(value)
    raise FailoverTimelineError(f"{field} must be numeric for a real FAILOVER_TIMELINE timeline sample")


def derive_rto_metrics(row: dict[str, Any]) -> dict[str, float]:
    timestamps = {field: _require_number(row, field) for field in REQUIRED_TIMESTAMPS}
    ordered_fields = [
        "fault_apply_at_ms",
        "target_process_gone_at_ms",
        "first_pfail_seen_at_ms",
        "first_fail_seen_at_ms",
        "first_promotion_seen_at_ms",
        "first_slots_covered_at_ms",
        "first_cluster_ok_at_ms",
        "first_client_success_at_ms",
        "clean_snapshot_passed_at_ms",
    ]
    for left, right in zip(ordered_fields, ordered_fields[1:]):
        if timestamps[left] > timestamps[right]:
            raise FailoverTimelineError(f"timestamps must be monotonic: {left} > {right}")
    metrics = {
        "kill_to_pfail_ms": timestamps["first_pfail_seen_at_ms"] - timestamps["fault_apply_at_ms"],
        "pfail_to_cluster_ok_ms": timestamps["first_cluster_ok_at_ms"] - timestamps["first_pfail_seen_at_ms"],
        "kill_to_client_recovered_ms": timestamps["first_client_success_at_ms"] - timestamps["fault_apply_at_ms"],
        "cluster_ok_to_client_success_ms": timestamps["first_client_success_at_ms"] - timestamps["first_cluster_ok_at_ms"],
        "cluster_ok_to_clean_snapshot_ms": timestamps["clean_snapshot_passed_at_ms"] - timestamps["first_cluster_ok_at_ms"],
        "kill_to_clean_snapshot_ms": timestamps["clean_snapshot_passed_at_ms"] - timestamps["fault_apply_at_ms"],
    }
    for name, value in metrics.items():
        if value < 0:
            raise FailoverTimelineError(f"{name} derived to negative duration")
    if (
        metrics["pfail_to_cluster_ok_ms"] == metrics["kill_to_clean_snapshot_ms"]
        and metrics["kill_to_pfail_ms"] + metrics["cluster_ok_to_clean_snapshot_ms"] > 0
    ):
        raise FailoverTimelineError("pfail_to_cluster_ok_ms must not be substituted with kill_to_clean_snapshot_ms")
    if metrics["pfail_to_cluster_ok_ms"] > metrics["kill_to_clean_snapshot_ms"]:
        raise FailoverTimelineError("pfail_to_cluster_ok_ms cannot include clean snapshot tail")
    return {name: round(value, 3) for name, value in metrics.items()}


def build_rto_summary(
    samples: list[dict[str, Any]],
    *,
    capability_id: str,
    run_id: str,
    timeout_config_ms: int,
    server_profile: str,
    nodehost_strategy: str,
    scale: str,
) -> dict[str, Any]:
    pass_samples = [sample for sample in samples if sample.get("status") == "PASS" and sample.get("real_valkey") is True]
    derived_series: dict[str, dict[str, float | int | str]] = {}
    for metric in [
        "kill_to_pfail_ms",
        "pfail_to_cluster_ok_ms",
        "kill_to_client_recovered_ms",
        "cluster_ok_to_clean_snapshot_ms",
        "kill_to_clean_snapshot_ms",
    ]:
        values = [float(sample[metric]) for sample in pass_samples if isinstance(sample.get(metric), (int, float))]
        derived_series[metric] = {
            "sample_count": len(values),
            "p50_ms": percentile(values, 0.50) if values else "MISSING",
            "p95_ms": percentile(values, 0.95) if values else "MISSING",
            "max_ms": round(max(values), 3) if values else "MISSING",
            "percentile_method": "nearest_rank_round_index",
        }
    node_counts = sorted({int(sample["node_count"]) for sample in pass_samples if isinstance(sample.get("node_count"), int)})
    return {
        "schema_version": "v1",
        "artifact_type": "failover_rto_summary",
        "capability_id": capability_id,
        "run_id": run_id,
        "status": "PASS" if pass_samples and len(pass_samples) == len(samples) else "FAIL",
        "sample_count": len(pass_samples),
        "sample_refs": [str(sample.get("sample_id")) for sample in pass_samples],
        "timeout_config_ms": timeout_config_ms,
        "server_profile": server_profile,
        "nodehost_strategy": nodehost_strategy,
        "node_count": node_counts[-1] if node_counts else "MISSING",
        "scale": scale,
        "observed_real_scales": node_counts,
        "derived_series": derived_series,
    }


def build_clean_gate_diagnostics(
    samples: list[dict[str, Any]],
    probe_rounds: list[dict[str, Any]],
    *,
    capability_id: str,
    run_id: str,
) -> dict[str, Any]:
    pass_samples = [sample for sample in samples if sample.get("status") == "PASS" and sample.get("real_valkey") is True]
    first_sample = pass_samples[0] if pass_samples else (samples[0] if samples else {})
    representative_rounds = [row for row in probe_rounds if row.get("sample_scope") == "representative"]
    all_node_rounds = [row for row in probe_rounds if row.get("sample_scope") == "all_nodes"]
    full_rounds = [row for row in probe_rounds if row.get("sample_scope") in {"all_nodes", "full"}]
    failed_rounds = [row for row in probe_rounds if row.get("status") != "PASS"]
    slowest = _slowest_probe_round(probe_rounds)
    first_rep_clean = _first_round_end(representative_rounds, status="PASS")
    first_all_clean = _first_round_end(all_node_rounds, status="PASS")
    clean_start = _first_round_start(probe_rounds)
    clean_end = first_all_clean if isinstance(first_all_clean, (int, float)) else _last_round_end(probe_rounds)
    clean_total = clean_end - clean_start if isinstance(clean_start, (int, float)) and isinstance(clean_end, (int, float)) else "MISSING"
    last_failed = _last_failing_reason(failed_rounds)
    return {
        "schema_version": "v1",
        "artifact_type": "clean_gate_diagnostics",
        "capability_id": capability_id,
        "run_id": run_id,
        "status": "PASS" if pass_samples and len(pass_samples) == len(samples) else "FAIL",
        "sample_count": len(samples),
        "sample_refs": [str(sample.get("sample_id")) for sample in samples],
        "first_cluster_ok_at_ms": first_sample.get("first_cluster_ok_at_ms", "MISSING"),
        "first_slots_covered_at_ms": first_sample.get("first_slots_covered_at_ms", "MISSING"),
        "first_representative_clean_at_ms": first_rep_clean,
        "first_all_nodes_clean_at_ms": first_all_clean,
        "clean_gate_total_ms": round(clean_total, 3) if isinstance(clean_total, (int, float)) else "MISSING",
        "probe_round_count": len(probe_rounds),
        "full_probe_count": len(full_rounds),
        "representative_probe_count": len(representative_rounds),
        "representative_probe_total_ms": _round_total_ms(representative_rounds),
        "all_nodes_probe_count": len(all_node_rounds),
        "all_nodes_probe_total_ms": _round_total_ms(all_node_rounds),
        "probe_timeout_count": sum(1 for row in probe_rounds if row.get("timed_out") is True or row.get("failed_reason") == "timeout"),
        "max_single_probe_ms": slowest.get("slowest_probe_ms", "MISSING"),
        "slowest_probe_node": slowest.get("slowest_node", "MISSING"),
        "slowest_probe_ms": slowest.get("slowest_probe_ms", "MISSING"),
        "first_client_success_at_ms": first_sample.get("first_client_success_at_ms", "MISSING"),
        "first_pfail_seen_at_ms": first_sample.get("first_pfail_seen_at_ms", "MISSING"),
        "first_fail_seen_at_ms": first_sample.get("first_fail_seen_at_ms", "MISSING"),
        "first_promotion_seen_at_ms": first_sample.get("first_promotion_seen_at_ms", "MISSING"),
        "last_failing_reason": last_failed if last_failed else ("MISSING" if failed_rounds else "not_applicable_clean_gate_passed_without_failed_round"),
        "source_artifacts": ["failover_timeline_samples.jsonl", "clean_gate_probe_rounds.jsonl"],
    }


def build_layered_recovery_summary(
    samples: list[dict[str, Any]],
    *,
    capability_id: str,
    run_id: str,
) -> dict[str, Any]:
    pass_samples = [sample for sample in samples if sample.get("status") == "PASS" and sample.get("real_valkey") is True]
    per_sample = []
    for sample in samples:
        durations = derive_rto_metrics(sample) if sample.get("status") == "PASS" else _missing_layered_durations()
        per_sample.append({
            "sample_id": sample.get("sample_id", "MISSING"),
            "node_count": sample.get("node_count", "MISSING"),
            **durations,
            "level_1": _level_ref("level_1", sample, "first_pfail_seen_at_ms", "first_cluster_ok_at_ms", "observer_samples_ref"),
            "level_2": _level_ref("level_2", sample, "fault_apply_at_ms", "first_client_success_at_ms", "client_recovery_samples_ref"),
            "level_3": _level_ref("level_3", sample, "first_cluster_ok_at_ms", "clean_snapshot_passed_at_ms", "clean_gate_probe_rounds_ref"),
            "clean_gate": {
                "source": LAYER_SOURCE_FIELDS["level_3"],
                "start_at_ms": sample.get("first_cluster_ok_at_ms", "MISSING"),
                "clean_snapshot_passed_at_ms": sample.get("clean_snapshot_passed_at_ms", "MISSING"),
                "probe_rounds_ref": sample.get("clean_gate_probe_rounds_ref", "clean_gate_probe_rounds.jsonl"),
            },
        })
    return {
        "schema_version": "v1",
        "artifact_type": "layered_recovery_summary",
        "capability_id": capability_id,
        "run_id": run_id,
        "status": "PASS" if pass_samples and len(pass_samples) == len(samples) else "FAIL",
        "sample_count": len(pass_samples),
        "sample_refs": [str(sample.get("sample_id")) for sample in pass_samples],
        "observed_real_scales": sorted({int(sample["node_count"]) for sample in pass_samples if isinstance(sample.get("node_count"), int)}),
        "per_sample": per_sample,
        **_summary_series(pass_samples),
        "level_1": {"source": LAYER_SOURCE_FIELDS["level_1"], "timestamp_fields": ["first_pfail_seen_at_ms", "first_cluster_ok_at_ms"]},
        "level_2": {"source": LAYER_SOURCE_FIELDS["level_2"], "timestamp_fields": ["fault_apply_at_ms", "first_client_success_at_ms"]},
        "level_3": {"source": LAYER_SOURCE_FIELDS["level_3"], "timestamp_fields": ["first_cluster_ok_at_ms", "clean_snapshot_passed_at_ms"]},
        "clean_gate": {"source": LAYER_SOURCE_FIELDS["level_3"], "final_all_node_clean_required": True},
    }


def build_recovery_endpoint_summary(
    samples: list[dict[str, Any]],
    *,
    capability_id: str,
    run_id: str,
) -> dict[str, Any]:
    endpoints = []
    for sample in samples:
        endpoints.append({
            "sample_id": sample.get("sample_id", "MISSING"),
            "node_count": sample.get("node_count", "MISSING"),
            "level_1": _level_ref("level_1", sample, "first_pfail_seen_at_ms", "first_cluster_ok_at_ms", "observer_samples_ref"),
            "level_2": _level_ref("level_2", sample, "fault_apply_at_ms", "first_client_success_at_ms", "client_recovery_samples_ref"),
            "level_3": _level_ref("level_3", sample, "first_cluster_ok_at_ms", "clean_snapshot_passed_at_ms", "clean_gate_probe_rounds_ref"),
            "timeline_sample_ref": f"failover_timeline_samples.jsonl#{sample.get('sample_id', 'MISSING')}",
        })
    return {
        "schema_version": "v1",
        "artifact_type": "recovery_endpoint_summary",
        "capability_id": capability_id,
        "run_id": run_id,
        "status": "PASS" if samples and all(sample.get("status") == "PASS" for sample in samples) else "FAIL",
        "endpoints": endpoints,
        "source_artifacts": ["failover_timeline_samples.jsonl", "observer_samples.jsonl", "client_recovery_samples.jsonl", "clean_gate_probe_rounds.jsonl"],
    }


def _missing_layered_durations() -> dict[str, str]:
    return {field: "MISSING" for field in RTO_METRIC_FIELDS}


def _summary_series(samples: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in RTO_METRIC_FIELDS:
        values = [float(sample[field]) for sample in samples if isinstance(sample.get(field), (int, float))]
        out[field] = {
            "sample_count": len(values),
            "p50_ms": percentile(values, 0.50) if values else "MISSING",
            "p95_ms": percentile(values, 0.95) if values else "MISSING",
            "max_ms": round(max(values), 3) if values else "MISSING",
            "percentile_method": "nearest_rank_round_index",
        }
    return out


def _level_ref(level: str, sample: dict[str, Any], start_field: str, end_field: str, ref_field: str) -> dict[str, Any]:
    return {
        "source": LAYER_SOURCE_FIELDS[level],
        "start_field": start_field,
        "end_field": end_field,
        "start_at_ms": sample.get(start_field, "MISSING"),
        "end_at_ms": sample.get(end_field, "MISSING"),
        "source_ref": sample.get(ref_field, "MISSING"),
    }


def _round_total_ms(rounds: list[dict[str, Any]]) -> float:
    return round(sum(float(row.get("probe_duration_ms", 0) or 0) for row in rounds), 3)


def _first_round_start(rounds: list[dict[str, Any]]) -> Any:
    values = [row.get("probe_start_ms") for row in rounds if isinstance(row.get("probe_start_ms"), (int, float))]
    return min(values) if values else "MISSING"


def _first_round_end(rounds: list[dict[str, Any]], *, status: str) -> Any:
    values = [row.get("probe_end_ms") for row in rounds if row.get("status") == status and isinstance(row.get("probe_end_ms"), (int, float))]
    return min(values) if values else "MISSING"


def _last_round_end(rounds: list[dict[str, Any]]) -> Any:
    values = [row.get("probe_end_ms") for row in rounds if isinstance(row.get("probe_end_ms"), (int, float))]
    return max(values) if values else "MISSING"


def _last_failing_reason(rounds: list[dict[str, Any]]) -> str:
    for row in reversed(rounds):
        reason = row.get("failed_reason")
        if isinstance(reason, str) and reason:
            return reason
    return ""


def _slowest_probe_round(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [row for row in rounds if isinstance(row.get("slowest_probe_ms"), (int, float))]
    if not candidates:
        return {}
    return max(candidates, key=lambda row: float(row.get("slowest_probe_ms", 0) or 0))


class RespError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _encode_command(*args: Any) -> bytes:
    parts = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        blob = arg if isinstance(arg, bytes) else str(arg).encode("utf-8")
        parts.append(f"${len(blob)}\r\n".encode())
        parts.append(blob + b"\r\n")
    return b"".join(parts)


class _RespConnection:
    def __init__(self, endpoint: ObserverEndpoint, timeout_seconds: float):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def execute(self, *args: Any) -> Any:
        with socket.create_connection((self.endpoint.host, self.endpoint.port), timeout=self.timeout_seconds) as sock:
            sock.settimeout(self.timeout_seconds)
            fp = sock.makefile("rb")
            if self.endpoint.password:
                sock.sendall(_encode_command("AUTH", self.endpoint.password))
                _read_resp(fp)
            sock.sendall(_encode_command(*args))
            return _read_resp(fp)

    def execute_pipeline(self, commands: list[tuple[Any, ...]]) -> list[Any]:
        with socket.create_connection((self.endpoint.host, self.endpoint.port), timeout=self.timeout_seconds) as sock:
            sock.settimeout(self.timeout_seconds)
            fp = sock.makefile("rb")
            if self.endpoint.password:
                sock.sendall(_encode_command("AUTH", self.endpoint.password))
                _read_resp(fp)
            sock.sendall(b"".join(_encode_command(*command) for command in commands))
            return [_read_resp(fp) for _ in commands]


def _read_line(fp: Any) -> bytes:
    line = fp.readline()
    if not line or not line.endswith(b"\r\n"):
        raise OSError("invalid RESP line")
    return line[:-2]


def _read_resp(fp: Any) -> Any:
    prefix = fp.read(1)
    if prefix == b"+":
        return _read_line(fp).decode("utf-8", errors="replace")
    if prefix == b"-":
        raise RespError(_read_line(fp).decode("utf-8", errors="replace"))
    if prefix == b":":
        return int(_read_line(fp))
    if prefix == b"$":
        n = int(_read_line(fp))
        if n == -1:
            return None
        data = fp.read(n)
        if fp.read(2) != b"\r\n":
            raise OSError("bulk string missing CRLF")
        return data.decode("utf-8", errors="replace")
    if prefix == b"*":
        n = int(_read_line(fp))
        if n == -1:
            return None
        return [_read_resp(fp) for _ in range(n)]
    raise OSError(f"unknown RESP prefix {prefix!r}")


def parse_info(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key] = value
    return out


def parse_cluster_nodes(text: str) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 8:
            continue
        flags = set(parts[2].split(","))
        role = "primary" if "master" in flags else "replica" if flags.intersection({"slave", "replica"}) else "unknown"
        nodes[parts[0]] = {
            "node_id": parts[0],
            "addr": parts[1],
            "flags": sorted(flags),
            "role": role,
            "master_id": None if parts[3] == "-" else parts[3],
            "link_state": parts[7],
            "slots": parts[8:],
        }
    return nodes


def moved_target(message: str) -> tuple[str, int] | None:
    parts = message.split()
    if len(parts) >= 3 and parts[0] in {"MOVED", "ASK"} and ":" in parts[2]:
        host, port_s = parts[2].rsplit(":", 1)
        try:
            return host, int(port_s)
        except ValueError:
            return None
    return None


class ClientRecoveryAccumulator:
    def __init__(self, sample_id: str, fault_apply_at_ms: int, probe_interval_ms: int):
        self.sample_id = sample_id
        self.fault_apply_at_ms = fault_apply_at_ms
        self.probe_interval_ms = probe_interval_ms
        self.samples: list[dict[str, Any]] = []

    def record(self, row: dict[str, Any]) -> None:
        self.samples.append(row)

    def first_success_at_or_after(self, timestamp_unix_ms: int) -> int | None:
        for row in self.samples:
            timestamp = row.get("timestamp_unix_ms")
            if row.get("status") == "PASS" and isinstance(timestamp, int) and timestamp >= timestamp_unix_ms:
                return timestamp
        return None

    def summary(self) -> dict[str, Any]:
        first_success = None
        saw_failure_after_fault = False
        errors = 0
        timeouts = 0
        moved = 0
        ask = 0
        for row in self.samples:
            timestamp = row.get("timestamp_unix_ms")
            after_fault = isinstance(timestamp, int) and timestamp >= self.fault_apply_at_ms
            if row.get("status") == "PASS" and after_fault and saw_failure_after_fault and first_success is None:
                first_success = timestamp
                break
            if after_fault:
                if row.get("status") != "PASS":
                    saw_failure_after_fault = True
                    errors += 1
                    timeouts += 1 if row.get("timeout") is True else 0
                    moved += int(row.get("moved_count", 0) or 0)
                    ask += int(row.get("ask_count", 0) or 0)
        return {
            "client_probe_interval_ms": self.probe_interval_ms,
            "first_success_after_fault_ms": first_success if first_success is not None else "MISSING",
            "error_count_before_recovery": errors,
            "timeout_count_before_recovery": timeouts,
            "moved_count": moved,
            "ask_count": ask,
            "sample_count": len(self.samples),
        }


class FailoverTimelineObserver:
    def __init__(
        self,
        *,
        capability_id: str,
        run_id: str,
        scenario_name: str,
        sample_id: str,
        node_count: int,
        endpoints: list[ObserverEndpoint],
        target_primary_logical_id: str,
        target_primary_node_id: str,
        expected_replica_node_id: str,
        probe_interval_ms: int = 250,
        timeout_seconds: float = 1.0,
        max_observer_endpoints: int = 32,
    ) -> None:
        self.capability_id = capability_id
        self.run_id = run_id
        self.scenario_name = scenario_name
        self.sample_id = sample_id
        self.node_count = node_count
        self.endpoints = endpoints
        self.target_primary_logical_id = target_primary_logical_id
        self.target_primary_node_id = target_primary_node_id
        self.expected_replica_node_id = expected_replica_node_id
        self.probe_interval_ms = probe_interval_ms
        self.timeout_seconds = timeout_seconds
        self._sample_endpoints = self._select_endpoints(max_observer_endpoints)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples: list[dict[str, Any]] = []
        self.markers: dict[str, int] = {}

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("observer already started")
        self._thread = threading.Thread(target=self._run, name=f"failover_timeline-observer-{self.sample_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.probe_interval_ms / 1000.0 * 4))

    def sample_once(self) -> dict[str, Any]:
        timestamp = unix_ms()
        probes = self._probe_endpoints()
        aggregate = _aggregate_probes(
            probes,
            self.target_primary_logical_id,
            self.target_primary_node_id,
            self.expected_replica_node_id,
        )
        row = {
            "schema_version": "v1",
            "capability_id": self.capability_id,
            "run_id": self.run_id,
            "scenario_name": self.scenario_name,
            "sample_id": self.sample_id,
            "timestamp_unix_ms": timestamp,
            "monotonic_ms": monotonic_ms(),
            "node_count": self.node_count,
            "observer_endpoint_count": len(self._sample_endpoints),
            **aggregate,
        }
        self._update_markers(row)
        self.samples.append(row)
        return row

    def _run(self) -> None:
        while not self._stop.is_set():
            self.sample_once()
            self._stop.wait(self.probe_interval_ms / 1000.0)

    def _select_endpoints(self, max_count: int) -> list[ObserverEndpoint]:
        selected: list[ObserverEndpoint] = []
        seen: set[str] = set()
        for endpoint in self.endpoints:
            if endpoint.logical_id == self.target_primary_logical_id:
                selected.append(endpoint)
                seen.add(endpoint.logical_id)
                break
        for endpoint in self.endpoints:
            if endpoint.logical_id not in seen and len(selected) < max_count:
                selected.append(endpoint)
                seen.add(endpoint.logical_id)
        return selected

    def _probe_endpoints(self) -> list[dict[str, Any]]:
        if not self._sample_endpoints:
            return []
        results: list[dict[str, Any] | None] = [None] * len(self._sample_endpoints)
        max_workers = min(16, len(self._sample_endpoints))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_probe_endpoint, endpoint, self.timeout_seconds): idx for idx, endpoint in enumerate(self._sample_endpoints)}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:  # noqa: BLE001
                    endpoint = self._sample_endpoints[idx]
                    results[idx] = {"logical_id": endpoint.logical_id, "status": "FAIL", "error": repr(exc)}
        return [item for item in results if item is not None]

    def _update_markers(self, row: dict[str, Any]) -> None:
        ts = row["timestamp_unix_ms"]
        if row.get("target_reachable") is False:
            self.markers.setdefault("target_process_gone_at_ms", ts)
        if int(row.get("pfail_count", 0) or 0) > 0:
            self.markers.setdefault("first_pfail_seen_at_ms", ts)
        if int(row.get("fail_count", 0) or 0) > 0:
            self.markers.setdefault("first_fail_seen_at_ms", ts)
        if row.get("expected_replica_promoted") is True:
            self.markers.setdefault("first_promotion_seen_at_ms", ts)
        if (
            row.get("expected_replica_promoted") is True
            and int(row.get("cluster_slots_assigned", 0) or 0) == 16384
            and int(row.get("cluster_slots_ok", 0) or 0) == 16384
        ):
            self.markers.setdefault("first_slots_covered_at_ms", ts)
        if (
            row.get("expected_replica_promoted") is True
            and int(row.get("cluster_slots_assigned", 0) or 0) == 16384
            and int(row.get("cluster_slots_ok", 0) or 0) == 16384
            and row.get("cluster_state") == "ok"
        ):
            self.markers.setdefault("first_cluster_ok_at_ms", ts)


def _probe_endpoint(endpoint: ObserverEndpoint, timeout_seconds: float) -> dict[str, Any]:
    result: dict[str, Any] = {"logical_id": endpoint.logical_id, "status": "FAIL"}
    try:
        conn = _RespConnection(endpoint, timeout_seconds)
        ping, cluster_info_raw, cluster_nodes_raw = conn.execute_pipeline([("PING",), ("CLUSTER", "INFO"), ("CLUSTER", "NODES")])
        info = parse_info(str(cluster_info_raw))
        result.update(
            {
                "status": "PASS",
                "ping": ping,
                "cluster_state": info.get("cluster_state", "unknown"),
                "cluster_slots_assigned": _as_int(info.get("cluster_slots_assigned")),
                "cluster_slots_ok": _as_int(info.get("cluster_slots_ok")),
                "cluster_known_nodes": _as_int(info.get("cluster_known_nodes")),
                "cluster_nodes": parse_cluster_nodes(str(cluster_nodes_raw)),
            }
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
    return result


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _aggregate_probes(
    probes: list[dict[str, Any]],
    target_primary_logical_id: str,
    target_primary_node_id: str,
    expected_replica_node_id: str,
) -> dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}
    pass_probes = [probe for probe in probes if probe.get("status") == "PASS"]
    pfail_count = 0
    fail_count = 0
    handshake_count = 0
    target_reachable = any(
        probe.get("logical_id") == target_primary_logical_id and probe.get("status") == "PASS"
        for probe in probes
    )
    expected_replica_promoted = False
    cluster_state = "unknown"
    slots_assigned = 0
    slots_ok = 0
    for probe in pass_probes:
        if probe.get("cluster_state") == "ok":
            cluster_state = "ok"
        slots_assigned = max(slots_assigned, int(probe.get("cluster_slots_assigned", 0) or 0))
        slots_ok = max(slots_ok, int(probe.get("cluster_slots_ok", 0) or 0))
        merged.update(probe.get("cluster_nodes") or {})
    for node_id, node in merged.items():
        flags = set(node.get("flags") or [])
        if flags.intersection({"pfail", "fail?"}):
            pfail_count += 1
        if "fail" in flags:
            fail_count += 1
        if "handshake" in flags:
            handshake_count += 1
        if node_id == expected_replica_node_id and node.get("role") == "primary":
            expected_replica_promoted = True
    return {
        "status": "PASS" if pass_probes else "FAIL",
        "probe_status_counts": {"PASS": len(pass_probes), "FAIL": len(probes) - len(pass_probes)},
        "cluster_state": cluster_state,
        "cluster_slots_assigned": slots_assigned,
        "cluster_slots_ok": slots_ok,
        "pfail_count": pfail_count,
        "fail_count": fail_count,
        "handshake_count": handshake_count,
        "target_reachable": target_reachable,
        "expected_replica_promoted": expected_replica_promoted,
        "observed_node_count": len(merged),
        "role_changes": {
            expected_replica_node_id: "primary" if expected_replica_promoted else "not_primary_observed",
        },
    }
