#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROFILE_FIELDS = [
    "requested_io_threads",
    "effective_io_threads",
    "requested_node_memory_limit_mb",
    "effective_node_memory_limit_mb",
    "io_thread_budget_status",
    "memory_budget_status",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability-id", required=True)
    parser.add_argument("--artifact-dir")
    args = parser.parse_args()

    base = Path(args.artifact_dir) if args.artifact_dir else ROOT / "artifacts" / "capabilities" / args.capability_id
    errors: list[str] = []
    artifacts = {
        "effective_server_profile": _load_json(base / "effective_server_profile.json", errors, "effective_server_profile"),
        "config_validation_report": _load_json(base / "config_validation_report.json", errors, "config_validation_report"),
        "resource_preflight": _load_json(base / "resource_preflight.json", errors, "resource_preflight"),
        "cluster_plan": _load_json(base / "cluster_plan.json", errors, "cluster_plan"),
        "run_state": _load_json(base / "run_state.json", errors, "run_state"),
        "generated_valkey_configs_manifest": _load_json(base / "generated_valkey_configs_manifest.json", errors, "generated_valkey_configs_manifest"),
    }
    if errors:
        _print(errors)
        return 1

    profile = artifacts["effective_server_profile"]
    _validate_profile("effective_server_profile", profile, errors)
    _validate_config_report(artifacts["config_validation_report"], errors)
    _validate_preflight(artifacts["resource_preflight"], errors)
    _validate_plan(artifacts["cluster_plan"], profile, errors)
    _validate_run_state(artifacts["run_state"], profile, errors)
    _validate_generated_configs(base, artifacts["generated_valkey_configs_manifest"], errors)
    _validate_real_evidence_files(base, errors)

    if errors:
        _print(errors)
        return 1
    print(f"PASS io-thread and memory evidence capability_id={args.capability_id}")
    return 0


def _validate_profile(label: str, profile: dict[str, Any], errors: list[str]) -> None:
    for field in PROFILE_FIELDS:
        if field not in profile:
            errors.append(f"{label}: missing {field}")
    if not profile:
        return
    effective_io = _int(profile.get("effective_io_threads"), 0)
    requested_mem = _int(profile.get("requested_node_memory_limit_mb"), 0)
    effective_mem = _int(profile.get("effective_node_memory_limit_mb"), 0)
    if effective_io < 1:
        errors.append(f"{label}: effective_io_threads must be >= 1")
    if requested_mem != 64 or effective_mem != 64:
        errors.append(f"{label}: requested/effective node memory must both be 64 MB")
    total_threads = _int(profile.get("total_valkey_threads"), effective_io)
    max_total = _int(profile.get("io_threads_max_total"), total_threads)
    if total_threads > max_total:
        errors.append(f"{label}: total_valkey_threads exceeds io_threads_max_total")
    if profile.get("io_thread_budget_status") not in {"PASS", "DEGRADED_WITH_REASON", "PENDING_PREFLIGHT"}:
        errors.append(f"{label}: invalid io_thread_budget_status {profile.get('io_thread_budget_status')!r}")


def _validate_config_report(report: dict[str, Any], errors: list[str]) -> None:
    for field in PROFILE_FIELDS:
        if field not in report:
            errors.append(f"config_validation_report: missing {field}")
    if _int(report.get("effective_node_memory_limit_mb"), 0) != 64:
        errors.append("config_validation_report: effective_node_memory_limit_mb must be 64")
    server_profile = report.get("server_profile", {})
    if isinstance(server_profile, dict):
        _validate_profile("config_validation_report.server_profile", server_profile, errors)
    else:
        errors.append("config_validation_report: server_profile must be object")


def _validate_preflight(report: dict[str, Any], errors: list[str]) -> None:
    for field in [
        "node_count",
        "can_run",
        "requested_io_threads",
        "effective_io_threads",
        "requested_node_memory_limit_mb",
        "effective_node_memory_limit_mb",
        "io_thread_budget_status",
        "memory_budget_status",
        "projected_node_memory_mb",
        "projected_nodehost_memory_mb",
        "host_available_memory_mb",
    ]:
        if field not in report:
            errors.append(f"resource_preflight: missing {field}")
    node_count = _int(report.get("node_count"), 0)
    memory = _int(report.get("effective_node_memory_limit_mb"), 0)
    projected = _int(report.get("projected_node_memory_mb"), -1)
    if memory != 64:
        errors.append("resource_preflight: effective_node_memory_limit_mb must be 64")
    if node_count > 0 and projected != node_count * memory:
        errors.append("resource_preflight: projected_node_memory_mb must equal node_count * effective_node_memory_limit_mb")
    if report.get("memory_budget_status") not in {"PASS", "FAIL", "BLOCKED", "DEGRADED_WITH_REASON"}:
        errors.append(f"resource_preflight: invalid memory_budget_status {report.get('memory_budget_status')!r}")
    checks = report.get("checks", [])
    if isinstance(checks, list):
        memory_checks = [item for item in checks if isinstance(item, dict) and item.get("name") == "memory_budget"]
        if not memory_checks:
            errors.append("resource_preflight: missing memory_budget check")
        for check in memory_checks:
            details = check.get("details", {})
            if details.get("node_count_times_node_memory_limit_mb") != node_count * memory:
                errors.append("resource_preflight.memory_budget: missing or wrong node_count_times_node_memory_limit_mb")
            if "host_available_memory_mb" not in details:
                errors.append("resource_preflight.memory_budget: missing host_available_memory_mb")
    else:
        errors.append("resource_preflight: checks must be a list")


