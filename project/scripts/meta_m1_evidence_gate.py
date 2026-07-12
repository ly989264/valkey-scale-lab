#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from valkey_scale_lab.meta_loop_v5.digests import product_tree_digest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DEFAULT_EVIDENCE_ROOT = WORKSPACE_ROOT / "loop_evidence" / "meta_runs" / "milestone1-v3" / "evidence"
REQUIRED_LIFECYCLE = {
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
}
REQUIRED_SCENARIOS = {
    "add_remove_node",
    "reshard_rebalance",
    "rolling_restart",
    "bounded_stability",
    "primary_failover",
    "replica_stop",
    "node_host_stop",
    "az_stop",
    "network_delay",
    "network_loss",
    "network_partition",
    "network_flap",
    "minority_majority",
    "split_brain_detection",
}
JSON_ARTIFACTS = {
    "run_metadata",
    "resource_preflight",
    "workload_windows",
    "lifecycle_timeline",
    "scenario_results",
    "management_results",
    "fault_results",
    "stability_results",
    "cleanup_report",
    "analysis_summary",
    "report_index",
}
JSONL_ARTIFACTS = {"command_log", "fault_command_log", "events", "metrics"}
REQUIRED_ARTIFACT_KINDS = JSON_ARTIFACTS | JSONL_ARTIFACTS
REPORT_SURFACES = {
    "topology_summary",
    "phase_durations",
    "bottlenecks",
    "resources",
    "workload_impact",
    "failover",
    "recovery",
    "error_summary",
    "missing_evidence",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Semantically admit exact-scale real Milestone 1 evidence")
    parser.add_argument("--scale", required=True, type=int, choices=(50, 200))
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    return parser


def source_tree_digest(project_root: Path = PROJECT_ROOT) -> str:
    return product_tree_digest(project_root)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is not valid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} JSON must be an object")
        return None
    return value


def _load_jsonl(path: Path, label: str, errors: list[str]) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"{label} cannot be read: {exc}")
        return []
    if not lines:
        errors.append(f"{label} JSONL must not be empty")
        return []
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{label}:{number} is not valid JSON: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{label}:{number} must be an object")
            continue
        rows.append(value)
    return rows


def evaluate(scale: int, evidence_root: Path) -> list[str]:
    base = (evidence_root / f"scale-{scale}").resolve()
    errors: list[str] = []
    admission = _load_object(base / "admission.json", "admission", errors)
    if admission is None:
        return errors

    expected = {
        "schema_version": "meta-m1-admission-v2",
        "execution_kind": "REAL_VALKEY_EXACT_SCALE",
        "requested_nodes": scale,
        "observed_nodes": scale,
        "status": "PASS",
    }
    for key, value in expected.items():
        if admission.get(key) != value:
            errors.append(f"admission.{key} must be {value!r}, got {admission.get(key)!r}")
    run_id = admission.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        errors.append("admission.run_id is required")
        run_id = ""
    run_nonce = admission.get("run_nonce")
    if not isinstance(run_nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", run_nonce):
        errors.append("admission.run_nonce must be a unique 32-character lowercase hex value")
    run_started = admission.get("run_started_unix_ms")
    run_ended = admission.get("run_ended_unix_ms")
    if not isinstance(run_started, int) or not isinstance(run_ended, int) or run_ended < run_started:
        errors.append("admission requires measured run_started_unix_ms and run_ended_unix_ms")
        run_started, run_ended = 0, 0
    if not re.fullmatch(r"[0-9a-f]{40}", str(admission.get("source_commit", ""))):
        errors.append("admission.source_commit must be a full Git commit hash")
    if admission.get("product_digest") != product_tree_digest(PROJECT_ROOT):
        errors.append("admission.product_digest does not match the current product tree")
    versions = admission.get("valkey_versions")
    if not isinstance(versions, list) or not versions or any(not re.fullmatch(r"9\.1(?:\.\d+)?", str(value)) for value in versions):
        errors.append("admission.valkey_versions must contain only observed 9.1.x versions")

    artifacts = admission.get("artifacts")
    items = artifacts if isinstance(artifacts, list) else []
    by_kind: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("kind"), str):
            errors.append("admission artifacts must be objects with a kind")
            continue
        kind = item["kind"]
        if kind in by_kind:
            errors.append(f"duplicate artifact kind: {kind}")
        by_kind[kind] = item
    missing = sorted(REQUIRED_ARTIFACT_KINDS - by_kind.keys())
    if missing:
        errors.append(f"missing artifact kinds: {missing}")
    management_commands = by_kind.get("command_log")
    fault_commands = by_kind.get("fault_command_log")
    if (
        isinstance(management_commands, dict)
        and isinstance(fault_commands, dict)
        and management_commands.get("sha256")
        and management_commands.get("sha256") == fault_commands.get("sha256")
    ):
        errors.append("management and fault command streams must be distinct evidence artifacts")

    parsed_json: dict[str, dict[str, Any]] = {}
    parsed_jsonl: dict[str, list[dict[str, Any]]] = {}
    for kind, item in by_kind.items():
        raw = item.get("path")
        if not isinstance(raw, str) or not raw:
            errors.append(f"{kind} artifact path is required")
            continue
        path = (base / raw).resolve()
        if not path.is_relative_to(base):
            errors.append(f"{kind} artifact escapes evidence directory: {raw}")
            continue
        if not path.is_file():
            errors.append(f"{kind} artifact is missing: {raw}")
            continue
        if item.get("sha256") != _sha256(path):
            errors.append(f"{kind} artifact hash mismatch: {raw}")
        if any(token in raw.lower() for token in ("fixture", "fake", "synthetic", "example")):
            errors.append(f"{kind} artifact path is not admissible real evidence: {raw}")
        if kind in JSON_ARTIFACTS:
            value = _load_object(path, kind, errors)
            if value is not None:
                parsed_json[kind] = value
        elif kind in JSONL_ARTIFACTS:
            parsed_jsonl[kind] = _load_jsonl(path, kind, errors)

    _validate_common(scale, str(run_id), int(run_started), int(run_ended), parsed_json, parsed_jsonl, errors)
    _validate_preflight(scale, parsed_json.get("resource_preflight"), errors)
    _validate_probe(scale, admission.get("independent_probe"), errors)
    _validate_lifecycle(str(run_id), parsed_json.get("lifecycle_timeline"), parsed_jsonl.get("events", []), errors)
    _validate_scenarios(str(run_id), parsed_json.get("scenario_results"), parsed_jsonl, base, errors)
    _validate_cleanup(parsed_json.get("cleanup_report"), admission.get("cleanup"), errors)
    _validate_report(parsed_json.get("analysis_summary"), parsed_json.get("report_index"), base, errors)
    return errors


