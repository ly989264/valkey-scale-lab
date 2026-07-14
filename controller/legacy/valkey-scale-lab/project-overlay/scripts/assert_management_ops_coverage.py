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
from schema_validator import load_json  # noqa: E402

REQUIRED_OPS = {
    "P17_MANAGEMENT_REMOVE_NODE": {"remove_replica", "remove_primary_drained", "remove_failed_node"},
    "P18_MANAGEMENT_RESHARD_REBALANCE": {"reshard_slot_range", "reshard_with_keys", "rebalance_after_imbalance"},
    "P19_MANAGEMENT_ROLLING_RESTART": {"rolling_restart_replica_first", "rolling_restart_primary_safe"},
}

REQUIRED_ROWS = {
    "P17_MANAGEMENT_REMOVE_NODE": {
        ("remove_replica", 6),
        ("remove_replica", 10),
        ("remove_primary_drained", 6),
        ("remove_primary_drained", 10),
        ("remove_failed_node", 6),
        ("remove_failed_node", 10),
    },
    "P18_MANAGEMENT_RESHARD_REBALANCE": {
        ("reshard_slot_range", 6),
        ("reshard_slot_range", 10),
        ("reshard_with_keys", 6),
        ("reshard_with_keys", 10),
        ("rebalance_after_imbalance", 6),
        ("rebalance_after_imbalance", 10),
    },
    "P19_MANAGEMENT_ROLLING_RESTART": {
        ("rolling_restart_replica_first", 6),
        ("rolling_restart_replica_first", 10),
        ("rolling_restart_primary_safe", 6),
        ("rolling_restart_primary_safe", 10),
    },
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _missing_reason_present(row: dict[str, Any], field: str) -> bool:
    for item in row.get("missing_fields", []):
        if isinstance(item, dict) and item.get("field") == field and item.get("status") == "MISSING" and item.get("reason"):
            return True
    reasons = row.get("missing_reasons", {})
    return isinstance(reasons, dict) and bool(reasons.get(field))


def _validate_p19_rolling_restart(
    plan: dict[str, Any],
    restart_rows: list[dict[str, Any]],
    command_rows: list[dict[str, Any]],
    operation_rows: list[dict[str, Any]],
    required_rows: set[tuple[str, int]],
    errors: list[str],
) -> None:
    operation_ids = {f"{operation}-{count:02d}" for operation, count in required_rows}
    row_by_operation = {str(row.get("operation_id")): row for row in operation_rows}
    command_by_id = {str(row.get("command_id")): row for row in command_rows if row.get("command_id")}
    operations = {str(item.get("operation_id")): item for item in plan.get("operations", []) if isinstance(item, dict)}
    missing_plan_ops = sorted(operation_ids - set(operations))
    if missing_plan_ops:
        errors.append(f"P19 rolling_restart_plan missing operation ids: {missing_plan_ops}")

    for operation_id in sorted(operation_ids):
        operation = row_by_operation.get(operation_id, {})
        plan_operation = operations.get(operation_id, {})
        op_name = str(operation.get("operation_name") or plan_operation.get("operation_name") or operation_id)
        try:
            node_count = int(operation.get("node_count") or plan_operation.get("node_count") or operation_id.rsplit("-", 1)[1])
        except ValueError:
            node_count = 0
        label = f"{op_name}[{node_count}]"
        plan_order = plan_operation.get("restart_order", [])
        results = sorted(
            [row for row in restart_rows if row.get("operation_id") == operation_id],
            key=lambda row: int(row.get("sequence", 0) or 0),
        )
        if len(plan_order) != node_count:
            errors.append(f"{label}: plan restart_order length must equal node_count")
        if len(results) != node_count:
            errors.append(f"{label}: rolling_restart_results rows must equal node_count")
        if plan_operation.get("max_concurrent_restarts") != 1:
            errors.append(f"{label}: plan max_concurrent_restarts must be 1")
        gate = plan_operation.get("health_gate", {})
        if not isinstance(gate, dict) or gate.get("required_after_each_restart") is not True:
            errors.append(f"{label}: plan health_gate.required_after_each_restart must be true")

        planned_sequences = [int(item.get("sequence", 0) or 0) for item in plan_order if isinstance(item, dict)]
        result_sequences = [int(item.get("sequence", 0) or 0) for item in results]
        expected_sequences = list(range(1, node_count + 1))
        if planned_sequences != expected_sequences:
            errors.append(f"{label}: plan sequence must be contiguous 1..node_count")
        if result_sequences != expected_sequences:
            errors.append(f"{label}: result sequence must be contiguous 1..node_count")
        planned_ids = [item.get("logical_node_id") for item in plan_order if isinstance(item, dict)]
        result_ids = [item.get("node_logical_id") for item in results]
        if planned_ids != result_ids:
            errors.append(f"{label}: plan restart order must match execution order")

        if op_name == "rolling_restart_replica_first":
            roles = [str(item.get("planned_role")) for item in plan_order if isinstance(item, dict)]
            first_primary = next((index for index, role in enumerate(roles) if role == "primary"), None)
            last_replica = max((index for index, role in enumerate(roles) if role == "replica"), default=-1)
            if first_primary is None or last_replica < 0 or first_primary < last_replica:
                errors.append(f"{label}: replica-first plan must restart all replicas before any primary")

        previous_health_completed: int | None = None
        for result in results:
            sequence = result.get("sequence")
            node_label = f"{label} seq={sequence} node={result.get('node_logical_id')}"
            if result.get("max_concurrent_restarts") != 1:
                errors.append(f"{node_label}: max_concurrent_restarts must be 1")
            if result.get("command_status") != "PASS":
                errors.append(f"{node_label}: command_status must be PASS")
            command = command_by_id.get(str(result.get("command_ref")))
            if not command:
                errors.append(f"{node_label}: command_ref missing from management_command_log")
            elif command.get("command_kind") != "owned_container_restart" or command.get("status") != "PASS":
                errors.append(f"{node_label}: command_ref must point to passing owned_container_restart command")
            if result.get("health_gate_status") != "PASS":
                errors.append(f"{node_label}: health_gate_status must be PASS")
            if result.get("cluster_state_after_gate") != "ok":
                errors.append(f"{node_label}: cluster_state_after_gate must be ok")
            if result.get("slots_after_gate") != 16384:
                errors.append(f"{node_label}: slots_after_gate must be 16384")
            if result.get("known_nodes_after_gate") != node_count:
                errors.append(f"{node_label}: known_nodes_after_gate must equal node_count")
            for started_field, ended_field in [
                ("restart_started_at_ms", "restart_completed_at_ms"),
                ("health_gate_started_at_ms", "health_gate_completed_at_ms"),
            ]:
                started = result.get(started_field)
                ended = result.get(ended_field)
                if not isinstance(started, int) or not isinstance(ended, int) or ended < started:
                    errors.append(f"{node_label}: invalid {started_field}/{ended_field} timing")
            if previous_health_completed is not None and isinstance(result.get("restart_started_at_ms"), int):
                if int(result["restart_started_at_ms"]) < previous_health_completed:
                    errors.append(f"{node_label}: next restart started before previous health gate completed")
            if isinstance(result.get("health_gate_completed_at_ms"), int):
                previous_health_completed = int(result["health_gate_completed_at_ms"])
            if op_name == "rolling_restart_primary_safe":
                if result.get("role_before_restart") == "primary":
                    if result.get("primary_safe_path") != "cluster_failover_takeover_before_owned_container_restart":
                        errors.append(f"{node_label}: primary restart requires safe primary path")
                    for metric in ["promotion_latency_ms", "cluster_recovery_latency_ms"]:
                        if not isinstance(result.get(metric), (int, float)):
                            errors.append(f"{node_label}: primary restart requires numeric {metric}")
                    for metric in ["read_unavailability_ms", "write_unavailability_ms"]:
                        if result.get(metric) == "MISSING" and not _missing_reason_present(result, metric):
                            errors.append(f"{node_label}: MISSING {metric} requires reason")
                else:
                    for metric in ["promotion_latency_ms", "cluster_recovery_latency_ms"]:
                        if result.get(metric) == "MISSING" and not _missing_reason_present(result, metric):
                            errors.append(f"{node_label}: MISSING {metric} requires reason")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    required_ops = REQUIRED_OPS.get(args.phase)
    if not required_ops:
        print(f"PASS management coverage not required for phase={args.phase}")
        return 0

    base = ROOT / "artifacts" / "phases" / args.phase
    errors: list[str] = []
    matrix = base / "management_ops_matrix.json"
    results = base / "management_operation_results.jsonl"
    errors.extend(validate_artifact(matrix, ROOT / "schemas/artifact/management_ops_matrix.schema.json"))
    errors.extend(validate_artifact(results, ROOT / "schemas/artifact/management_operation_result.schema.json"))
    slot_movements_path = base / "reshard_slot_movements.jsonl"
    rebalance_path = base / "rebalance_summary.json"
    if args.phase == "P18_MANAGEMENT_RESHARD_REBALANCE":
        errors.extend(validate_artifact(slot_movements_path, ROOT / "schemas/artifact/slot_movement.schema.json"))
        errors.extend(validate_artifact(rebalance_path, ROOT / "schemas/artifact/rebalance_summary.schema.json"))
    rolling_plan_path = base / "rolling_restart_plan.json"
    rolling_results_path = base / "rolling_restart_results.jsonl"
    command_log_path = base / "management_command_log.jsonl"
    if args.phase == "P19_MANAGEMENT_ROLLING_RESTART":
        errors.extend(validate_artifact(rolling_plan_path, ROOT / "schemas/artifact/rolling_restart_plan.schema.json"))
        errors.extend(validate_artifact(rolling_results_path, ROOT / "schemas/artifact/rolling_restart_result.schema.json"))
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rows = load_jsonl(results)
    slot_movements = load_jsonl(slot_movements_path) if args.phase == "P18_MANAGEMENT_RESHARD_REBALANCE" and slot_movements_path.exists() else []
    rolling_results = load_jsonl(rolling_results_path) if args.phase == "P19_MANAGEMENT_ROLLING_RESTART" and rolling_results_path.exists() else []
    command_rows = load_jsonl(command_log_path) if command_log_path.exists() else []
    required_rows = REQUIRED_ROWS.get(args.phase)
    if required_rows:
        observed_rows = {(row.get("operation_name"), row.get("node_count")) for row in rows}
        missing_rows = sorted(required_rows - observed_rows)
        if missing_rows:
            errors.append(f"missing required operation/node_count rows: {missing_rows}")
        matrix_rows = {
            (row.get("operation_name"), row.get("node_count"))
            for row in load_json(matrix).get("operations", [])
        }
        matrix_missing = sorted(required_rows - matrix_rows)
        if matrix_missing:
            errors.append(f"management_ops_matrix missing required rows: {matrix_missing}")
    else:
        observed_ops = {row.get("operation_name") for row in rows}
        missing = sorted(required_ops - observed_ops)
        if missing:
            errors.append(f"missing required operation rows: {missing}")
    for row in rows:
        label = f"{row.get('operation_name')}[{row.get('node_count')}]"
        status = row.get("operation_status")
        if required_rows and (row.get("operation_name"), row.get("node_count")) in required_rows and status != "PASS":
            errors.append(f"{label}: required {args.phase} row must PASS, got {status}")
        if status == "PASS" and row.get("real_execution_verified") is not True:
            errors.append(f"{label}: PASS requires real_execution_verified=true")
        if status in {"SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON", "MISSING"} and not row.get("reason"):
            errors.append(f"{label}: {status} requires reason")
        if status == "PASS":
            for field in ["started_at_unix_ms", "ended_at_unix_ms", "wall_ms", "command_ms", "convergence_ms"]:
                if row.get(field) == "MISSING":
                    errors.append(f"{label}: PASS cannot have MISSING {field}")
            if required_rows and (row.get("operation_name"), row.get("node_count")) in required_rows:
                if row.get("removed_node_absent") is not True:
                    if args.phase == "P17_MANAGEMENT_REMOVE_NODE":
                        errors.append(f"{label}: removed_node_absent must be true")
                if row.get("cluster_state_before") != "ok":
                    errors.append(f"{label}: cluster_state_before must be ok")
                if row.get("cluster_state_after") != "ok":
                    errors.append(f"{label}: cluster_state_after must be ok")
                if row.get("slots_before") != 16384:
                    errors.append(f"{label}: slots_before must be 16384")
                if row.get("slots_after") != 16384:
                    errors.append(f"{label}: slots_after must be 16384")
                if row.get("sidecar_cleanup_status") != "PASS":
                    errors.append(f"{label}: sidecar_cleanup_status must be PASS")
                if args.phase == "P17_MANAGEMENT_REMOVE_NODE":
                    if row.get("observed_nodes_after") != int(row.get("node_count", 0)) - 1:
                        errors.append(f"{label}: observed_nodes_after must equal node_count - 1")
                    cleanup = row.get("removed_resource_cleanup")
                    if not isinstance(cleanup, dict) or cleanup.get("status") != "PASS":
                        errors.append(f"{label}: removed_resource_cleanup.status must be PASS")
                    if not row.get("removed_node_id"):
                        errors.append(f"{label}: removed_node_id required")
                    if not row.get("target_logical_id"):
                        errors.append(f"{label}: target_logical_id required")
                if args.phase == "P18_MANAGEMENT_RESHARD_REBALANCE":
                    if int(row.get("slots_moved", 0) or 0) <= 0:
                        errors.append(f"{label}: slots_moved must be > 0")
                    if row.get("slot_coverage_complete") is not True:
                        errors.append(f"{label}: slot_coverage_complete must be true")
                    if row.get("post_move_writable") is not True:
                        errors.append(f"{label}: post_move_writable must be true")
                    if not row.get("source_node_id") or not row.get("target_node_id"):
                        errors.append(f"{label}: source_node_id and target_node_id required")
                    if not row.get("movement_ids"):
                        errors.append(f"{label}: movement_ids required")
                    if row.get("operation_name") == "reshard_with_keys":
                        if int(row.get("keys_moved", 0) or 0) <= 0:
                            errors.append(f"{label}: keys_moved must be > 0")
                        if row.get("moved_keys_readable") is not True:
                            errors.append(f"{label}: moved_keys_readable must be true")
                    if row.get("operation_name") == "rebalance_after_imbalance":
                        before = row.get("imbalance_before")
                        after = row.get("imbalance_after")
                        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)) or not before > after:
                            errors.append(f"{label}: imbalance_before must be greater than imbalance_after")
                if args.phase == "P19_MANAGEMENT_ROLLING_RESTART":
                    if int(row.get("restart_count", 0) or 0) != int(row.get("node_count", 0) or 0):
                        errors.append(f"{label}: restart_count must equal node_count")
                    if int(row.get("health_gate_count", 0) or 0) != int(row.get("node_count", 0) or 0):
                        errors.append(f"{label}: health_gate_count must equal node_count")
                    if row.get("max_concurrent_restarts") != 1:
                        errors.append(f"{label}: max_concurrent_restarts must be 1")
        if not row.get("workload_window_ref"):
            errors.append(f"{label}: workload_window_ref required")
        if not isinstance(row.get("errors_by_type"), dict):
            errors.append(f"{label}: errors_by_type must be object")

    if args.phase == "P18_MANAGEMENT_RESHARD_REBALANCE":
        if not slot_movements:
            errors.append("P18 requires non-empty reshard_slot_movements.jsonl")
        movement_ops = {row.get("operation_id") for row in slot_movements}
        expected_ops = {f"{op}-{count:02d}" for op, count in REQUIRED_ROWS[args.phase]}
        missing_movement_ops = sorted(expected_ops - movement_ops)
        if missing_movement_ops:
            errors.append(f"P18 slot movements missing operation ids: {missing_movement_ops}")
        for movement in slot_movements:
            label = str(movement.get("movement_id", "unknown"))
            if movement.get("status") != "PASS":
                errors.append(f"{label}: slot movement status must be PASS")
            if int(movement.get("slot_count", 0) or 0) <= 0:
                errors.append(f"{label}: slot_count must be > 0")
            if not movement.get("source_node_id") or not movement.get("target_node_id"):
                errors.append(f"{label}: source_node_id and target_node_id required")
        if rebalance_path.exists():
            rebalance = load_json(rebalance_path)
            if rebalance.get("status") != "PASS":
                errors.append("rebalance_summary status must be PASS")
            before = rebalance.get("imbalance_before")
            after = rebalance.get("imbalance_after")
            if not isinstance(before, (int, float)) or not isinstance(after, (int, float)) or not before > after:
                errors.append("rebalance_summary imbalance_before must be greater than imbalance_after")

    if args.phase == "P19_MANAGEMENT_ROLLING_RESTART":
        if not rolling_results:
            errors.append("P19 requires non-empty rolling_restart_results.jsonl")
        rolling_plan = load_json(rolling_plan_path) if rolling_plan_path.exists() else {}
        _validate_p19_rolling_restart(rolling_plan, rolling_results, command_rows, rows, required_rows or set(), errors)

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS management operation coverage phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
