from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional


LIFECYCLE_HANDLER_IDS = tuple(
    f"product.{step_id}"
    for step_id in (
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
    )
)

SCENARIO_HANDLER_IDS = (
    "product.management_operation",
    "product.bounded_stability",
    "product.primary_failover",
    "product.process_pause",
    "product.nodehost_pause",
    "product.az_pause",
    "product.proxy",
    "product.network_disconnect",
)

HANDLER_REGISTRY: Mapping[str, str] = MappingProxyType(
    {
        **{handler_id: "lifecycle" for handler_id in LIFECYCLE_HANDLER_IDS},
        **{
            "product.management_operation": "management",
            "product.bounded_stability": "management",
            "product.primary_failover": "fault",
            "product.process_pause": "fault",
            "product.nodehost_pause": "fault",
            "product.az_pause": "fault",
            "product.proxy": "fault",
            "product.network_disconnect": "fault",
        },
    }
)


def _run_state_to_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    return {"nodes": value.get("nodes")}


def _normalize_timestamp(value: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(value)
    if not isinstance(item.get("timestamp_unix_ms"), int):
        ended = item.get("ended_at_unix_ms")
        if not isinstance(ended, int):
            raise ValueError(
                "normalize_timestamp requires integer timestamp_unix_ms or ended_at_unix_ms"
            )
        item["timestamp_unix_ms"] = ended
    return item


def _recovery_health(value: Mapping[str, Any]) -> dict[str, Any]:
    return {"recovery_health": value.get("recovery_health")}


TRANSFORM_REGISTRY: Mapping[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = (
    MappingProxyType(
        {
            "run_state_to_metadata": _run_state_to_metadata,
            "normalize_timestamp": _normalize_timestamp,
            "recovery_health": _recovery_health,
        }
    )
)


@dataclass(frozen=True)
class TransformCompatibility:
    source_raw_name: str
    source_format: str
    admitted_kind: str
    source_selector: Optional[str] = None


@dataclass(frozen=True)
class AdmissionCompatibility:
    admitted_kind: str
    source_raw_name: str
    source_format: str
    transform_id: Optional[str] = None
    source_selector: Optional[str] = None


ADMISSION_COMPATIBILITY: Mapping[str, AdmissionCompatibility] = MappingProxyType(
    {
        "run_metadata": AdmissionCompatibility(
            admitted_kind="run_metadata",
            source_raw_name="run_state.json",
            source_format="json",
            transform_id="run_state_to_metadata",
        ),
        "resource_preflight": AdmissionCompatibility(
            admitted_kind="resource_preflight",
            source_raw_name="resource_preflight.json",
            source_format="json",
        ),
        "workload_windows": AdmissionCompatibility(
            admitted_kind="workload_windows",
            source_raw_name="workload_windows.json",
            source_format="json",
        ),
        "lifecycle_timeline": AdmissionCompatibility(
            admitted_kind="lifecycle_timeline",
            source_raw_name="lifecycle_timeline.json",
            source_format="json",
        ),
        "scenario_results": AdmissionCompatibility(
            admitted_kind="scenario_results",
            source_raw_name="scenario_results.json",
            source_format="json",
        ),
        "management_results": AdmissionCompatibility(
            admitted_kind="management_results",
            source_raw_name="management_sequence.json",
            source_format="json",
        ),
        "fault_results": AdmissionCompatibility(
            admitted_kind="fault_results",
            source_raw_name="fault_sequence.json",
            source_format="json",
        ),
        "stability_results": AdmissionCompatibility(
            admitted_kind="stability_results",
            source_raw_name="fault_sequence.json",
            source_format="json",
            transform_id="recovery_health",
            source_selector="recovery_health",
        ),
        "cleanup_report": AdmissionCompatibility(
            admitted_kind="cleanup_report",
            source_raw_name="cleanup_report.json",
            source_format="json",
        ),
        "analysis_summary": AdmissionCompatibility(
            admitted_kind="analysis_summary",
            source_raw_name="analysis_summary.json",
            source_format="json",
        ),
        "report_index": AdmissionCompatibility(
            admitted_kind="report_index",
            source_raw_name="report_index.json",
            source_format="json",
        ),
        "command_log": AdmissionCompatibility(
            admitted_kind="command_log",
            source_raw_name="management_command_log.jsonl",
            source_format="jsonl",
            transform_id="normalize_timestamp",
        ),
        "fault_command_log": AdmissionCompatibility(
            admitted_kind="fault_command_log",
            source_raw_name="fault_command_log.jsonl",
            source_format="jsonl",
            transform_id="normalize_timestamp",
        ),
        "events": AdmissionCompatibility(
            admitted_kind="events",
            source_raw_name="events.jsonl",
            source_format="jsonl",
        ),
        "metrics": AdmissionCompatibility(
            admitted_kind="metrics",
            source_raw_name="metrics_timeseries.jsonl",
            source_format="jsonl",
        ),
    }
)


TRANSFORM_COMPATIBILITY: Mapping[str, tuple[TransformCompatibility, ...]] = (
    MappingProxyType(
        {
            transform_id: tuple(
                TransformCompatibility(
                    source_raw_name=rule.source_raw_name,
                    source_format=rule.source_format,
                    admitted_kind=rule.admitted_kind,
                    source_selector=rule.source_selector,
                )
                for rule in ADMISSION_COMPATIBILITY.values()
                if rule.transform_id == transform_id
            )
            for transform_id in TRANSFORM_REGISTRY
        }
    )
)


def expected_admission_compatibility(
    admitted_kind: str,
) -> AdmissionCompatibility | None:
    return ADMISSION_COMPATIBILITY.get(admitted_kind)


def expected_transform_compatibility(
    *,
    source_raw_name: str,
    source_format: str,
    admitted_kind: str,
) -> tuple[str, TransformCompatibility] | None:
    for transform_id, rules in TRANSFORM_COMPATIBILITY.items():
        for rule in rules:
            if (
                rule.source_raw_name == source_raw_name
                and rule.source_format == source_format
                and rule.admitted_kind == admitted_kind
            ):
                return transform_id, rule
    return None


def apply_transform(transform_id: str, value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        transform = TRANSFORM_REGISTRY[transform_id]
    except KeyError as exc:
        raise ValueError(f"unknown closed transform id: {transform_id}") from exc
    return transform(value)