def _validate_common(
    scale: int,
    run_id: str,
    run_started: int,
    run_ended: int,
    objects: dict[str, dict[str, Any]],
    streams: dict[str, list[dict[str, Any]]],
    errors: list[str],
) -> None:
    run_metadata = objects.get("run_metadata")
    if isinstance(run_metadata, dict):
        nodes = run_metadata.get("nodes")
        node_rows = nodes if isinstance(nodes, list) else []
        logical_ids = [
            str(node.get("logical_id"))
            for node in node_rows
            if isinstance(node, dict) and isinstance(node.get("logical_id"), str) and node["logical_id"].strip()
        ]
        if len(node_rows) != scale or len(logical_ids) != scale or len(set(logical_ids)) != scale:
            errors.append(f"run_metadata.nodes must contain {scale} unique non-empty logical_id values")
    for kind, value in objects.items():
        if value.get("schema_version") != "v1":
            errors.append(f"{kind}.schema_version must be 'v1'")
        if kind != "resource_preflight" and value.get("status") != "PASS":
            errors.append(f"{kind}.status must be PASS")
        if value.get("run_id") != run_id:
            errors.append(f"{kind}.run_id must match admission.run_id")
        created = value.get("created_at_unix_ms")
        if not isinstance(created, int) or not run_started <= created <= run_ended:
            errors.append(f"{kind}.created_at_unix_ms must fall within the measured run")
        observed = value.get("node_count", value.get("scale"))
        if observed is not None and observed != scale:
            errors.append(f"{kind} scale/node_count must equal {scale}")
    for kind, rows in streams.items():
        for number, row in enumerate(rows, start=1):
            if row.get("run_id") != run_id:
                errors.append(f"{kind}:{number} run_id must match admission.run_id")
            timestamp = row.get("timestamp_unix_ms")
            if not isinstance(timestamp, int) or not run_started <= timestamp <= run_ended:
                errors.append(f"{kind}:{number} timestamp_unix_ms must fall within the measured run")
            if kind in {"command_log", "fault_command_log"}:
                if not row.get("command_id") or row.get("status") != "PASS" or not row.get("scenario_id"):
                    errors.append(f"{kind}:{number} requires command_id, scenario_id, and PASS")
            elif kind == "events":
                if not row.get("event_id") or not isinstance(row.get("monotonic_ms"), (int, float)):
                    errors.append(f"events:{number} requires event_id and monotonic_ms")
            elif kind == "metrics":
                if not row.get("metric_name") or "metric_value" not in row:
                    errors.append(f"metrics:{number} requires metric_name and metric_value")
    metadata = objects.get("run_metadata")
    if metadata is not None:
        nodes = metadata.get("nodes")
        if not isinstance(nodes, list) or len(nodes) != scale:
            errors.append(f"run_metadata.nodes must contain exactly {scale} nodes")


