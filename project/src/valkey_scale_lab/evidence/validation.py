from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from valkey_scale_lab.scenarios import ScenarioDefinition

from .contracts import MISSING_STATUSES


_HEX64 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class RawSourceErrors:
    """Source-evidence problems, split by which §12.1 kind they are.

    §12.1 puts 必要证据无法写入 on the collector's side of the line: evidence that
    cannot be read is the tool failing, not the cluster being observed and found
    wanting. This validator only runs after a passing gate, so by then every
    required artifact should exist - a file that is missing or unparseable at that
    point is the evidence layer breaking, and reporting it as a run failure told a
    reader something untrue about the cluster.
    """

    semantic: tuple[str, ...] = ()
    tool: tuple[str, ...] = ()

    @property
    def all(self) -> tuple[str, ...]:
        # §12.2's order: a confirmed failure is reported ahead of a tool error.
        return self.semantic + self.tool

    def __bool__(self) -> bool:
        return bool(self.semantic or self.tool)


def load_raw_documents(
    base: Path, definition: ScenarioDefinition
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]], list[str], list[str]]:
    """Load every declared artifact, keeping unreadable apart from malformed.

    A file that cannot be opened or parsed is a tool error. A file that opens and
    parses but holds the wrong shape is an observation of bad evidence, which is
    the producer's failure and stays semantic.
    """

    runtime = Path(base).resolve() / "runtime"
    objects: dict[str, dict[str, Any]] = {}
    streams: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    tool_errors: list[str] = []
    for artifact in definition.artifacts:
        path = runtime / artifact.raw_name
        try:
            if artifact.format == "json":
                value = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    errors.append(f"runtime/{artifact.raw_name} must contain a JSON object")
                else:
                    objects[artifact.raw_name] = value
            else:
                lines = path.read_text(encoding="utf-8").splitlines()
                rows = [json.loads(line) for line in lines if line.strip()]
                if not rows or any(not isinstance(row, dict) for row in rows):
                    errors.append(
                        f"runtime/{artifact.raw_name} must contain non-empty JSON object rows"
                    )
                else:
                    streams[artifact.raw_name] = rows
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            tool_errors.append(f"runtime/{artifact.raw_name} is missing or invalid: {exc}")
    return objects, streams, errors, tool_errors


def validate_raw_sources(
    base: Path,
    scale: int,
    definition: ScenarioDefinition,
) -> tuple[str, ...]:
    """Every source-evidence problem, in §12.2's order.

    Kept for callers that only need to know whether the evidence is admissible.
    `validate_raw_sources_by_kind` is the implementation and is what a caller
    needs when the *kind* of failure decides the run's verdict.
    """

    return validate_raw_sources_by_kind(base, scale, definition).all


def validate_raw_sources_by_kind(
    base: Path,
    scale: int,
    definition: ScenarioDefinition,
) -> RawSourceErrors:
    errors: list[str] = []
    if isinstance(scale, bool) or not isinstance(scale, int):
        return RawSourceErrors(semantic=("requested scale must be an integer",))
    if not definition.scale_policy.min_nodes <= scale <= definition.scale_policy.max_nodes:
        return RawSourceErrors(
            semantic=(
                f"requested scale must be between {definition.scale_policy.min_nodes} and {definition.scale_policy.max_nodes}",
            )
        )
    objects, streams, load_errors, tool_errors = load_raw_documents(base, definition)
    errors.extend(load_errors)
    if tool_errors:
        # Evidence that could not be read cannot also be judged. Every check below
        # reads a missing name as `{}` and would append a derived complaint - `must
        # PASS for the admitted run` about a file nobody could open - and under
        # §12.2's precedence that derived semantic error would outrank the tool
        # error that caused it, hiding the real finding behind its own consequence.
        # Any shape errors already found came from files that did open, so they are
        # independent findings and are kept.
        return RawSourceErrors(semantic=tuple(errors), tool=tuple(tool_errors))
    run_state = objects.get("run_state.json", {})
    run_id = run_state.get("run_id")
    nodes = run_state.get("nodes") if isinstance(run_state.get("nodes"), list) else []
    logical_ids = [
        node.get("logical_id")
        for node in nodes
        if isinstance(node, dict)
        and isinstance(node.get("logical_id"), str)
        and node["logical_id"]
    ]
    if not isinstance(run_id, str) or not run_id:
        errors.append("runtime/run_state.json requires run_id")
    if (
        run_state.get("status") != "PASS"
        or run_state.get("node_count") != scale
        or len(nodes) != scale
    ):
        errors.append(f"runtime/run_state.json must PASS with exactly {scale} nodes")
    if len(logical_ids) != scale or len(set(logical_ids)) != scale:
        errors.append(
            f"runtime/run_state.json requires exactly {scale} unique logical_id values"
        )

    for name in (
        "management_sequence.json",
        "fault_sequence.json",
        "cleanup_report.json",
        "analysis_summary.json",
        "report_index.json",
        "full_flow_result.json",
    ):
        value = objects.get(name, {})
        if value.get("status") != "PASS" or value.get("run_id") != run_id:
            errors.append(f"runtime/{name} must PASS for the admitted run")
    for name in ("workload_windows.json", "lifecycle_timeline.json", "scenario_results.json"):
        value = objects.get(name, {})
        if value.get("status") != "PASS" or value.get("run_id") != run_id:
            errors.append(f"runtime/{name} must PASS for the admitted run")

    preflight = objects.get("resource_preflight.json", {})
    requested = preflight.get("nodes_requested", preflight.get("node_count"))
    if preflight.get("status") != "PASS" or preflight.get("can_run") is not True or requested != scale:
        errors.append(f"runtime/resource_preflight.json must admit exactly {scale} nodes")
    cleanup = objects.get("cleanup_report.json", {})
    if cleanup.get("resources_remaining") not in ([], None) or cleanup.get(
        "cleanup_errors"
    ) not in ([], None):
        errors.append("runtime/cleanup_report.json reports residual resources or cleanup errors")

    analysis = objects.get("analysis_summary.json", {})
    missing_surfaces = sorted(set(definition.report_ids) - analysis.keys())
    if missing_surfaces:
        errors.append(
            f"runtime/analysis_summary.json is missing report surfaces: {missing_surfaces}"
        )
    _validate_missing_taxonomy(objects, streams, errors)
    _validate_streams(streams, str(run_id), errors)
    _validate_workload(objects.get("workload_windows.json"), errors)
    _validate_lifecycle(
        objects.get("lifecycle_timeline.json"),
        streams.get("events.jsonl", []),
        str(run_id),
        definition.lifecycle_ids,
        errors,
    )
    _validate_scenarios(
        Path(base).resolve(),
        objects.get("scenario_results.json"),
        streams,
        str(run_id),
        definition,
        errors,
    )
    # Reached only when every declared artifact was readable, so anything here is
    # a reading of evidence that exists.
    return RawSourceErrors(semantic=tuple(errors))


