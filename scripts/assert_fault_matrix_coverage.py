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

REQUIRED_FAULTS = {
    "P22_FAULT_REPLICA_HOST_AZ_STOP": {"replica_stop", "node_host_stop", "az_stop"},
    "P23_FAULT_NETWORK_DELAY_LOSS_FLAP": {"network_delay", "network_loss", "network_flap"},
    "P24_PARTITION_SPLIT_BRAIN_MATRIX": {"network_partition", "minority_partition", "majority_partition"},
}
SAFE_PATHS = {"container_netns_tc", "sandbox_proxy", "owned_container_control", "owned_runtime_control", "unsupported_skipped_with_reason"}
P22_MANDATORY_COUNTS = {6, 10}
P23_MANDATORY_COUNTS = {6, 10}
P23_FORBIDDEN_FAULTS = {"network_partition", "minority_partition", "majority_partition", "split_brain_window"}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_p22(rows: list[dict[str, Any]], base: Path, errors: list[str]) -> None:
    observed_pairs = {(row.get("fault_type"), row.get("node_count")) for row in rows if row.get("status") != "SKIPPED_WITH_REASON"}
    for fault_type in REQUIRED_FAULTS["P22_FAULT_REPLICA_HOST_AZ_STOP"]:
        for node_count in P22_MANDATORY_COUNTS:
            if (fault_type, node_count) not in observed_pairs:
                errors.append(f"P22 missing real {fault_type} row for {node_count} nodes")

    preflight_path = base / "resource_preflight_30.json"
    preflight = load_json(preflight_path) if preflight_path.exists() else {}
    real_30_plus = [row for row in rows if isinstance(row.get("node_count"), int) and int(row["node_count"]) >= 30 and row.get("status") != "SKIPPED_WITH_REASON"]
    skipped_30 = [row for row in rows if row.get("node_count") == 30 and row.get("status") == "SKIPPED_WITH_REASON"]
    if preflight.get("can_run") is True:
        if not real_30_plus:
            errors.append("P22 30+ preflight passed but no real 30+ row was emitted")
    else:
        if len(skipped_30) < len(REQUIRED_FAULTS["P22_FAULT_REPLICA_HOST_AZ_STOP"]):
            errors.append("P22 30+ preflight did not pass, so every 30-node fault row must be SKIPPED_WITH_REASON")
        for row in skipped_30:
            if not row.get("reason") or not row.get("preflight_ref"):
                errors.append(f"{row.get('fault_id')}: skipped 30+ row requires reason and preflight_ref")

    for row in rows:
        label = row.get("fault_id", row.get("fault_type"))
        if row.get("phase_id") != "P22_FAULT_REPLICA_HOST_AZ_STOP":
            errors.append(f"{label}: wrong phase_id {row.get('phase_id')!r}")
        if row.get("node_count") == 200:
            errors.append(f"{label}: P22 must not emit 200-node rows")
        if row.get("status") == "SKIPPED_WITH_REASON":
            if row.get("implementation_path") != "unsupported_skipped_with_reason":
                errors.append(f"{label}: skipped rows must use unsupported_skipped_with_reason")
            continue
        if row.get("real_valkey") is not True:
            errors.append(f"{label}: real rows must record real_valkey=true")
        if row.get("host_network_mutated") is not False:
            errors.append(f"{label}: host_network_mutated must be false")
        if row.get("physical_host_mutated") is not False:
            errors.append(f"{label}: physical_host_mutated must be false")
        if row.get("physical_az_mutated") is not False:
            errors.append(f"{label}: physical_az_mutated must be false")
        if row.get("implementation_path") not in {"owned_runtime_control", "owned_container_control"}:
            errors.append(f"{label}: P22 real rows must use owned runtime/container control")

        targets = row.get("targets") if isinstance(row.get("targets"), list) else []
        selector = row.get("target_selector") if isinstance(row.get("target_selector"), dict) else {}
        if row.get("fault_type") == "replica_stop":
            if not targets or any(target.get("role") != "replica" for target in targets if isinstance(target, dict)):
                errors.append(f"{label}: replica_stop must target only replica role")
            if selector.get("promotion_expected") is not False:
                errors.append(f"{label}: replica_stop must record promotion_expected=false")
            observed = row.get("observed_impact") if isinstance(row.get("observed_impact"), dict) else {}
            if observed.get("promotion_success") is True and observed.get("unexpected_promotion_observed") is not True:
                errors.append(f"{label}: replica_stop must not count promotion success unless unexpected promotion is recorded")
        if row.get("fault_type") == "node_host_stop":
            selected_host = selector.get("selected_host_id")
            target_hosts = {target.get("host_id") for target in targets if isinstance(target, dict)}
            if not selected_host or target_hosts != {selected_host}:
                errors.append(f"{label}: node_host_stop target host leakage selected={selected_host!r} targets={sorted(str(item) for item in target_hosts)}")
            if selector.get("logical_host_only") is not True:
                errors.append(f"{label}: node_host_stop must record logical_host_only=true")
        if row.get("fault_type") == "az_stop":
            selected_az = selector.get("selected_az_id")
            target_azs = {target.get("az_id") for target in targets if isinstance(target, dict)}
            if not selected_az or target_azs != {selected_az}:
                errors.append(f"{label}: az_stop target AZ leakage selected={selected_az!r} targets={sorted(str(item) for item in target_azs)}")
            if selector.get("virtual_az_only") is not True:
                errors.append(f"{label}: az_stop must record virtual_az_only=true")
            observed = row.get("observed_impact") if isinstance(row.get("observed_impact"), dict) else {}
            if "split_brain_window_ms" not in observed:
                errors.append(f"{label}: az_stop must record split_brain_window_ms or missing reason")


