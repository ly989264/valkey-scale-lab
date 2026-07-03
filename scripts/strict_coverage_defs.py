#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STRICT_COVERAGE_STAGE = "P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER"
SCHEMA_VERSION = "v1"
DETERMINISTIC_CREATED_AT = "2026-07-03T00:00:00Z"
REAL_SCALES = (50, 100, 200)
DRY_RUN_SCALES = (201, 250, 300, 500, 1000)

LIFECYCLE_ROWS = (
    "config_validate",
    "resource_preflight",
    "plan_cluster",
    "create_cluster",
    "meet_nodes",
    "assign_slots",
    "add_replica",
    "baseline_workload",
    "telemetry_collect",
    "analysis_build",
    "report_render",
    "cleanup_verify",
)
MANAGEMENT_ROWS = (
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
)
FAULT_ROWS = (
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
)
DRY_RUN_ROWS = (
    "config_validate_dry_run",
    "resource_preflight_dry_run",
    "plan_cluster_dry_run",
    "placement_schedule_dry_run",
    "port_directory_collision_check_dry_run",
    "artifact_schema_projection_dry_run",
    "no_runtime_created_proof",
    "report_projection_dry_run",
)

MANAGEMENT_STAGE_BY_SCALE = {
    50: "P30_MANAGEMENT_MATRIX_50_REAL",
    100: "P31_MANAGEMENT_MATRIX_100_REAL",
    200: "P32_MANAGEMENT_MATRIX_200_REAL",
}
FAULT_STAGE_BY_SCALE = {
    50: "P33_FAULT_FAILOVER_MATRIX_50_REAL",
    100: "P34_FAULT_FAILOVER_MATRIX_100_REAL",
    200: "P35_FAULT_FAILOVER_MATRIX_200_REAL",
}
FULL_FLOW_STAGE = "P36_FULL_FLOW_E2E_50_100_200_REAL"
DRY_RUN_STAGE = "P37_200_PLUS_DRY_RUN_SUPPORT"

EXPECTED_COUNTS = {
    "lifecycle": len(REAL_SCALES) * len(LIFECYCLE_ROWS),
    "management": len(REAL_SCALES) * len(MANAGEMENT_ROWS),
    "fault": len(REAL_SCALES) * len(FAULT_ROWS),
    "dry_run": len(DRY_RUN_SCALES) * len(DRY_RUN_ROWS),
}
EXPECTED_TOTAL_ROWS = sum(EXPECTED_COUNTS.values())

SOURCE_SPEC_REFS = [
    "docs/codex/goal-loop-strict/06_COVERAGE_REGISTRY_SPEC.md",
    "docs/codex/goal-loop-strict/08_MANAGEMENT_OPERATION_MATRIX_SPEC.md",
    "docs/codex/goal-loop-strict/09_FAULT_FAILOVER_MATRIX_SPEC.md",
    "docs/codex/goal-loop-strict/10_SCALE_EXECUTION_POLICY.md",
]

CSV_COLUMNS = [
    "coverage_id",
    "scale",
    "node_count",
    "category",
    "row_name",
    "stage_owner",
    "required",
    "execution_mode",
    "status",
    "status_reason",
    "source_artifacts",
    "validation_artifacts",
    "metric_refs",
    "cleanup_ref",
    "review_ref",
    "commit_sha",
]


@dataclass(frozen=True)
class RequiredRow:
    scale: int
    category: str
    row_name: str
    stage_owner: str
    execution_mode: str

    @property
    def coverage_id(self) -> str:
        return f"{self.scale}.{self.category}.{self.row_name}"


def required_row_specs() -> list[RequiredRow]:
    rows: list[RequiredRow] = []
    for scale in REAL_SCALES:
        rows.extend(RequiredRow(scale, "lifecycle", name, FULL_FLOW_STAGE, "real") for name in LIFECYCLE_ROWS)
        rows.extend(
            RequiredRow(scale, "management", name, MANAGEMENT_STAGE_BY_SCALE[scale], "real")
            for name in MANAGEMENT_ROWS
        )
        rows.extend(RequiredRow(scale, "fault", name, FAULT_STAGE_BY_SCALE[scale], "real") for name in FAULT_ROWS)
    for scale in DRY_RUN_SCALES:
        rows.extend(RequiredRow(scale, "dry_run", name, DRY_RUN_STAGE, "dry_run") for name in DRY_RUN_ROWS)
    return sorted(rows, key=lambda row: (row.scale, category_sort_key(row.category), row.row_name))


def category_sort_key(category: str) -> int:
    return {"lifecycle": 0, "management": 1, "fault": 2, "dry_run": 3}.get(category, 99)


def expected_rows_by_id() -> dict[str, RequiredRow]:
    return {row.coverage_id: row for row in required_row_specs()}


def empty_pending_row(spec: RequiredRow) -> dict[str, Any]:
    reason = (
        f"Awaiting exact-scale real evidence from {spec.stage_owner}"
        if spec.execution_mode == "real"
        else "Awaiting P37 dry-run no-runtime proof"
    )
    return {
        "coverage_id": spec.coverage_id,
        "scale": spec.scale,
        "node_count": spec.scale,
        "category": spec.category,
        "row_name": spec.row_name,
        "stage_owner": spec.stage_owner,
        "required": True,
        "execution_mode": spec.execution_mode,
        "status": "PENDING",
        "status_reason": reason,
        "source_artifacts": [],
        "validation_artifacts": [],
        "metric_refs": [],
        "cleanup_ref": "",
        "review_ref": "",
        "commit_sha": "",
    }


def config_path_for_scale(scale: int) -> str:
    if scale in REAL_SCALES:
        return f"templates/configs/scale_{scale}.yaml"
    return f"artifacts/phases/{DRY_RUN_STAGE}/generated_configs/scale_{scale}_dry_run.yaml"