def _validate_streams(
    streams: Mapping[str, list[dict[str, Any]]], run_id: str, errors: list[str]
) -> None:
    for name, rows in streams.items():
        if any(row.get("run_id") != run_id for row in rows):
            errors.append(f"runtime/{name} contains rows from another run")
    events = streams.get("events.jsonl", [])
    event_ids = [row.get("event_id") for row in events]
    if any(not isinstance(value, str) or not value for value in event_ids) or len(
        set(event_ids)
    ) != len(event_ids):
        errors.append("runtime/events.jsonl requires globally unique event_id values")
    commands = [
        *streams.get("management_command_log.jsonl", []),
        *streams.get("fault_command_log.jsonl", []),
    ]
    command_ids = [row.get("command_id") for row in commands]
    if any(not isinstance(value, str) or not value for value in command_ids) or len(
        set(command_ids)
    ) != len(command_ids):
        errors.append("runtime command logs require globally unique command_id values")
    for row in commands:
        if row.get("status") != "PASS" or not row.get("operation_id") or not row.get(
            "scenario_id"
        ):
            errors.append("runtime command rows require PASS, operation_id, and scenario_id")
    for row in streams.get("metrics_timeseries.jsonl", []):
        if not row.get("metric_name") or "metric_value" not in row:
            errors.append("runtime metric rows require metric_name and metric_value")


def _validate_workload(value: dict[str, Any] | None, errors: list[str]) -> None:
    if not isinstance(value, dict):
        return
    windows = value.get("windows")
    if not isinstance(windows, list) or not windows:
        errors.append("runtime/workload_windows.json requires observed workload windows")
    elif any(not isinstance(row, dict) or row.get("status") != "PASS" for row in windows):
        errors.append("runtime/workload_windows.json requires all observed windows to PASS")