def _validate_plan(plan: dict[str, Any], reference_profile: dict[str, Any], errors: list[str]) -> None:
    runtime = plan.get("runtime", {})
    if runtime.get("effective_io_threads") != reference_profile.get("effective_io_threads"):
        errors.append("cluster_plan.runtime: effective_io_threads does not match effective_server_profile")
    if runtime.get("effective_node_memory_limit_mb") != 64:
        errors.append("cluster_plan.runtime: effective_node_memory_limit_mb must be 64")
    _validate_nodes("cluster_plan.nodes", plan.get("nodes"), errors)


def _validate_run_state(state: dict[str, Any], reference_profile: dict[str, Any], errors: list[str]) -> None:
    runtime = state.get("runtime", {})
    if isinstance(runtime.get("server_profile"), dict):
        if runtime["server_profile"].get("effective_io_threads") != reference_profile.get("effective_io_threads"):
            errors.append("run_state.runtime.server_profile: effective_io_threads mismatch")
    elif state.get("effective_server_profile", {}).get("effective_io_threads") != reference_profile.get("effective_io_threads"):
        errors.append("run_state: missing runtime/effective server profile evidence")
    _validate_nodes("run_state.nodes", state.get("nodes"), errors)


def _validate_nodes(label: str, nodes: Any, errors: list[str]) -> None:
    if not isinstance(nodes, list) or not nodes:
        errors.append(f"{label}: must be a non-empty list")
        return
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"{label}[{index}]: must be object")
            continue
        effective_io = _int(node.get("effective_io_threads"), 0)
        memory = _int(node.get("effective_node_memory_limit_mb"), 0)
        if effective_io < 1:
            errors.append(f"{label}[{index}]: effective_io_threads missing or invalid")
        if memory != 64:
            errors.append(f"{label}[{index}]: effective_node_memory_limit_mb must be 64")
        if "effective_server_profile" not in node:
            errors.append(f"{label}[{index}]: missing effective_server_profile")


def _validate_generated_configs(base: Path, manifest: dict[str, Any], errors: list[str]) -> None:
    if manifest.get("artifact_type") != "generated_valkey_configs_manifest":
        errors.append("generated_valkey_configs_manifest: wrong artifact_type")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("generated_valkey_configs_manifest: entries must be non-empty")
        return
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"generated_valkey_configs_manifest.entries[{index}]: must be object")
            continue
        config_path = _resolve_path(base, str(entry.get("config_artifact_file", "")))
        if not config_path.exists():
            errors.append(f"generated config missing: {config_path}")
            continue
        text = config_path.read_text(encoding="utf-8")
        effective_io = _int(entry.get("effective_io_threads"), 0)
        memory = _int(entry.get("effective_node_memory_limit_mb"), 0)
        if effective_io < 1:
            errors.append(f"{config_path}: effective_io_threads must be >= 1")
        if memory != 64:
            errors.append(f"{config_path}: effective_node_memory_limit_mb must be 64")
        io_lines = [line.strip() for line in text.splitlines() if re.match(r"^\s*io-threads\b", line)]
        if effective_io > 1:
            if f"io-threads {effective_io}" not in io_lines:
                errors.append(f"{config_path}: missing io-threads {effective_io}")
            if entry.get("io_threads_line_present") is not True:
                errors.append(f"{config_path}: manifest must record io_threads_line_present=true")
        else:
            if io_lines:
                errors.append(f"{config_path}: io-threads line must be omitted when effective_io_threads=1")
        if f"maxmemory {memory}mb" not in text:
            errors.append(f"{config_path}: missing maxmemory {memory}mb")
        if entry.get("maxmemory_line_present") is not True:
            errors.append(f"{config_path}: manifest must record maxmemory_line_present=true")
        if entry.get("runtime_memory_limit_enforced") is not True and not entry.get("runtime_memory_limit_reason"):
            errors.append(f"{config_path}: non-enforced memory limit requires runtime_memory_limit_reason")


def _validate_real_evidence_files(base: Path, errors: list[str]) -> None:
    evidence_paths = sorted(base.glob("valkey_e2e_evidence*.json"))
    if not evidence_paths:
        errors.append("missing valkey_e2e_evidence*.json real evidence files")
        return
    for path in evidence_paths:
        evidence = _load_json(path, errors, path.name)
        if not evidence:
            continue
        if evidence.get("real_valkey") is not True:
            errors.append(f"{path.name}: real_valkey must be true")
        runtime = evidence.get("runtime", {})
        if isinstance(runtime.get("server_profile"), dict):
            _validate_profile(f"{path.name}.runtime.server_profile", runtime["server_profile"], errors)
        elif "effective_io_threads" not in runtime or "effective_node_memory_limit_mb" not in runtime:
            errors.append(f"{path.name}: runtime lacks effective server profile fields")
        processes = evidence.get("node_processes", [])
        _validate_nodes(f"{path.name}.node_processes", processes, errors)


def _load_json(path: Path, errors: list[str], label: str) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"{label} missing: {path}")
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{label}: invalid JSON: {exc}")
        return {}
    if not isinstance(obj, dict):
        errors.append(f"{label}: must be JSON object")
        return {}
    return obj


def _resolve_path(base: Path, ref: str) -> Path:
    path = Path(ref)
    if path.is_absolute():
        return path
    for candidate in [ROOT / path, base / path]:
        if candidate.exists():
            return candidate
    return ROOT / path


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _print(errors: list[str]) -> None:
    for err in errors:
        print(f"FAIL: {err}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
