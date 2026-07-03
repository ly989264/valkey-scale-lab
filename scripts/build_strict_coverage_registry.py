#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_coverage_defs import (  # noqa: E402
    CSV_COLUMNS,
    DETERMINISTIC_CREATED_AT,
    DRY_RUN_SCALES,
    EXPECTED_COUNTS,
    EXPECTED_TOTAL_ROWS,
    FAULT_ROWS,
    FULL_FLOW_STAGE,
    LIFECYCLE_ROWS,
    MANAGEMENT_ROWS,
    REAL_SCALES,
    SCHEMA_VERSION,
    SOURCE_SPEC_REFS,
    STRICT_COVERAGE_STAGE,
    config_path_for_scale,
    empty_pending_row,
    required_row_specs,
)
from strict_harness_lib import rel  # noqa: E402

PHASE_DIR = ROOT / "artifacts" / "phases" / STRICT_COVERAGE_STAGE


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def compact_list(value: list[str]) -> str:
    return ";".join(value)


def build_registry() -> dict[str, Any]:
    rows = [empty_pending_row(spec) for spec in required_row_specs()]
    count_by_category = Counter(row["category"] for row in rows)
    count_by_mode = Counter(row["execution_mode"] for row in rows)
    count_by_status = Counter(row["status"] for row in rows)
    count_by_stage_owner = Counter(row["stage_owner"] for row in rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "strict_coverage_registry",
        "stage_id": STRICT_COVERAGE_STAGE,
        "created_at": DETERMINISTIC_CREATED_AT,
        "producer": {"name": "scripts/build_strict_coverage_registry.py", "version": "v1"},
        "source_spec_refs": SOURCE_SPEC_REFS,
        "summary": {
            "total_rows": len(rows),
            "expected_total_rows": EXPECTED_TOTAL_ROWS,
            "expected_counts": EXPECTED_COUNTS,
            "counts_by_category": dict(sorted(count_by_category.items())),
            "counts_by_execution_mode": dict(sorted(count_by_mode.items())),
            "counts_by_status": dict(sorted(count_by_status.items())),
            "counts_by_stage_owner": dict(sorted(count_by_stage_owner.items())),
            "real_rows_initial_status": "PENDING",
            "dry_run_rows_initial_status": "PENDING",
            "real_runtime_claimed": False,
            "real_execution_above_200_permitted": False,
        },
        "rows": rows,
    }


def scenario_common(
    scenario_id: str,
    stage_owner: str,
    node_count: int,
    execution_mode: str,
    coverage_ids: list[str],
) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "stage_owner": stage_owner,
        "node_count": node_count,
        "execution_mode": execution_mode,
        "config_path": config_path_for_scale(node_count),
        "resource_preflight_required": True,
        "workload_profile": {
            "name": "strict_probe_workload" if execution_mode == "real" else "dry_run_projection_only",
            "qps_policy": "nonzero_probe_load_with_reason_allowed_for_100_200" if execution_mode == "real" else "no_workload_execution",
            "latency_error_impact_required": execution_mode == "real",
        },
        "telemetry_policy": {
            "required": execution_mode == "real",
            "events_jsonl_required": execution_mode == "real",
            "metrics_timeseries_jsonl_required": execution_mode == "real",
            "workload_windows_required": execution_mode == "real",
            "missing_values_policy": "MISSING_or_SKIPPED_WITH_REASON_with_reason",
            "dry_run_policy": "schema_projection_only_no_runtime_samples" if execution_mode == "dry_run" else "",
        },
        "timeout_policy": {
            "convergence_timeout_seconds": 900 if node_count == 50 else 1800 if node_count == 100 else 3600,
            "fault_recovery_timeout_seconds": 900 if node_count == 50 else 1800 if node_count == 100 else 3600,
            "dry_run_timeout_seconds": 300,
        },
        "cleanup_policy": {
            "required": True,
            "deterministic_state_files": True,
            "owned_resources_only": True,
            "no_host_network_mutation": True,
            "no_runtime_for_dry_run": execution_mode == "dry_run",
        },
        "expected_artifacts": [
            f"artifacts/phases/{stage_owner}/phase_summary.json",
            f"artifacts/phases/{stage_owner}/quant_summary.json",
            f"artifacts/phases/{stage_owner}/coverage_ledger.json",
            f"artifacts/phases/{stage_owner}/cleanup_report.json",
        ],
        "coverage_ids": coverage_ids,
        "safety_constraints": [
            "no host-level network mutation",
            "owned Docker/container namespaces or sandbox proxy only",
            "deterministic cleanup required",
            "no fake real Valkey evidence",
        ],
    }