def _validate_preflight(scale: int, value: dict[str, Any] | None, errors: list[str]) -> None:
    if value is None:
        return
    if value.get("status") != "PASS" or value.get("can_run") is not True:
        errors.append("resource_preflight must PASS with can_run=true")
    requested = value.get("nodes_requested", value.get("node_count"))
    if requested != scale:
        errors.append(f"resource_preflight must cover exactly {scale} nodes")
    checks = value.get("checks")
    if not isinstance(checks, list) or not checks or any(not isinstance(item, dict) or item.get("status") != "PASS" for item in checks):
        errors.append("resource_preflight checks must be a non-empty all-PASS list")


def _validate_probe(scale: int, probe: Any, errors: list[str]) -> None:
    if not isinstance(probe, dict):
        errors.append("admission.independent_probe is required")
        return
    expected = {"status": "PASS", "observed_nodes": scale, "cluster_state": "ok", "slots_assigned": 16384, "slots_ok": 16384}
    for key, value in expected.items():
        if probe.get(key) != value:
            errors.append(f"independent_probe.{key} must be {value!r}")
    if not isinstance(probe.get("endpoint_count"), int) or probe["endpoint_count"] < 2:
        errors.append("independent_probe.endpoint_count must be at least 2")


def _validate_lifecycle(run_id: str, value: dict[str, Any] | None, events: list[dict[str, Any]], errors: list[str]) -> None:
    if value is None:
        return
    steps = value.get("steps")
    rows = steps if isinstance(steps, list) else []
    by_id = {str(item.get("id")): item for item in rows if isinstance(item, dict)}
    missing = sorted(REQUIRED_LIFECYCLE - by_id.keys())
    if missing:
        errors.append(f"lifecycle_timeline missing steps: {missing}")
    event_by_id = {str(item.get("event_id")): item for item in events if item.get("event_id")}
    for step_id in sorted(REQUIRED_LIFECYCLE & by_id.keys()):
        step = by_id[step_id]
        start = step.get("started_monotonic_ms")
        end = step.get("ended_monotonic_ms")
        refs = step.get("event_ids")
        if step.get("status") != "PASS" or not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end < start:
            errors.append(f"lifecycle step {step_id} needs measured monotonic bounds and PASS")
        if not isinstance(refs, list) or not refs or any(str(ref) not in event_by_id for ref in refs):
            errors.append(f"lifecycle step {step_id} must reference existing events")
        elif any(event_by_id[str(ref)].get("step_id") != step_id for ref in refs):
            errors.append(f"lifecycle step {step_id} event references must identify the same step")
        if step.get("run_id") != run_id:
            errors.append(f"lifecycle step {step_id} run_id mismatch")
    preflight = by_id.get("resource_preflight", {})
    runtime_start = by_id.get("runtime_start", {})
    preflight_end = preflight.get("ended_monotonic_ms")
    runtime_begin = runtime_start.get("started_monotonic_ms")
    if isinstance(preflight_end, (int, float)) and isinstance(runtime_begin, (int, float)) and preflight_end > runtime_begin:
        errors.append("lifecycle resource_preflight must finish before runtime_start begins")


