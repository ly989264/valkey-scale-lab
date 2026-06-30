from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from valkey_scale_lab import __version__

SETUP_TIMELINE_ARTIFACT_TYPE = "p13_setup_exhaustive_timeline"
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
