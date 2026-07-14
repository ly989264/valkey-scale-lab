from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from valkey_scale_lab import __version__

SETUP_TIMELINE_ARTIFACT_TYPE = "p13_setup_exhaustive_timeline"
SETUP_TELEMETRY_ARTIFACT_TYPE = "setup_telemetry"
SETUP_TIMELINE_OPTIMIZATION_PHASE = "P13O-07_SETUP_EXHAUSTIVE_TIMELINE"
SETUP_TIMELINE_UNEXPLAINED_LIMIT_SECONDS = 2.0

REQUIRED_SETUP_SEGMENTS = [
    "setup_entry",
    "config_parse_and_validate",
    "node_spec_generation",
    "port_preflight_check",
    "pre_cleanup_by_label",
    "docker_network_create",
    "nodehost_plan",
    "nodehost_start",
    "node_config_local_generate",
    "nodehost_bundle_write",
    "docker_cp_bundle",
    "nodehost_bundle_install",
    "nodehost_start_all",
    "pidfile_collect",
    "process_ready_wait",
    "state_write_before_cluster",
    "primary_cluster_create",
    "replica_meet",
    "replica_replicate",
    "cluster_convergence_wait",
    "cluster_final_snapshot",
    "cluster_snapshot_write",
    "runtime_timing_write",
    "state_write_after_cluster",
    "scale_ladder_artifact_write",
    "state_write_setup_timeline_reference",
    "setup_return",
]

REQUIRED_SETUP_GROUPS = [
    "process_config_prepare",
    "process_start",
    "cluster_formation",
]

REQUIRED_SETUP_TELEMETRY_METRICS = [
    "config_parse_ms",
    "config_validate_ms",
    "resource_preflight_ms",
    "plan_build_ms",
    "port_check_ms",
    "nodehost_start_ms",
    "node_config_generate_ms",
    "node_config_distribute_ms",
    "process_start_ms",
    "process_ready_wait_ms",
    "cluster_meet_ms",
    "cluster_slots_assign_ms",
    "replica_replicate_ms",
    "cluster_convergence_probe_ms",
    "full_cluster_probe_ms",
    "cleanup_ms",
    "total_setup_ms",
]

RUNTIME_ONLY_REASON = {
    "status": "SKIPPED_WITH_REASON",
    "reason": "This metric is only available after a live local setup reaches the corresponding runtime step.",
}