def _validate_scenarios(
    run_id: str,
    value: dict[str, Any] | None,
    streams: dict[str, list[dict[str, Any]]],
    base: Path,
    errors: list[str],
) -> None:
    if value is None:
        return
    rows = value.get("scenarios")
    scenarios = rows if isinstance(rows, list) else []
    by_id = {str(item.get("id")): item for item in scenarios if isinstance(item, dict)}
    missing = sorted(REQUIRED_SCENARIOS - by_id.keys())
    if missing:
        errors.append(f"scenario_results missing scenarios: {missing}")
    event_by_id = {str(item.get("event_id")): item for item in streams.get("events", []) if item.get("event_id")}
    command_by_id = {
        str(item.get("command_id")): item
        for kind in ("command_log", "fault_command_log")
        for item in streams.get(kind, [])
        if item.get("command_id")
    }
    operation_scenarios: dict[str, set[str]] = {}
    for scenario_id in sorted(REQUIRED_SCENARIOS & by_id.keys()):
        row = by_id[scenario_id]
        if row.get("status") != "REAL_PASS" or row.get("run_id") != run_id:
            errors.append(f"scenario {scenario_id} must be REAL_PASS for the admitted run")
        refs = row.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"scenario {scenario_id} must cite evidence_refs")
        else:
            for raw in refs:
                path = (base / str(raw)).resolve()
                if not path.is_relative_to(base) or not path.is_file():
                    errors.append(f"scenario {scenario_id} evidence_ref is missing or escapes: {raw}")
        row_events = row.get("event_ids")
        row_commands = row.get("command_ids")
        if not isinstance(row_events, list) or not row_events or any(str(ref) not in event_by_id for ref in row_events):
            errors.append(f"scenario {scenario_id} must reference existing event_ids")
        elif any(event_by_id[str(ref)].get("scenario_id") != scenario_id for ref in row_events):
            errors.append(f"scenario {scenario_id} event_ids must identify the same scenario")
        if not isinstance(row_commands, list) or not row_commands or any(str(ref) not in command_by_id for ref in row_commands):
            errors.append(f"scenario {scenario_id} must reference existing command_ids")
        elif any(command_by_id[str(ref)].get("scenario_id") != scenario_id for ref in row_commands):
            errors.append(f"scenario {scenario_id} command_ids must identify the same scenario")
        else:
            for ref in row_commands:
                operation_id = command_by_id[str(ref)].get("operation_id")
                if isinstance(operation_id, str) and operation_id:
                    operation_scenarios.setdefault(operation_id, set()).add(scenario_id)
        if isinstance(row_events, list):
            for ref in row_events:
                event = event_by_id.get(str(ref), {})
                operation_id = event.get("operation_id")
                if isinstance(operation_id, str) and operation_id:
                    operation_scenarios.setdefault(operation_id, set()).add(scenario_id)
    shared = {operation: sorted(scenarios) for operation, scenarios in operation_scenarios.items() if len(scenarios) > 1}
    if shared:
        errors.append(f"operation provenance must not be relabelled across scenarios: {shared}")


def _validate_cleanup(value: dict[str, Any] | None, summary: Any, errors: list[str]) -> None:
    if value is None:
        return
    if value.get("resources_remaining") not in ([], None) or value.get("cleanup_errors") not in ([], None):
        errors.append("cleanup_report must have no residual resources or cleanup errors")
    if not isinstance(summary, dict) or summary.get("status") != "PASS" or summary.get("residual_owned_resources") != 0:
        errors.append("admission.cleanup must PASS with zero residual owned resources")


def _validate_report(analysis: dict[str, Any] | None, report: dict[str, Any] | None, base: Path, errors: list[str]) -> None:
    if analysis is not None:
        missing = sorted(REPORT_SURFACES - analysis.keys())
        if missing:
            errors.append(f"analysis_summary missing required report surfaces: {missing}")
        shown_surfaces = {
            surface
            for surface in REPORT_SURFACES - {"missing_evidence"}
            if isinstance(analysis.get(surface), dict) and bool(analysis[surface])
        }
        for surface in sorted(REPORT_SURFACES):
            if analysis.get(surface) is None:
                errors.append(f"analysis_summary.{surface} must show evidence or explicit missing evidence")
            elif surface != "missing_evidence" and analysis.get(surface) == {} and shown_surfaces:
                errors.append(f"analysis_summary.{surface} must not be empty when other report evidence is shown")
    if report is None:
        return
    views = report.get("views")
    if not isinstance(views, list) or not views:
        errors.append("report_index.views must be a non-empty list")
        return
    for index, view in enumerate(views):
        if not isinstance(view, dict) or view.get("status") != "PASS" or not isinstance(view.get("path"), str):
            errors.append(f"report_index view {index} is invalid")
            continue
        path = (base / "runtime" / view["path"]).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            errors.append(f"report_index view {index} path is missing or escapes")
            continue
        if path.suffix == ".json":
            _load_object(path, f"report_index view {index}", errors)


def main() -> int:
    args = _parser().parse_args()
    errors = evaluate(args.scale, args.evidence_root)
    print(json.dumps({"status": "PASS" if not errors else "FAIL", "scale": args.scale, "errors": errors}, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