def build_scenario_plan() -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    for scale in REAL_SCALES:
        management_ids = [f"{scale}.management.{name}" for name in MANAGEMENT_ROWS]
        scenario = scenario_common(
            f"management_matrix_{scale}_real",
            {50: "P30_MANAGEMENT_MATRIX_50_REAL", 100: "P31_MANAGEMENT_MATRIX_100_REAL", 200: "P32_MANAGEMENT_MATRIX_200_REAL"}[scale],
            scale,
            "real",
            management_ids,
        )
        scenario["operation_sequence"] = list(MANAGEMENT_ROWS)
        scenario["fault_sequence"] = []
        scenario["expected_artifacts"].extend(
            [
                f"artifacts/phases/{scenario['stage_owner']}/events.jsonl",
                f"artifacts/phases/{scenario['stage_owner']}/metrics_timeseries.jsonl",
                f"artifacts/phases/{scenario['stage_owner']}/management_ops_matrix.json",
                f"artifacts/phases/{scenario['stage_owner']}/workload_windows.json",
            ]
        )
        scenarios.append(scenario)

    for scale in REAL_SCALES:
        fault_ids = [f"{scale}.fault.{name}" for name in FAULT_ROWS]
        scenario = scenario_common(
            f"fault_failover_matrix_{scale}_real",
            {50: "P33_FAULT_FAILOVER_MATRIX_50_REAL", 100: "P34_FAULT_FAILOVER_MATRIX_100_REAL", 200: "P35_FAULT_FAILOVER_MATRIX_200_REAL"}[scale],
            scale,
            "real",
            fault_ids,
        )
        scenario["operation_sequence"] = []
        scenario["fault_sequence"] = list(FAULT_ROWS)
        scenario["expected_artifacts"].extend(
            [
                f"artifacts/phases/{scenario['stage_owner']}/events.jsonl",
                f"artifacts/phases/{scenario['stage_owner']}/metrics_timeseries.jsonl",
                f"artifacts/phases/{scenario['stage_owner']}/fault_matrix_report.json",
                f"artifacts/phases/{scenario['stage_owner']}/failover_latency_curve.json",
                f"artifacts/phases/{scenario['stage_owner']}/split_brain_report.json",
                f"artifacts/phases/{scenario['stage_owner']}/workload_windows.json",
            ]
        )
        scenarios.append(scenario)

    for scale in REAL_SCALES:
        lifecycle_ids = [f"{scale}.lifecycle.{name}" for name in LIFECYCLE_ROWS]
        scenario = scenario_common(
            f"full_flow_e2e_{scale}_real",
            FULL_FLOW_STAGE,
            scale,
            "real",
            lifecycle_ids,
        )
        scenario["operation_sequence"] = list(LIFECYCLE_ROWS)
        scenario["fault_sequence"] = ["primary_stop_failover", "replica_stop", "network_delay"]
        scenario["expected_artifacts"].extend(
            [
                f"artifacts/phases/{FULL_FLOW_STAGE}/events.jsonl",
                f"artifacts/phases/{FULL_FLOW_STAGE}/metrics_timeseries.jsonl",
                f"artifacts/phases/{FULL_FLOW_STAGE}/workload_windows.json",
                f"artifacts/phases/{FULL_FLOW_STAGE}/full_flow_e2e_report.json",
                f"artifacts/phases/{FULL_FLOW_STAGE}/analysis_summary.json",
                f"artifacts/phases/{FULL_FLOW_STAGE}/report_index.json",
            ]
        )
        scenarios.append(scenario)

    for scale in DRY_RUN_SCALES:
        dry_ids = [f"{scale}.dry_run.{name}" for name in (
            "config_validate_dry_run",
            "resource_preflight_dry_run",
            "plan_cluster_dry_run",
            "placement_schedule_dry_run",
            "port_directory_collision_check_dry_run",
            "artifact_schema_projection_dry_run",
            "no_runtime_created_proof",
            "report_projection_dry_run",
        )]
        scenario = scenario_common(
            f"dry_run_{scale}_no_runtime",
            "P37_200_PLUS_DRY_RUN_SUPPORT",
            scale,
            "dry_run",
            dry_ids,
        )
        scenario["operation_sequence"] = [
            "config_validate_dry_run",
            "resource_preflight_dry_run",
            "plan_cluster_dry_run",
            "placement_schedule_dry_run",
            "port_directory_collision_check_dry_run",
            "artifact_schema_projection_dry_run",
            "runtime_inventory_before_after_compare",
            "report_projection_dry_run",
        ]
        scenario["fault_sequence"] = []
        scenario["expected_artifacts"].extend(
            [
                f"artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/dry_run_plan_{scale}.json",
                f"artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/no_runtime_created_proof_{scale}.json",
            ]
        )
        scenario["safety_constraints"].extend(
            [
                "no containers started above 200 nodes",
                "no live Valkey endpoint probing above 200 nodes",
                "no workload execution above 200 nodes",
            ]
        )
        scenarios.append(scenario)

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "strict_scenario_plan",
        "stage_id": STRICT_COVERAGE_STAGE,
        "created_at": DETERMINISTIC_CREATED_AT,
        "producer": {"name": "scripts/build_strict_coverage_registry.py", "version": "v1"},
        "source_spec_refs": SOURCE_SPEC_REFS,
        "summary": {
            "scenario_count": len(scenarios),
            "management_scenarios": len(REAL_SCALES),
            "fault_scenarios": len(REAL_SCALES),
            "full_flow_scenarios": len(REAL_SCALES),
            "dry_run_scenarios": len(DRY_RUN_SCALES),
            "real_execution_above_200_permitted": False,
        },
        "scenarios": scenarios,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            out = {key: row[key] for key in CSV_COLUMNS}
            for key in ["source_artifacts", "validation_artifacts", "metric_refs"]:
                out[key] = compact_list(out[key])
            writer.writerow(out)


