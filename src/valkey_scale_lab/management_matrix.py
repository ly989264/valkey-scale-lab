from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__

REQUIRED_MANAGEMENT_OPERATIONS = [
    "create_cluster",
    "meet_nodes",
    "add_replica",
    "remove_replica",
    "remove_primary_drained_or_safe_replaced",
    "remove_failed_node",
    "reshard_slot_range",
    "reshard_with_keys",
    "rebalance_after_imbalance",
    "rolling_restart_replica_first",
    "rolling_restart_primary_safe",
]

RESHARD_REBALANCE_OPERATIONS = {"reshard_slot_range", "reshard_with_keys", "rebalance_after_imbalance"}
ROLLING_RESTART_OPERATIONS = {"rolling_restart_replica_first", "rolling_restart_primary_safe"}

COMMON_RESULT_FIELDS = [
    "schema_version",
    "artifact_type",
    "phase_id",
    "run_id",
    "scenario",
    "coverage_id",
    "operation_name",
    "operation_id",
    "node_count",
    "scale",
    "operation_status",
    "status_reason",
    "started_at_unix_ms",
    "ended_at_unix_ms",
    "operation_duration_ms",
    "wall_ms",
    "prepare_ms",
    "command_ms",
    "convergence_ms",
    "cleanup_ms",
    "before_topology_snapshot",
    "after_topology_snapshot",
    "before_topology_snapshot_ref",
    "after_topology_snapshot_ref",
    "topology_diff",
    "topology_diff_ref",
    "slot_diff",
    "role_diff",
    "cluster_state_before",
    "cluster_state_after",
    "known_nodes_before",
    "known_nodes_after",
    "fail_pfail_handshake_before",
    "fail_pfail_handshake_after",
    "command_count",
    "retry_count",
    "error_count",
    "command_log_refs",
    "workload_impact_ref",
    "cleanup_ref",
    "source_evidence_refs",
    "missing_fields",
]


def missing(field: str, reason: str, impact: str = "No value was invented; downstream consumers must treat this metric as unavailable.") -> dict[str, str]:
    return {"status": "MISSING", "field": field, "reason": reason, "impact": impact}


def skipped(field: str, reason: str, impact: str) -> dict[str, str]:
    return {"status": "SKIPPED_WITH_REASON", "field": field, "reason": reason, "impact": impact}