def _validate_lifecycle(
    value: dict[str, Any] | None,
    events: list[dict[str, Any]],
    run_id: str,
    lifecycle_ids: tuple[str, ...],
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        return
    rows = value.get("steps") if isinstance(value.get("steps"), list) else []
    by_id = {str(row.get("id")): row for row in rows if isinstance(row, dict)}
    missing = sorted(set(lifecycle_ids) - by_id.keys())
    if missing:
        errors.append(f"runtime/lifecycle_timeline.json missing measured steps: {missing}")
    event_by_id = {str(row.get("event_id")): row for row in events if row.get("event_id")}
    for step_id in lifecycle_ids:
        row = by_id.get(step_id)
        if row is None:
            continue
        start, end = row.get("started_monotonic_ms"), row.get("ended_monotonic_ms")
        refs = row.get("event_ids")
        if row.get("status") != "PASS" or row.get("run_id") != run_id:
            errors.append(f"lifecycle step {step_id} must PASS for the admitted run")
        if (
            not isinstance(start, (int, float))
            or isinstance(start, bool)
            or not isinstance(end, (int, float))
            or isinstance(end, bool)
            or end <= start
        ):
            errors.append(f"lifecycle step {step_id} requires positive measured monotonic bounds")
        if not isinstance(refs, list) or not refs:
            errors.append(f"lifecycle step {step_id} requires measured event references")
        elif any(
            str(ref) not in event_by_id
            or event_by_id[str(ref)].get("step_id") != step_id
            for ref in refs
        ):
            errors.append(f"lifecycle step {step_id} requires matching measured events")
    first, second = by_id.get("resource_preflight", {}), by_id.get("runtime_start", {})
    if isinstance(first.get("ended_monotonic_ms"), (int, float)) and isinstance(
        second.get("started_monotonic_ms"), (int, float)
    ) and first["ended_monotonic_ms"] > second["started_monotonic_ms"]:
        errors.append("resource_preflight must finish before runtime_start begins")


def _validate_scenarios(
    base: Path,
    value: dict[str, Any] | None,
    streams: Mapping[str, list[dict[str, Any]]],
    run_id: str,
    definition: ScenarioDefinition,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        return
    rows = value.get("scenarios") if isinstance(value.get("scenarios"), list) else []
    by_id = {str(row.get("id")): row for row in rows if isinstance(row, dict)}
    missing = sorted(set(definition.scenario_ids) - by_id.keys())
    if missing:
        errors.append(f"runtime/scenario_results.json missing observed scenarios: {missing}")
    event_by_id = {
        str(row.get("event_id")): row
        for row in streams.get("events.jsonl", [])
        if row.get("event_id")
    }
    command_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for stream_name, raw_name in (
        ("management", "management_command_log.jsonl"),
        ("fault", "fault_command_log.jsonl"),
    ):
        for row in streams.get(raw_name, []):
            if row.get("command_id"):
                command_by_id[str(row["command_id"])] = (stream_name, row)
    owners: dict[str, str] = {}
    management = set(definition.management_ids)
    for scenario_id in definition.scenario_ids:
        row = by_id.get(scenario_id)
        if row is None:
            continue
        if row.get("status") != "REAL_PASS" or row.get("run_id") != run_id:
            errors.append(f"scenario {scenario_id} must be an observed REAL_PASS for the admitted run")
        event_ids = row.get("event_ids") if isinstance(row.get("event_ids"), list) else []
        command_ids = row.get("command_ids") if isinstance(row.get("command_ids"), list) else []
        if not event_ids or any(str(ref) not in event_by_id for ref in event_ids):
            errors.append(f"scenario {scenario_id} requires existing observed event_ids")
        if not command_ids or any(str(ref) not in command_by_id for ref in command_ids):
            errors.append(f"scenario {scenario_id} requires existing observed command_ids")
        expected_stream = "management" if scenario_id in management else "fault"
        for ref in command_ids:
            item = command_by_id.get(str(ref))
            if item is None:
                continue
            stream_name, command = item
            if stream_name != expected_stream or command.get("scenario_id") != scenario_id:
                errors.append(f"scenario {scenario_id} command provenance does not match its source stream")
            _claim_operation(command.get("operation_id"), scenario_id, owners, errors)
        for ref in event_ids:
            event = event_by_id.get(str(ref))
            if event is None:
                continue
            if event.get("scenario_id") != scenario_id:
                errors.append(f"scenario {scenario_id} event provenance does not match")
            _claim_operation(event.get("operation_id"), scenario_id, owners, errors)
        refs = row.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"scenario {scenario_id} requires evidence_refs")
        else:
            for raw in refs:
                path = (base / str(raw)).resolve()
                if not path.is_relative_to(base) or not path.is_file():
                    errors.append(f"scenario {scenario_id} evidence_ref is missing or escapes: {raw}")


def _claim_operation(
    raw: Any, scenario_id: str, owners: dict[str, str], errors: list[str]
) -> None:
    if not isinstance(raw, str) or not raw:
        errors.append(f"scenario {scenario_id} requires observed operation_id provenance")
        return
    existing = owners.setdefault(raw, scenario_id)
    if existing != scenario_id:
        errors.append(f"operation {raw} cannot be relabelled from {existing} to {scenario_id}")


def _validate_missing_taxonomy(
    objects: Mapping[str, dict[str, Any]],
    streams: Mapping[str, list[dict[str, Any]]],
    errors: list[str],
) -> None:
    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            status = value.get("status")
            if status in MISSING_STATUSES:
                reason = value.get("reason")
                if not isinstance(reason, str) or not reason.strip():
                    errors.append(f"{path} status {status} requires a non-empty reason")
            for key, item in value.items():
                visit(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    for name, value in objects.items():
        visit(value, f"runtime/{name}")
    for name, rows in streams.items():
        visit(rows, f"runtime/{name}")


def validate_digest(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        errors.append(f"{label} must be a 64-character lowercase SHA-256 digest")