def build_report(registry: dict[str, Any], scenario_plan: dict[str, Any], artifact_paths: list[str]) -> dict[str, Any]:
    rows = registry["rows"]
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "coverage_registry_report",
        "phase_id": STRICT_COVERAGE_STAGE,
        "run_id": "p28-coverage-registry-static",
        "created_at": DETERMINISTIC_CREATED_AT,
        "producer": {"name": "scripts/build_strict_coverage_registry.py", "version": "v1"},
        "status": "PASS",
        "summary": "Canonical strict coverage registry and deterministic scenario plan generated without runtime execution.",
        "row_counts": registry["summary"],
        "expected_counts": EXPECTED_COUNTS | {"total": EXPECTED_TOTAL_ROWS},
        "scenario_plan_summary": scenario_plan["summary"],
        "generated_artifacts": artifact_paths,
        "schema_validation_status": "PENDING_EXTERNAL_VALIDATION",
        "runtime_claims": {
            "real_valkey_claimed": False,
            "management_runtime_claimed": False,
            "fault_runtime_claimed": False,
            "full_flow_runtime_claimed": False,
            "dry_run_runtime_claimed": False,
            "real_execution_above_200_permitted": False,
        },
        "coverage_id_samples": {
            "first": rows[0]["coverage_id"],
            "last": rows[-1]["coverage_id"],
            "sample_management": "50.management.remove_replica",
            "sample_fault": "100.fault.network_delay",
            "sample_lifecycle": "200.lifecycle.cleanup_verify",
            "sample_dry_run": "500.dry_run.no_runtime_created_proof",
        },
    }