def validate_p23(rows: list[dict[str, Any]], base: Path, errors: list[str]) -> None:
    required_faults = REQUIRED_FAULTS["P23_FAULT_NETWORK_DELAY_LOSS_FLAP"]
    real_rows = [row for row in rows if row.get("status") != "SKIPPED_WITH_REASON"]
    observed_pairs = {(row.get("fault_type"), row.get("node_count")) for row in real_rows}
    for fault_type in required_faults:
        for node_count in P23_MANDATORY_COUNTS:
            if (fault_type, node_count) not in observed_pairs:
                errors.append(f"P23 missing real {fault_type} row for {node_count} nodes")
    unexpected = sorted({row.get("fault_type") for row in rows if row.get("fault_type") in P23_FORBIDDEN_FAULTS})
    if unexpected:
        errors.append(f"P23 must not emit P24 partition/split-brain rows: {unexpected}")
    command_path = base / "network_fault_command_log.jsonl"
    network_report_path = base / "network_fault_report.json"
    errors.extend(validate_artifact(command_path, ROOT / "schemas/artifact/command_log_entry.schema.json"))
    errors.extend(validate_artifact(network_report_path, ROOT / "schemas/artifact/network_fault_report.schema.json"))
    command_rows = load_jsonl(command_path) if command_path.exists() else []
    commands_by_fault: dict[str, set[str]] = {}
    forbidden_terms = ["su" + "do", "pf" + "ctl", "ip" + "tables", "nf" + "t", "ip" + " route", "route " + "add", "route " + "delete", "if" + "config", "network" + "setup"]
    for idx, command in enumerate(command_rows, start=1):
        text = json.dumps(command, sort_keys=True).lower()
        for term in forbidden_terms:
            if term in text:
                errors.append(f"network_fault_command_log.jsonl:{idx}: forbidden host mutation token {term!r}")
        if command.get("host_network_mutated") is not False:
            errors.append(f"network_fault_command_log.jsonl:{idx}: host_network_mutated must be false")
        fid = str(command.get("fault_id") or "")
        if fid:
            commands_by_fault.setdefault(fid, set()).add(str(command.get("command_kind")))
    network_report = load_json(network_report_path) if network_report_path.exists() else {}
    if network_report.get("status") != "PASS":
        errors.append("P23 network_fault_report status must be PASS")
    if "sandbox_proxy" not in set(network_report.get("safe_paths_exercised", [])):
        errors.append("P23 network_fault_report must record sandbox_proxy as exercised")

    for row in rows:
        label = row.get("fault_id", row.get("fault_type"))
        fault_type = row.get("fault_type")
        if row.get("phase_id") != "P23_FAULT_NETWORK_DELAY_LOSS_FLAP":
            errors.append(f"{label}: wrong phase_id {row.get('phase_id')!r}")
        if row.get("node_count") == 200:
            errors.append(f"{label}: P23 must not emit 200-node rows")
        if row.get("status") == "SKIPPED_WITH_REASON":
            errors.append(f"{label}: P23 mandatory network rows may not be skipped")
            continue
        if row.get("status") != "PASS":
            errors.append(f"{label}: P23 real rows must PASS")
        if row.get("real_valkey") is not True:
            errors.append(f"{label}: P23 real rows must record real_valkey=true")
        if row.get("implementation_path") not in {"sandbox_proxy", "container_netns_tc"}:
            errors.append(f"{label}: P23 real rows must use sandbox_proxy or container_netns_tc")
        if row.get("host_network_mutated") is not False:
            errors.append(f"{label}: host_network_mutated must be false")
        if row.get("physical_host_mutated") is not False:
            errors.append(f"{label}: physical_host_mutated must be false")
        params = row.get("fault_parameters") if isinstance(row.get("fault_parameters"), dict) else {}
        if not params.get("target_set"):
            errors.append(f"{label}: fault_parameters.target_set required")
        if fault_type == "network_delay":
            for field in ["delay_ms", "jitter_ms", "affected_direction", "duration_seconds"]:
                if field not in params:
                    errors.append(f"{label}: network_delay missing parameter {field}")
        if fault_type == "network_loss":
            for field in ["loss_percent", "correlation", "affected_direction", "duration_seconds"]:
                if field not in params:
                    errors.append(f"{label}: network_loss missing parameter {field}")
        if fault_type == "network_flap":
            for field in ["up_ms", "down_ms", "iterations", "duration_seconds"]:
                if field not in params:
                    errors.append(f"{label}: network_flap missing parameter {field}")
        observed = row.get("observed_impact") if isinstance(row.get("observed_impact"), dict) else {}
        if observed.get("effect_observed") is not True:
            errors.append(f"{label}: observed_impact.effect_observed must be true")
        stats = observed.get("proxy_stats") if isinstance(observed.get("proxy_stats"), dict) else {}
        if row.get("implementation_path") == "sandbox_proxy" and int(stats.get("accepted_connections", 0) or 0) <= 0:
            errors.append(f"{label}: sandbox_proxy rows require accepted connection counters")
        command_kinds = commands_by_fault.get(str(row.get("fault_id")), set())
        if "sandbox_proxy_apply" not in command_kinds or "sandbox_proxy_clear" not in command_kinds:
            errors.append(f"{label}: command log must include sandbox_proxy_apply and sandbox_proxy_clear")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    required = REQUIRED_FAULTS.get(args.phase)
    if not required:
        print(f"PASS fault matrix not required for phase={args.phase}")
        return 0

    base = ROOT / "artifacts" / "phases" / args.phase
    path = base / "fault_results.jsonl"
    errors: list[str] = []
    errors.extend(validate_artifact(path, ROOT / "schemas/artifact/fault_result.schema.json"))
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rows = load_jsonl(path)
    observed = {row.get("fault_type") for row in rows}
    missing = sorted(required - observed)
    if missing:
        errors.append(f"missing required fault rows: {missing}")
    for row in rows:
        label = row.get("fault_id", row.get("fault_type"))
        if row.get("implementation_path") not in SAFE_PATHS:
            errors.append(f"{label}: unsafe or unknown implementation_path={row.get('implementation_path')!r}")
        if row.get("implementation_path") == "unsupported_skipped_with_reason" and not row.get("reason"):
            errors.append(f"{label}: unsupported implementation path requires reason")
        if row.get("safety_scope_verified") is not True:
            errors.append(f"{label}: safety_scope_verified must be true")
        if row.get("cleanup_verified") is not True:
            errors.append(f"{label}: cleanup_verified must be true")
        if not row.get("workload_impact_ref"):
            errors.append(f"{label}: workload_impact_ref required")
        if not row.get("targets"):
            errors.append(f"{label}: targets required")
    if args.phase == "P22_FAULT_REPLICA_HOST_AZ_STOP":
        validate_p22(rows, base, errors)
    if args.phase == "P23_FAULT_NETWORK_DELAY_LOSS_FLAP":
        validate_p23(rows, base, errors)

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS fault matrix coverage phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