DEFAULT_SETUP_GROUPS = [
    {
        "name": "process_config_prepare",
        "category": "process_config_prepare",
        "children": [
            "node_config_local_generate",
            "nodehost_bundle_write",
            "docker_cp_bundle",
            "nodehost_bundle_install",
        ],
    },
    {
        "name": "process_start",
        "category": "process_start",
        "children": [
            "nodehost_start_all",
            "pidfile_collect",
        ],
    },
    {
        "name": "cluster_formation",
        "category": "cluster_formation",
        "children": [
            "primary_cluster_create",
            "replica_meet",
            "replica_replicate",
            "cluster_convergence_wait",
            "cluster_final_snapshot",
            "cluster_final_full_snapshot",
        ],
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _round_seconds(value: float) -> float:
    return round(max(float(value), 0.0), 6)


def _ms(seconds: float | int) -> float:
    return round(max(float(seconds), 0.0) * 1000.0, 3)


def _missing(reason: str, impact: str) -> dict[str, str]:
    return {"status": "MISSING", "reason": reason, "impact": impact}


def _skipped(reason: str) -> dict[str, str]:
    return {"status": "SKIPPED_WITH_REASON", "reason": reason}


class SetupTimeline:
    """Sequential, leaf-only setup timeline recorder.

    Parent phases are represented in the artifact hierarchy. They are not added
    to the segment list, so total duration is the sum of non-overlapping leaf
    spans and explicit gaps only.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        gap_threshold_seconds: float = 0.001,
    ) -> None:
        self._clock = clock or time.monotonic
        self._gap_threshold_seconds = max(float(gap_threshold_seconds), 0.0)
        self._origin = float(self._clock())
        self._last_end = self._origin
        self._segments: list[dict[str, Any]] = []
        self._active = False

    @property
    def segments(self) -> list[dict[str, Any]]:
        return [dict(segment) for segment in self._segments]

    @contextmanager
    def span(
        self,
        name: str,
        category: str,
        details: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        if self._active:
            raise RuntimeError(f"setup timeline span {name!r} would overlap an active span")
        start = float(self._clock())
        self._append_gap_if_needed(start, next_name=name)
        self._active = True
        status = "PASS"
        error: str | None = None
        try:
            yield
        except Exception as exc:  # noqa: BLE001 - failed setup spans must be captured
            status = "FAIL"
            error = repr(exc)
            raise
        finally:
            end = float(self._clock())
            self._active = False
            segment_details = dict(details or {})
            if error:
                segment_details["error"] = error
            self._append_segment(
                name=name,
                category=category,
                kind="span",
                start=start,
                end=end,
                status=status,
                details=segment_details,
            )

    def mark_gap(
        self,
        name: str,
        *,
        start_monotonic: float,
        end_monotonic: float,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._append_segment(
            name=name,
            category="gap",
            kind="gap",
            start=float(start_monotonic),
            end=float(end_monotonic),
            status="PASS",
            details=details or {"reason": "explicitly recorded setup timeline gap"},
        )

    def _append_gap_if_needed(self, start: float, *, next_name: str) -> None:
        if start < self._last_end - 1e-9:
            raise RuntimeError(f"setup timeline overlap before {next_name}: {start} < {self._last_end}")
        gap = start - self._last_end
        if gap >= self._gap_threshold_seconds:
            previous = self._segments[-1]["name"] if self._segments else "timeline_origin"
            self._append_segment(
                name=f"gap_after_{previous}_before_{next_name}",
                category="gap",
                kind="gap",
                start=self._last_end,
                end=start,
                status="PASS",
                details={
                    "reason": "elapsed setup time between adjacent recorded stages",
                    "previous_segment": previous,
                    "next_segment": next_name,
                },
            )

    def _append_segment(
        self,
        *,
        name: str,
        category: str,
        kind: str,
        start: float,
        end: float,
        status: str,
        details: dict[str, Any],
    ) -> None:
        if end < start:
            raise RuntimeError(f"setup timeline segment {name!r} ends before it starts")
        if self._segments and start < self._last_end - 1e-9:
            raise RuntimeError(f"setup timeline segment {name!r} overlaps previous segment")
        segment = {
            "id": f"segment_{len(self._segments) + 1:03d}",
            "name": str(name),
            "kind": str(kind),
            "category": str(category),
            "start_monotonic": round(float(start), 6),
            "end_monotonic": round(float(end), 6),
            "duration_seconds": _round_seconds(end - start),
            "status": str(status),
            "details": details,
        }
        self._segments.append(segment)
        self._last_end = end

    def to_artifact(
        self,
        *,
        phase_id: str,
        run_id: str,
        scenario: str,
        node_count: int,
        status: str,
        setup_command_wall_seconds: float | None = None,
        real_valkey_evidence_summary: dict[str, Any] | None = None,
        source_artifacts: list[dict[str, Any]] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        segments = self.segments
        return build_setup_timeline_artifact(
            phase_id=phase_id,
            run_id=run_id,
            scenario=scenario,
            node_count=node_count,
            status=status,
            segments=segments,
            setup_command_wall_seconds=setup_command_wall_seconds,
            real_valkey_evidence_summary=real_valkey_evidence_summary,
            source_artifacts=source_artifacts,
            extra=extra,
        )

    def write_artifact(self, path: str | Path, **kwargs: Any) -> dict[str, Any]:
        artifact = self.to_artifact(**kwargs)
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return artifact


def build_setup_timeline_artifact(
    *,
    phase_id: str,
    run_id: str,
    scenario: str,
    node_count: int,
    status: str,
    segments: list[dict[str, Any]],
    setup_command_wall_seconds: float | None = None,
    real_valkey_evidence_summary: dict[str, Any] | None = None,
    source_artifacts: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_segments = _normalize_segments(segments)
    total = _round_seconds(sum(float(segment["duration_seconds"]) for segment in normalized_segments))
    wall = round(float(setup_command_wall_seconds), 6) if setup_command_wall_seconds is not None else None
    unexplained = None if wall is None else round(abs(wall - total), 6)
    unexplained_status = (
        "MISSING"
        if unexplained is None
        else ("PASS" if unexplained <= SETUP_TIMELINE_UNEXPLAINED_LIMIT_SECONDS else "FAIL")
    )
    hierarchy = build_phase_hierarchy(normalized_segments)
    coverage = setup_timeline_coverage(normalized_segments, hierarchy)
    errors = validate_setup_timeline_artifact_data(
        {
            "segments": normalized_segments,
            "phase_hierarchy": hierarchy,
            "setup_command_wall_seconds": wall,
            "setup_timeline_total_seconds": total,
            "setup_timeline_unexplained_seconds": unexplained,
            "setup_timeline_unexplained_status": unexplained_status,
        },
        require_wall=wall is not None,
    )
    artifact_status = "PASS" if status == "PASS" and not errors else "FAIL"
    summary = {
        "setup_command_wall_seconds": wall if wall is not None else "MISSING",
        "setup_timeline_total_seconds": total,
        "setup_timeline_unexplained_seconds": unexplained if unexplained is not None else "MISSING",
        "setup_timeline_unexplained_status": unexplained_status,
        "largest_segments": largest_segments(normalized_segments),
        "largest_gaps": largest_gaps(normalized_segments),
    }
    artifact = {
        "schema_version": "v1",
        "artifact_type": SETUP_TIMELINE_ARTIFACT_TYPE,
        "phase_id": phase_id,
        "optimization_phase_id": SETUP_TIMELINE_OPTIMIZATION_PHASE,
        "run_id": run_id,
        "scenario": scenario,
        "created_at": utc_now(),
        "producer": {"name": "valkey-scale-lab-runtime", "version": __version__},
        "status": artifact_status,
        "node_count": int(node_count),
        "setup_command_wall_seconds": summary["setup_command_wall_seconds"],
        "setup_timeline_total_seconds": total,
        "setup_timeline_unexplained_seconds": summary["setup_timeline_unexplained_seconds"],
        "setup_timeline_unexplained_status": unexplained_status,
        "setup_timeline_unexplained_explanation": unexplained_explanation(wall, total, unexplained),
        "segments": normalized_segments,
        "phase_hierarchy": hierarchy,
        "required_phase_coverage": coverage,
        "largest_segments": summary["largest_segments"],
        "largest_gaps": summary["largest_gaps"],
        "real_valkey_evidence_summary": real_valkey_evidence_summary
        or {
            "status": "MISSING",
            "reason": "real Valkey evidence is added by the P13O validator after wrapper probes complete",
        },
        "source_artifacts": source_artifacts or [],
        "summary": summary,
        "errors": errors,
    }
    if extra:
        artifact.update(extra)
    return artifact


def build_setup_telemetry_artifact(
    *,
    phase_id: str,
    run_id: str,
    scenario: str,
    status: str,
    node_count: int,
    segments: list[dict[str, Any]] | None = None,
    runtime_timings: list[dict[str, Any]] | None = None,
    nodes: list[dict[str, Any]] | None = None,
    nodehosts: list[dict[str, Any]] | None = None,
    cleanup_report: dict[str, Any] | None = None,
    source_artifacts: list[dict[str, Any]] | None = None,
    blocked_reason: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the common setup telemetry artifact from runtime evidence."""
    normalized_segments = _normalize_segments(segments or []) if segments else []
    timings_by_name = {
        str(item.get("name")): dict(item)
        for item in (runtime_timings or [])
        if isinstance(item, dict) and item.get("name")
    }
    segment_ms = _segment_duration_ms(normalized_segments)
    metric_values = {
        "config_parse_ms": _segment_detail_ms(normalized_segments, "config_parse_and_validate", "config_parse_ms")
        or _missing("config_parse_and_validate span did not include parser timing detail.", "Cannot independently rank parser cost."),
        "config_validate_ms": _segment_detail_ms(normalized_segments, "config_parse_and_validate", "config_validate_ms")
        or segment_ms.get("config_parse_and_validate")
        or _missing("config_parse_and_validate span was not recorded.", "Cannot rank config validation cost."),
        "resource_preflight_ms": segment_ms.get("resource_preflight")
        or _skipped("Resource preflight is only executed by stages that require bounded scale admission."),
        "plan_build_ms": _sum_metric_values(segment_ms.get("node_spec_generation"), segment_ms.get("nodehost_plan")),
        "port_check_ms": segment_ms.get("port_preflight_check")
        or _missing("port_preflight_check span was not recorded.", "Cannot isolate local port collision check cost."),
        "nodehost_start_ms": _timing_ms(timings_by_name, "nodehost_start") or segment_ms.get("nodehost_start") or RUNTIME_ONLY_REASON,
        "node_config_generate_ms": segment_ms.get("node_config_local_generate")
        or _timing_detail_ms(timings_by_name, "process_config_prepare", "config_local_generate_seconds")
        or RUNTIME_ONLY_REASON,
        "node_config_distribute_ms": _sum_metric_values(
            segment_ms.get("nodehost_bundle_write"),
            segment_ms.get("docker_cp_bundle"),
            segment_ms.get("nodehost_bundle_install"),
        ),
        "process_start_ms": _timing_ms(timings_by_name, "process_start") or segment_ms.get("nodehost_start_all") or RUNTIME_ONLY_REASON,
        "process_ready_wait_ms": _timing_ms(timings_by_name, "process_ready_wait") or segment_ms.get("process_ready_wait") or RUNTIME_ONLY_REASON,
        "cluster_meet_ms": _sum_metric_values(
            _timing_ms(timings_by_name, "primary_cluster_create") or segment_ms.get("primary_cluster_create"),
            _timing_ms(timings_by_name, "replica_meet") or segment_ms.get("replica_meet"),
        ),
        "cluster_slots_assign_ms": _timing_detail_ms(timings_by_name, "primary_cluster_create", "slot_assignment_seconds")
        or _timing_ms(timings_by_name, "cluster_slots_assign")
        or segment_ms.get("cluster_slots_assign")
        or _timing_ms(timings_by_name, "primary_cluster_create")
        or segment_ms.get("primary_cluster_create")
        or RUNTIME_ONLY_REASON,
        "replica_replicate_ms": _timing_ms(timings_by_name, "replica_replicate") or segment_ms.get("replica_replicate") or RUNTIME_ONLY_REASON,
        "cluster_convergence_probe_ms": _sum_metric_values(
            _timing_ms(timings_by_name, "runtime_representative_probe"),
            segment_ms.get("cluster_convergence_wait"),
        ),
        "full_cluster_probe_ms": _sum_metric_values(
            _timing_ms(timings_by_name, "runtime_final_full_probe"),
            segment_ms.get("cluster_final_full_snapshot"),
            segment_ms.get("cluster_final_snapshot"),
        ),
        "cleanup_ms": _cleanup_ms(cleanup_report),
        "total_setup_ms": _ms(sum(float(segment["duration_seconds"]) for segment in normalized_segments))
        if normalized_segments
        else _missing("setup timeline segments were not recorded.", "Cannot compute total setup duration."),
    }
    node_samples = _node_samples(nodes or [], metric_values)
    nodehost_samples = _nodehost_samples(nodehosts or [], nodes or [], metric_values)
    slow_nodes = _top_n(node_samples, "node_ready_ms")
    slow_replicas = _top_n([sample for sample in node_samples if sample.get("node_role") == "replica"], "node_ready_ms")
    missing_metrics = _setup_missing_metrics(metric_values)
    artifact = {
        "schema_version": "v1",
        "artifact_type": SETUP_TELEMETRY_ARTIFACT_TYPE,
        "phase_id": phase_id,
        "run_id": run_id,
        "scenario": scenario,
        "created_at": utc_now(),
        "producer": {"name": "valkey-scale-lab-runtime", "version": __version__},
        "status": status if not missing_metrics or status != "PASS" else "PASS",
        "node_count": int(node_count),
        "same_schema_scale_rungs": [30, 50, 100, 200],
        "metrics": metric_values,
        "per_node_samples": node_samples
        or [_skipped("No per-node samples exist because setup did not reach live node runtime.")],
        "per_nodehost_samples": nodehost_samples
        or [_skipped("No per-nodehost samples exist because setup did not reach nodehost runtime.")],
        "slowest_nodes_topN": slow_nodes
        or [_skipped("Slow-node ranking requires numeric per-node readiness samples.")],
        "slowest_replica_replicate_topN": slow_replicas
        or [_skipped("Slow-replica ranking requires numeric replica readiness samples.")],
        "cleanup": _cleanup_summary(cleanup_report),
        "missing_metrics": missing_metrics,
        "source_artifacts": source_artifacts or [],
    }
    if blocked_reason:
        artifact["blocked_reason"] = blocked_reason
    return artifact


def write_setup_telemetry_artifact(path: str | Path, artifact: dict[str, Any]) -> dict[str, Any]:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifact


def validate_setup_telemetry_artifact(artifact: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if artifact.get("artifact_type") != SETUP_TELEMETRY_ARTIFACT_TYPE:
        errors.append("artifact_type must be setup_telemetry")
    metrics = artifact.get("metrics")
    if not isinstance(metrics, dict):
        return [*errors, "metrics must be object"]
    for name in REQUIRED_SETUP_TELEMETRY_METRICS:
        if name not in metrics:
            errors.append(f"missing setup telemetry metric: {name}")
        elif not _is_metric_value(metrics[name]):
            errors.append(f"setup telemetry metric {name} must be numeric ms or structured missing/skipped reason")
    for collection in ["per_node_samples", "per_nodehost_samples", "slowest_nodes_topN", "slowest_replica_replicate_topN"]:
        if not isinstance(artifact.get(collection), list) or not artifact.get(collection):
            errors.append(f"{collection} must be a non-empty array or structured skipped reason")
    if not isinstance(artifact.get("cleanup"), dict):
        errors.append("cleanup must be object")
    return errors


def _segment_duration_ms(segments: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for segment in segments:
        if segment.get("kind") == "gap":
            continue
        name = str(segment.get("name", ""))
        out[name] = round(out.get(name, 0.0) + _ms(float(segment.get("duration_seconds", 0.0))), 3)
    return out


def _segment_detail_ms(segments: list[dict[str, Any]], segment_name: str, detail_name: str) -> float | None:
    for segment in segments:
        if segment.get("name") != segment_name:
            continue
        details = segment.get("details", {})
        if not isinstance(details, dict):
            return None
        value = details.get(detail_name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return round(max(float(value), 0.0), 3)
    return None


def _timing_ms(timings: dict[str, dict[str, Any]], name: str) -> float | None:
    value = timings.get(name, {}).get("duration_seconds")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _ms(value)
    return None


def _timing_detail_ms(timings: dict[str, dict[str, Any]], name: str, detail: str) -> float | None:
    value = timings.get(name, {}).get("details", {}).get(detail)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _ms(value)
    return None


def _sum_metric_values(*values: Any) -> float | dict[str, str]:
    numeric = [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    if numeric:
        return round(sum(numeric), 3)
    return dict(RUNTIME_ONLY_REASON)


def _cleanup_ms(cleanup_report: dict[str, Any] | None) -> float | dict[str, str]:
    if not cleanup_report:
        return _skipped("Cleanup timing is attached after gate cleanup runs.")
    timing = cleanup_report.get("cleanup_timing", {})
    if not isinstance(timing, dict):
        return _missing("cleanup_report.cleanup_timing is missing or invalid.", "Cannot quantify cleanup duration.")
    total = sum(float(value) for value in timing.values() if isinstance(value, (int, float)) and not isinstance(value, bool))
    return _ms(total)


def _cleanup_summary(cleanup_report: dict[str, Any] | None) -> dict[str, Any]:
    if not cleanup_report:
        return {
            "status": "SKIPPED_WITH_REASON",
            "reason": "Cleanup report is written by the cleanup command after setup.",
            "cleanup_ms": _skipped("Cleanup timing is attached after gate cleanup runs."),
            "resources_remaining": _skipped("Residual resources are checked during cleanup."),
        }
    return {
        "status": cleanup_report.get("status", "MISSING"),
        "cleanup_ms": _cleanup_ms(cleanup_report),
        "resources_remaining": cleanup_report.get("resources_remaining", []),
        "cleanup_timing": cleanup_report.get("cleanup_timing", {}),
    }


def _node_samples(nodes: list[dict[str, Any]], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    process_ready = metrics.get("process_ready_wait_ms", RUNTIME_ONLY_REASON)
    samples: list[dict[str, Any]] = []
    for node in nodes:
        logical_id = str(node.get("logical_id", "MISSING"))
        pid = node.get("pid", _missing("Node pid was not present in runtime state.", "Cannot prove process identity for this node."))
        known = node.get("cluster_known_nodes", node.get("known_nodes"))
        if known is None:
            known = _missing("Node cluster_known_nodes was not persisted in runtime state.", "Report cannot compare per-node membership convergence.")
        samples.append(
            {
                "logical_id": logical_id,
                "nodehost_id": node.get("nodehost_id", node.get("container_name", "MISSING")),
                "node_ready_ms": process_ready,
                "node_ping_ready_ms": process_ready,
                "node_cluster_known_nodes": known,
                "node_cluster_state": node.get("cluster_state", "MISSING"),
                "node_role": node.get("role", "MISSING"),
                "node_pid": pid,
            }
        )
    return samples


def _nodehost_samples(nodehosts: list[dict[str, Any]], nodes: list[dict[str, Any]], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for node in nodes:
        nodehost_id = str(node.get("nodehost_id", node.get("container_name", "MISSING")))
        counts[nodehost_id] = counts.get(nodehost_id, 0) + 1
    if not nodehosts and counts:
        nodehosts = [{"nodehost_id": key} for key in sorted(counts)]
    samples = []
    for nodehost in nodehosts:
        nodehost_id = str(nodehost.get("nodehost_id", nodehost.get("container_name", "MISSING")))
        samples.append(
            {
                "nodehost_id": nodehost_id,
                "az_id": nodehost.get("az_id", "MISSING"),
                "host_id": nodehost.get("host_id", "MISSING"),
                "container_name": nodehost.get("container_name", "MISSING"),
                "nodehost_start_ms": metrics.get("nodehost_start_ms", RUNTIME_ONLY_REASON),
                "nodehost_process_count": int(nodehost.get("logical_node_count", counts.get(nodehost_id, 0)) or 0),
            }
        )
    return samples


def _top_n(samples: list[dict[str, Any]], key: str, limit: int = 10) -> list[dict[str, Any]]:
    numeric = [sample for sample in samples if isinstance(sample.get(key), (int, float)) and not isinstance(sample.get(key), bool)]
    return sorted(numeric, key=lambda item: float(item[key]), reverse=True)[:limit]


def _setup_missing_metrics(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for name in REQUIRED_SETUP_TELEMETRY_METRICS:
        value = metrics.get(name)
        if isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON"}:
            missing.append({"metric": name, **value})
    return missing


def _is_metric_value(value: Any) -> bool:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value >= 0
    return isinstance(value, dict) and value.get("status") in {"MISSING", "SKIPPED_WITH_REASON"} and bool(value.get("reason"))


def _normalize_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(segments, start=1):
        start = float(raw["start_monotonic"])
        end = float(raw["end_monotonic"])
        normalized.append(
            {
                "id": str(raw.get("id") or f"segment_{idx:03d}"),
                "name": str(raw["name"]),
                "kind": str(raw.get("kind", "span")),
                "category": str(raw["category"]),
                "start_monotonic": round(start, 6),
                "end_monotonic": round(end, 6),
                "duration_seconds": _round_seconds(end - start),
                "status": str(raw.get("status", "PASS")),
                "details": dict(raw.get("details") or {}),
            }
        )
    return normalized


def build_phase_hierarchy(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        by_name.setdefault(str(segment["name"]), []).append(segment)
    hierarchy: list[dict[str, Any]] = []
    for group in DEFAULT_SETUP_GROUPS:
        children: list[dict[str, Any]] = []
        for child_name in group["children"]:
            duration = _round_seconds(sum(float(item["duration_seconds"]) for item in by_name.get(child_name, [])))
            children.append(
                {
                    "name": child_name,
                    "inclusive_duration_seconds": duration,
                    "exclusive_duration_seconds": duration,
                    "segment_ids": [item["id"] for item in by_name.get(child_name, [])],
                    "status": "PASS" if duration > 0 or child_name in by_name else "MISSING",
                }
            )
        inclusive = _round_seconds(sum(float(child["inclusive_duration_seconds"]) for child in children))
        hierarchy.append(
            {
                "name": group["name"],
                "category": group["category"],
                "inclusive_duration_seconds": inclusive,
                "exclusive_duration_seconds": 0.0,
                "children": children,
                "status": "PASS" if all(child["status"] == "PASS" for child in children) else "FAIL",
            }
        )
    return hierarchy


def setup_timeline_coverage(
    segments: list[dict[str, Any]],
    hierarchy: list[dict[str, Any]],
) -> dict[str, Any]:
    names = {str(segment["name"]) for segment in segments}
    groups = {str(item["name"]): item for item in hierarchy}
    segment_status = {
        name: ("PASS" if name in names else "MISSING")
        for name in REQUIRED_SETUP_SEGMENTS
    }
    group_status = {
        name: ("PASS" if groups.get(name, {}).get("status") == "PASS" else "MISSING")
        for name in REQUIRED_SETUP_GROUPS
    }
    return {
        "required_segments": segment_status,
        "required_groups": group_status,
        "status": "PASS"
        if all(value == "PASS" for value in segment_status.values())
        and all(value == "PASS" for value in group_status.values())
        else "FAIL",
    }


def largest_segments(segments: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    spans = [segment for segment in segments if segment.get("kind") != "gap"]
    return _largest(spans, limit)


def largest_gaps(segments: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    gaps = [segment for segment in segments if segment.get("kind") == "gap"]
    return _largest(gaps, limit)


def _largest(segments: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return [
        {
            "id": segment["id"],
            "name": segment["name"],
            "category": segment["category"],
            "duration_seconds": segment["duration_seconds"],
            "details": segment.get("details", {}),
        }
        for segment in sorted(segments, key=lambda item: float(item["duration_seconds"]), reverse=True)[:limit]
    ]


def unexplained_explanation(wall: float | None, total: float, unexplained: float | None) -> dict[str, Any]:
    if wall is None or unexplained is None:
        return {
            "status": "MISSING",
            "reason": "setup_command_wall is measured by the outer wrapper and has not been attached yet",
        }
    if unexplained <= SETUP_TIMELINE_UNEXPLAINED_LIMIT_SECONDS:
        return {
            "status": "PASS",
            "reason": "setup timeline explains setup_command_wall within the two-second process-boundary tolerance",
        }
    return {
        "status": "FAIL",
        "reason": "difference between outer wrapper setup_command_wall and setup subprocess timeline exceeds two seconds",
        "process_boundary_note": "Python interpreter startup, argument parsing before recorder creation, final artifact write, and process exit are outside the recorder; this must remain failing until further instrumentation reduces the gap.",
        "setup_command_wall_seconds": wall,
        "setup_timeline_total_seconds": total,
    }


def validate_setup_timeline_artifact(artifact: dict[str, Any]) -> list[str]:
    return validate_setup_timeline_artifact_data(artifact, require_wall=True)


def validate_setup_timeline_artifact_data(artifact: dict[str, Any], *, require_wall: bool) -> list[str]:
    errors: list[str] = []
    segments = artifact.get("segments", [])
    if not isinstance(segments, list) or not segments:
        return ["setup timeline segments must be a non-empty array"]
    previous_end: float | None = None
    for idx, segment in enumerate(segments):
        if not isinstance(segment, dict):
            errors.append(f"segments[{idx}] must be object")
            continue
        missing_fields: list[str] = []
        for field in [
            "id",
            "name",
            "kind",
            "category",
            "start_monotonic",
            "end_monotonic",
            "duration_seconds",
            "status",
            "details",
        ]:
            if field not in segment:
                missing_fields.append(field)
        for field in missing_fields:
            errors.append(f"segments[{idx}] missing {field}")
        if missing_fields:
            continue
        start = float(segment["start_monotonic"])
        end = float(segment["end_monotonic"])
        duration = float(segment["duration_seconds"])
        if end < start:
            errors.append(f"{segment['id']}: end_monotonic precedes start_monotonic")
        if abs(duration - max(end - start, 0.0)) > 0.01:
            errors.append(f"{segment['id']}: duration_seconds does not match monotonic bounds")
        if previous_end is not None:
            delta = start - previous_end
            if delta < -0.001:
                errors.append(f"{segment['id']}: segment overlaps previous segment")
            if delta > 0.01 and segment.get("kind") != "gap":
                errors.append(f"{segment['id']}: silent gap of {delta:.6f}s before non-gap segment")
        previous_end = end
    names = {str(segment.get("name")) for segment in segments if isinstance(segment, dict)}
    for name in REQUIRED_SETUP_SEGMENTS:
        if name not in names:
            errors.append(f"missing required setup timeline segment: {name}")
    hierarchy = artifact.get("phase_hierarchy", [])
    groups = {str(item.get("name")): item for item in hierarchy if isinstance(item, dict)}
    for name in REQUIRED_SETUP_GROUPS:
        group = groups.get(name)
        if not group:
            errors.append(f"missing required setup timeline hierarchy group: {name}")
            continue
        inclusive = group.get("inclusive_duration_seconds")
        exclusive = group.get("exclusive_duration_seconds")
        if not isinstance(inclusive, (int, float)) or not isinstance(exclusive, (int, float)):
            errors.append(f"hierarchy group {name} must include numeric inclusive/exclusive durations")
        elif float(exclusive) != 0.0:
            errors.append(f"hierarchy group {name} must not double-count child durations as exclusive time")
        children = group.get("children", [])
        child_sum = sum(float(child.get("inclusive_duration_seconds", 0.0)) for child in children if isinstance(child, dict))
        if isinstance(inclusive, (int, float)) and abs(float(inclusive) - child_sum) > 0.01:
            errors.append(f"hierarchy group {name} inclusive duration must equal sum(children)")
    if require_wall:
        wall = artifact.get("setup_command_wall_seconds")
        total = artifact.get("setup_timeline_total_seconds")
        unexplained = artifact.get("setup_timeline_unexplained_seconds")
        unexplained_status = artifact.get("setup_timeline_unexplained_status")
        if not isinstance(wall, (int, float)):
            errors.append("setup_command_wall_seconds must be numeric")
        if not isinstance(total, (int, float)):
            errors.append("setup_timeline_total_seconds must be numeric")
        if not isinstance(unexplained, (int, float)):
            errors.append("setup_timeline_unexplained_seconds must be numeric")
        elif float(unexplained) > SETUP_TIMELINE_UNEXPLAINED_LIMIT_SECONDS:
            errors.append("setup_timeline_unexplained_seconds exceeds 2.0")
        if unexplained_status != "PASS":
            errors.append(f"setup_timeline_unexplained_status must be PASS, got {unexplained_status!r}")
    return errors