def build_phase_summary(artifact_paths: list[str]) -> dict[str, Any]:
    missing = [
        {
            "metric": metric,
            "status": "SKIPPED_WITH_REASON",
            "reason": "P28 is a non-runtime registry/compiler stage; later stages must produce exact-scale evidence.",
        }
        for metric in [
            "valkey_e2e_evidence",
            "management_operation_metrics",
            "fault_failover_metrics",
            "workload_qps_latency_error_impact",
        ]
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "phase_summary",
        "phase_id": STRICT_COVERAGE_STAGE,
        "run_id": "p28-coverage-registry-static",
        "created_at": DETERMINISTIC_CREATED_AT,
        "producer": {"name": "scripts/build_strict_coverage_registry.py", "version": "v1"},
        "status": "PASS",
        "summary": "P28 generated strict coverage registry, CSV export, and scenario plan without claiming real runtime evidence.",
        "required_artifacts": artifact_paths,
        "missing_metrics": missing,
        "risks": [
            {
                "risk": "Runtime rows remain pending.",
                "mitigation": "All real 50/100/200 rows are PENDING until later exact-scale stages supply evidence.",
            }
        ],
        "real_runtime_claimed": False,
    }


def build_quant_summary(artifact_paths: list[str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "quant_summary",
        "phase_id": STRICT_COVERAGE_STAGE,
        "run_id": "p28-coverage-registry-static",
        "created_at": DETERMINISTIC_CREATED_AT,
        "producer": {"name": "scripts/build_strict_coverage_registry.py", "version": "v1"},
        "status": "SKIPPED_WITH_REASON",
        "summary": "Runtime quantification is intentionally skipped because P28 only compiles registry and scenario artifacts.",
        "artifact_refs": artifact_paths,
        "missing_data": [
            {
                "field": field,
                "status": "SKIPPED_WITH_REASON",
                "reason": "P28 has no Docker, live Valkey, workload, management, or fault runtime execution.",
            }
            for field in [
                "real_valkey_runtime_metrics",
                "management_operation_timings",
                "fault_failover_latency_samples",
                "workload_window_measurements",
            ]
        ],
        "runtime_claims": {
            "real_valkey_claimed": False,
            "management_runtime_claimed": False,
            "fault_runtime_claimed": False,
            "full_flow_runtime_claimed": False,
            "real_execution_above_200_claimed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="artifacts/coverage")
    parser.add_argument("--phase", default=STRICT_COVERAGE_STAGE)
    args = parser.parse_args()
    if args.phase != STRICT_COVERAGE_STAGE:
        print(f"build_strict_coverage_registry only supports {STRICT_COVERAGE_STAGE}", file=sys.stderr)
        return 2

    out_dir = ROOT / args.out_dir
    registry_path = out_dir / "strict_coverage_registry.json"
    matrix_path = out_dir / "strict_required_matrix.csv"
    scenario_path = out_dir / "strict_scenario_plan.json"
    report_path = PHASE_DIR / "coverage_registry_report.json"
    phase_summary_path = PHASE_DIR / "phase_summary.json"
    quant_summary_path = PHASE_DIR / "quant_summary.json"
    artifact_paths = [rel(path) for path in [registry_path, matrix_path, scenario_path, report_path, phase_summary_path, quant_summary_path]]

    registry = build_registry()
    scenario_plan = build_scenario_plan()
    write_json(registry_path, registry)
    write_csv(matrix_path, registry["rows"])
    write_json(scenario_path, scenario_plan)
    write_json(report_path, build_report(registry, scenario_plan, artifact_paths))
    write_json(phase_summary_path, build_phase_summary(artifact_paths))
    write_json(quant_summary_path, build_quant_summary(artifact_paths))
    print(f"WROTE strict coverage artifacts: {', '.join(artifact_paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