def fixture_nodes(node_count: int) -> list[dict[str, Any]]:
    primary_count = max(1, node_count // 2)
    replicas = max(0, node_count - primary_count)
    slots_per_primary = 16384 // primary_count
    nodes: list[dict[str, Any]] = []
    slot_start = 0
    for index in range(primary_count):
        slot_end = 16383 if index == primary_count - 1 else slot_start + slots_per_primary - 1
        nodes.append(
            {
                "logical_id": f"node-{index:04d}",
                "node_id": f"nodeid-{index:04d}",
                "role": "primary",
                "master_id": "",
                "status": "ok",
                "slots": [[slot_start, slot_end]],
            }
        )
        slot_start = slot_end + 1
    for replica_index in range(replicas):
        index = primary_count + replica_index
        master_index = replica_index % primary_count
        nodes.append(
            {
                "logical_id": f"node-{index:04d}",
                "node_id": f"nodeid-{index:04d}",
                "role": "replica",
                "master_id": f"nodeid-{master_index:04d}",
                "status": "ok",
                "slots": [],
            }
        )
    return nodes


def build_topology_snapshot(
    *,
    phase_id: str,
    run_id: str,
    operation_id: str,
    label: str,
    nodes: list[dict[str, Any]],
    cluster_state: str = "ok",
) -> dict[str, Any]:
    role_counts: dict[str, int] = {}
    slot_ranges: list[dict[str, Any]] = []
    for node in nodes:
        role = str(node.get("role", "MISSING"))
        role_counts[role] = role_counts.get(role, 0) + 1
        for slot_range in node.get("slots", []) or []:
            if isinstance(slot_range, list) and len(slot_range) == 2:
                slot_ranges.append({"node_id": node.get("node_id", "MISSING"), "start": slot_range[0], "end": slot_range[1]})
    return {
        "schema_version": "v1",
        "artifact_type": "management_topology_snapshot",
        "phase_id": phase_id,
        "run_id": run_id,
        "operation_id": operation_id,
        "snapshot_id": f"{operation_id}-{label}",
        "label": label,
        "cluster_state": cluster_state,
        "known_nodes": len(nodes),
        "fail_count": sum(1 for node in nodes if node.get("status") == "fail"),
        "pfail_count": sum(1 for node in nodes if node.get("status") == "pfail"),
        "handshake_count": sum(1 for node in nodes if node.get("status") == "handshake"),
        "role_counts": role_counts,
        "slot_ranges": slot_ranges,
        "nodes": nodes,
    }


def diff_topology(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_roles = before.get("role_counts", {}) if isinstance(before.get("role_counts"), dict) else {}
    after_roles = after.get("role_counts", {}) if isinstance(after.get("role_counts"), dict) else {}
    roles = sorted(set(before_roles) | set(after_roles))
    role_diff = {role: int(after_roles.get(role, 0) or 0) - int(before_roles.get(role, 0) or 0) for role in roles}
    before_slots = {(item.get("node_id"), item.get("start"), item.get("end")) for item in before.get("slot_ranges", []) if isinstance(item, dict)}
    after_slots = {(item.get("node_id"), item.get("start"), item.get("end")) for item in after.get("slot_ranges", []) if isinstance(item, dict)}
    moved_slots = sorted([list(item) for item in (before_slots ^ after_slots)], key=str)
    slot_diff = {
        "before_range_count": len(before_slots),
        "after_range_count": len(after_slots),
        "moved_slot_ranges": moved_slots,
        "moved_slot_range_count": len(moved_slots),
    }
    return {
        "slot_diff": slot_diff,
        "role_diff": role_diff,
        "known_nodes_delta": int(after.get("known_nodes", 0) or 0) - int(before.get("known_nodes", 0) or 0),
        "fail_pfail_handshake_delta": {
            "fail": int(after.get("fail_count", 0) or 0) - int(before.get("fail_count", 0) or 0),
            "pfail": int(after.get("pfail_count", 0) or 0) - int(before.get("pfail_count", 0) or 0),
            "handshake": int(after.get("handshake_count", 0) or 0) - int(before.get("handshake_count", 0) or 0),
        },
        "changed_nodes": [],
        "moved_slots": moved_slots,
        "status": "PASS",
    }


def build_management_operation_result(
    *,
    phase_id: str,
    run_id: str,
    scenario: str,
    operation_name: str,
    operation_index: int,
    node_count: int,
    command_refs: list[str],
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
    operation_status: str = "PASS",
    status_reason: str = "Management operation fixture completed with traceable command, topology, workload, and cleanup evidence.",
) -> dict[str, Any]:
    operation_id = f"m1-s04-{operation_index:02d}-{operation_name}"
    diff = diff_topology(before_snapshot, after_snapshot)
    duration = float(40 + operation_index * 7)
    result: dict[str, Any] = {
        "schema_version": "v1",
        "artifact_type": "management_operation_result",
        "phase_id": phase_id,
        "run_id": run_id,
        "scenario": scenario,
        "coverage_id": f"{node_count}.management.{operation_name}",
        "operation_name": operation_name,
        "operation_id": operation_id,
        "node_count": node_count,
        "scale": node_count,
        "operation_status": operation_status,
        "status_reason": status_reason,
        "started_at_unix_ms": 1760000000000 + operation_index * 1000,
        "ended_at_unix_ms": 1760000000000 + operation_index * 1000 + int(duration),
        "operation_duration_ms": duration,
        "duration_ms": duration,
        "wall_ms": duration,
        "prepare_ms": 3.0,
        "command_ms": duration - 12.0,
        "convergence_ms": 8.0,
        "cleanup_ms": 1.0,
        "before_topology_snapshot": before_snapshot,
        "after_topology_snapshot": after_snapshot,
        "before_topology_snapshot_ref": f"management_topology_snapshots.jsonl#{before_snapshot['snapshot_id']}",
        "after_topology_snapshot_ref": f"management_topology_snapshots.jsonl#{after_snapshot['snapshot_id']}",
        "topology_diff": diff,
        "topology_diff_ref": f"management_topology_diffs.jsonl#{operation_id}",
        "slot_diff": diff["slot_diff"],
        "role_diff": diff["role_diff"],
        "cluster_state_before": before_snapshot.get("cluster_state", "MISSING"),
        "cluster_state_after": after_snapshot.get("cluster_state", "MISSING"),
        "known_nodes_before": before_snapshot.get("known_nodes", "MISSING"),
        "known_nodes_after": after_snapshot.get("known_nodes", "MISSING"),
        "fail_pfail_handshake_before": {
            "fail": before_snapshot.get("fail_count", 0),
            "pfail": before_snapshot.get("pfail_count", 0),
            "handshake": before_snapshot.get("handshake_count", 0),
        },
        "fail_pfail_handshake_after": {
            "fail": after_snapshot.get("fail_count", 0),
            "pfail": after_snapshot.get("pfail_count", 0),
            "handshake": after_snapshot.get("handshake_count", 0),
        },
        "command_count": len(command_refs),
        "retry_count": 0,
        "error_count": 0,
        "command_log_refs": command_refs,
        "workload_impact_ref": f"management_workload_impact.json#{operation_id}",
        "cleanup_ref": "cleanup_report.json",
        "source_evidence_refs": [
            "management_ops_matrix.json",
            "management_operation_results.jsonl",
            "management_topology_snapshots.jsonl",
            "management_topology_diffs.jsonl",
            "command_log.jsonl",
            "management_workload_impact.json",
            "cleanup_report.json",
        ],
        "missing_fields": [],
        "errors_by_type": {},
        "cluster_known_nodes_before": before_snapshot.get("known_nodes", "MISSING"),
        "cluster_known_nodes_after": after_snapshot.get("known_nodes", "MISSING"),
        "slots_before": 16384,
        "slots_after": 16384,
        "workload_window_ref": f"management_workload_impact.json#{operation_id}",
        "command_log_ref": command_refs[0] if command_refs else missing("command_log_ref", "No command references were attached."),
        "topology_before_ref": f"management_topology_snapshots.jsonl#{before_snapshot['snapshot_id']}",
        "topology_after_ref": f"management_topology_snapshots.jsonl#{after_snapshot['snapshot_id']}",
        "topology_ref": "management_topology_snapshots.jsonl",
    }
    if operation_name in RESHARD_REBALANCE_OPERATIONS:
        result.update(
            {
                "slots_moved": 64 if operation_name != "rebalance_after_imbalance" else 128,
                "keys_moved": 12 if operation_name == "reshard_with_keys" else 0,
                "bytes_migrated": missing("bytes_migrated", "Fixture and current Valkey command path do not expose migrated byte counts."),
                "slot_balance_before": {"status": "PASS", "min_slots": 5461, "max_slots": 5462, "imbalance": 1},
                "slot_balance_after": {"status": "PASS", "min_slots": 5461, "max_slots": 5462, "imbalance": 1},
                "imbalance_delta": 0,
                "imbalance_before": 1,
                "imbalance_after": 1,
                "movement_ids": [f"{operation_id}-move-0001"],
                "source_node_id": "nodeid-0000",
                "target_node_id": "nodeid-0001",
                "slot_coverage_complete": True,
                "post_move_writable": True,
            }
        )
    else:
        result.update(
            {
                "slots_moved": 0,
                "keys_moved": 0,
                "bytes_migrated": missing("bytes_migrated", "Operation does not migrate keys or expose byte counts."),
                "slot_balance_before": {"status": "PASS", "min_slots": 5461, "max_slots": 5462, "imbalance": 1},
                "slot_balance_after": {"status": "PASS", "min_slots": 5461, "max_slots": 5462, "imbalance": 1},
                "imbalance_delta": 0,
            }
        )
    if operation_name in ROLLING_RESTART_OPERATIONS:
        result.update(
            {
                "per_node_stop_ms": [{"logical_id": "node-0003", "value_ms": 11.0}],
                "per_node_restart_ms": [{"logical_id": "node-0003", "value_ms": 14.0}],
                "per_node_rejoin_ms": [{"logical_id": "node-0003", "value_ms": 18.0}],
                "per_node_unavailable_ms": [{"logical_id": "node-0003", "value_ms": 31.0}],
                "cluster_impact_ms": 6.0,
                "restart_count": 1,
                "health_gate_count": 1,
                "max_concurrent_restarts": 1,
                "rolling_restart_plan_ref": "rolling_restart_plan.json",
                "rolling_restart_results_ref": "rolling_restart_results.jsonl",
            }
        )
    return result


def build_topology_diff_row(phase_id: str, run_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": "management_topology_diff",
        "phase_id": phase_id,
        "run_id": run_id,
        "operation_id": result["operation_id"],
        "before_snapshot_ref": result["before_topology_snapshot_ref"],
        "after_snapshot_ref": result["after_topology_snapshot_ref"],
        **result["topology_diff"],
    }


def write_management_matrix_artifacts(
    artifacts_dir: str | Path,
    *,
    phase_id: str,
    run_id: str,
    scenario: str,
    node_count: int = 6,
    operation_status: str = "PASS",
) -> dict[str, Any]:
    artifacts = Path(artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    nodes = fixture_nodes(node_count)
    command_rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    diffs: list[dict[str, Any]] = []
    for index, operation_name in enumerate(REQUIRED_MANAGEMENT_OPERATIONS, start=1):
        operation_id = f"m1-s04-{index:02d}-{operation_name}"
        before = build_topology_snapshot(phase_id=phase_id, run_id=run_id, operation_id=operation_id, label="before", nodes=nodes)
        after = build_topology_snapshot(phase_id=phase_id, run_id=run_id, operation_id=operation_id, label="after", nodes=nodes)
        command_id = f"cmd-{index:06d}"
        command_rows.append(
            {
                "schema_version": "v1",
                "artifact_type": "command_log_entry",
                "phase_id": phase_id,
                "run_id": run_id,
                "scenario": scenario,
                "command_id": command_id,
                "operation_id": operation_id,
                "step_id": operation_name,
                "command_kind": "management_operation",
                "command": ["valkey-cli", "cluster", operation_name],
                "started_at_unix_ms": 1760000000000 + index * 1000,
                "ended_at_unix_ms": 1760000000000 + index * 1000 + 10,
                "duration_ms": 10.0,
                "timeout_ms": 30000,
                "status": "PASS",
                "exit_code": 0,
                "retry_index": 0,
                "stdout_ref": f"command-logs/{command_id}.stdout.txt",
                "stderr_ref": f"command-logs/{command_id}.stderr.txt",
            }
        )
        result = build_management_operation_result(
            phase_id=phase_id,
            run_id=run_id,
            scenario=scenario,
            operation_name=operation_name,
            operation_index=index,
            node_count=node_count,
            command_refs=[f"command_log.jsonl#{command_id}"],
            before_snapshot=before,
            after_snapshot=after,
            operation_status=operation_status,
            status_reason="Fixture operation carries the full M1-S04 evidence contract.",
        )
        snapshots.extend([before, after])
        results.append(result)
        diffs.append(build_topology_diff_row(phase_id, run_id, result))
    _write_jsonl(artifacts / "command_log.jsonl", command_rows)
    _write_jsonl(artifacts / "management_operation_results.jsonl", results)
    _write_jsonl(artifacts / "management_topology_snapshots.jsonl", snapshots)
    _write_jsonl(artifacts / "management_topology_diffs.jsonl", diffs)
    workload_impact = {
        "schema_version": "v1",
        "artifact_type": "management_workload_impact",
        "phase_id": phase_id,
        "run_id": run_id,
        "scenario": scenario,
        "status": operation_status,
        "operations": [
            {
                "operation_id": row["operation_id"],
                "operation_name": row["operation_name"],
                "coverage_id": row["coverage_id"],
                "status": row["operation_status"],
                "baseline_qps": 1000.0,
                "during_qps": 980.0,
                "error_rate": 0.0,
                "latency_p99_ms": 4.2,
            }
            for row in results
        ],
    }
    matrix = {
        "schema_version": "v1",
        "artifact_type": "management_ops_matrix",
        "phase_id": phase_id,
        "run_id": run_id,
        "scenario": scenario,
        "status": operation_status,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "required_operations": REQUIRED_MANAGEMENT_OPERATIONS,
        "operations": [
            {
                "operation_name": row["operation_name"],
                "operation_id": row["operation_id"],
                "coverage_id": row["coverage_id"],
                "node_count": row["node_count"],
                "scale": row["scale"],
                "operation_status": row["operation_status"],
                "operation_result_ref": f"management_operation_results.jsonl#{row['operation_id']}",
                "before_topology_snapshot_ref": row["before_topology_snapshot_ref"],
                "after_topology_snapshot_ref": row["after_topology_snapshot_ref"],
                "topology_diff_ref": row["topology_diff_ref"],
                "command_count": row["command_count"],
                "command_log_refs": row["command_log_refs"],
                "workload_impact_ref": row["workload_impact_ref"],
                "cleanup_ref": row["cleanup_ref"],
            }
            for row in results
        ],
    }
    _write_json(artifacts / "management_ops_matrix.json", matrix)
    _write_json(artifacts / "management_workload_impact.json", workload_impact)
    _write_json(artifacts / "command_audit_summary.json", _command_audit_summary(phase_id, run_id, scenario, command_rows))
    _write_json(artifacts / "rolling_restart_plan.json", {"schema_version": "v1", "artifact_type": "rolling_restart_plan", "phase_id": phase_id, "run_id": run_id, "status": "PASS", "operations": [row for row in results if row["operation_name"] in ROLLING_RESTART_OPERATIONS]})
    _write_jsonl(artifacts / "rolling_restart_results.jsonl", [row for row in results if row["operation_name"] in ROLLING_RESTART_OPERATIONS])
    _write_json(artifacts / "rebalance_summary.json", {"schema_version": "v1", "artifact_type": "rebalance_summary", "phase_id": phase_id, "run_id": run_id, "status": "PASS", "operations": [row for row in results if row["operation_name"] in RESHARD_REBALANCE_OPERATIONS]})
    return matrix


def load_management_artifacts(artifacts_dir: str | Path) -> dict[str, Any]:
    base = Path(artifacts_dir)
    return {
        "matrix": _load_json(base / "management_ops_matrix.json"),
        "operation_results": _load_jsonl(base / "management_operation_results.jsonl"),
        "topology_diffs": _load_jsonl(base / "management_topology_diffs.jsonl"),
        "workload_impact": _load_json(base / "management_workload_impact.json"),
    }


def _command_audit_summary(phase_id: str, run_id: str, scenario: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": "command_audit_summary",
        "phase_id": phase_id,
        "run_id": run_id,
        "scenario": scenario,
        "status": "PASS",
        "command_log_ref": "command_log.jsonl",
        "total_commands": len(rows),
        "pass_count": len(rows),
        "failure_count": 0,
        "timeout_count": 0,
        "retry_count": 0,
        "missing_or_skipped": [],
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
