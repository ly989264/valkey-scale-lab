#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import load_json, load_jsonl, phase_dir, rel  # noqa: E402

PHASE = "P38_CROSS_SCALE_ANALYSIS_REGRESSION"
RUN_ID = "P38_CROSS_SCALE_ANALYSIS_REGRESSION-analysis-20260704"
CREATED_AT = "2026-07-04T00:00:00Z"
PRODUCER = {"name": "scripts/p38_cross_scale_analysis.py", "version": "v1"}
REGISTRY_PATH = "artifacts/coverage/strict_coverage_registry.json"

MANAGEMENT_STAGES = {
    50: "P30_MANAGEMENT_MATRIX_50_REAL",
    100: "P31_MANAGEMENT_MATRIX_100_REAL",
    200: "P32_MANAGEMENT_MATRIX_200_REAL",
}
FAULT_STAGES = {
    50: "P33_FAULT_FAILOVER_MATRIX_50_REAL",
    100: "P34_FAULT_FAILOVER_MATRIX_100_REAL",
    200: "P35_FAULT_FAILOVER_MATRIX_200_REAL",
}
P36 = "P36_FULL_FLOW_E2E_50_100_200_REAL"
P37 = "P37_200_PLUS_DRY_RUN_SUPPORT"
SOURCE_STAGES = [*MANAGEMENT_STAGES.values(), *FAULT_STAGES.values(), P36, P37]
OUTPUT_FILES = [
    "phase_summary.json",
    "cross_scale_analysis_summary.json",
    "coverage_heatmap_table.csv",
    "management_latency_table.csv",
    "management_convergence_table.csv",
    "failover_curve_table.csv",
    "fault_impact_table.csv",
    "workload_window_table.csv",
    "resource_usage_table.csv",
    "cleanup_table.csv",
    "missing_data_table.csv",
    "analysis_provenance.json",
    "regression_baseline.json",
    "quant_summary.json",
]
ALLOWED_MISSING = {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"}
FORBIDDEN_STRINGS = {"nan", "infinity", "-infinity", "undefined", "null"}


class BuildContext:
    def __init__(self) -> None:
        self.read_paths: set[str] = set()
        self.missing_rows: list[dict[str, Any]] = []
        self.row_provenance: list[dict[str, Any]] = []

    def read_json(self, path_text: str) -> dict[str, Any]:
        self.read_paths.add(path_text)
        return load_json(ROOT / path_text)

    def read_jsonl(self, path_text: str) -> list[dict[str, Any]]:
        self.read_paths.add(path_text)
        rows = load_jsonl(ROOT / path_text)
        return [row for row in rows if isinstance(row, dict)]

    def add_missing(
        self,
        *,
        source_stage: str,
        source_artifact: str,
        field: str,
        reason: str,
        status: str = "MISSING",
        coverage_id: str = "MISSING",
        row_name: str = "MISSING",
    ) -> None:
        self.missing_rows.append(
            {
                "coverage_id": coverage_id,
                "source_stage": source_stage,
                "source_artifact": source_artifact,
                "row_name": row_name,
                "field": field,
                "status": status,
                "reason": reason,
                "method": "copied_from_source_missing_encoding",
            }
        )

    def add_row_provenance(
        self,
        *,
        table: str,
        coverage_id: str,
        source_stage: str,
        source_artifact: str,
        method: str,
        source_line: int | str = "MISSING",
    ) -> None:
        self.row_provenance.append(
            {
                "table": table,
                "coverage_id": coverage_id,
                "source_stage": source_stage,
                "source_artifact": source_artifact,
                "source_line": source_line,
                "method": method,
            }
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(encode_output(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field, "MISSING")) for field in fieldnames})


def csv_value(value: Any) -> str:
    encoded = encode_output(value)
    if isinstance(encoded, (dict, list)):
        return json.dumps(encoded, sort_keys=True, separators=(",", ":"))
    return str(encoded)


def encode_output(value: Any) -> Any:
    if value is None:
        return {"status": "MISSING", "reason": "Source artifact did not provide this value."}
    if isinstance(value, float) and not math.isfinite(value):
        return {"status": "MISSING", "reason": "Source artifact provided a non-finite numeric value."}
    if isinstance(value, str) and value.lower() in FORBIDDEN_STRINGS:
        return "MISSING" if value.lower() == "null" else value
    if isinstance(value, dict):
        return {str(key): encode_output(item) for key, item in value.items()}
    if isinstance(value, list):
        return [encode_output(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default=PHASE)
    args = parser.parse_args()
    if args.phase != PHASE:
        print(f"p38_cross_scale_analysis only builds {PHASE}", file=sys.stderr)
        return 2

    ctx = BuildContext()
    base = phase_dir(PHASE)
    base.mkdir(parents=True, exist_ok=True)

    registry = ctx.read_json(REGISTRY_PATH)
    rows = registry.get("rows", [])
    if not isinstance(rows, list):
        print("coverage registry rows must be a list", file=sys.stderr)
        return 1
    source_summaries = validate_sources(ctx)
    coverage_rows = build_coverage_heatmap(ctx, rows)
    management_latency_rows, management_convergence_rows = build_management_tables(ctx)
    failover_rows = build_failover_curve_table(ctx)
    fault_impact_rows = build_fault_impact_table(ctx)
    workload_rows = build_workload_window_table(ctx)
    resource_rows = build_resource_usage_table(ctx)
    cleanup_rows = build_cleanup_table(ctx)
    missing_rows = sorted(ctx.missing_rows, key=lambda row: (row["source_stage"], row["coverage_id"], row["field"]))
    for row in missing_rows:
        ctx.add_row_provenance(
            table="missing_data_table.csv",
            coverage_id=str(row["coverage_id"]),
            source_stage=str(row["source_stage"]),
            source_artifact=str(row["source_artifact"]),
            method="copied_from_source_missing_encoding",
        )

    output_specs = {
        "coverage_heatmap_table.csv": (
            [
                "coverage_id",
                "scale",
                "category",
                "row_name",
                "execution_mode",
                "status",
                "status_reason",
                "source_stage",
                "source_artifact",
                "method",
            ],
            coverage_rows,
        ),
        "management_latency_table.csv": (
            [
                "coverage_id",
                "scale",
                "operation_name",
                "operation_status",
                "duration_ms",
                "command_ms",
                "prepare_ms",
                "cleanup_ms",
                "latency_method",
                "source_stage",
                "source_artifact",
                "source_line",
                "method",
            ],
            management_latency_rows,
        ),
        "management_convergence_table.csv": (
            [
                "coverage_id",
                "scale",
                "operation_name",
                "convergence_ms",
                "cluster_state_before",
                "cluster_state_after",
                "slots_ok_before",
                "slots_ok_after",
                "known_nodes_before",
                "known_nodes_after",
                "errors_total",
                "source_stage",
                "source_artifact",
                "source_line",
                "method",
            ],
            management_convergence_rows,
        ),
        "failover_curve_table.csv": (
            [
                "coverage_id",
                "scale",
                "metric",
                "sample_count",
                "p50_ms",
                "p95_ms",
                "max_ms",
                "delta_from_previous_scale_ms",
                "percentile_method",
                "delta_method",
                "source_stage",
                "source_artifact",
                "method",
            ],
            failover_rows,
        ),
        "fault_impact_table.csv": (
            [
                "coverage_id",
                "scale",
                "fault_type",
                "window_name",
                "status",
                "duration_ms",
                "availability_percent",
                "errors_total",
                "timeouts_total",
                "latency_p50_ms",
                "latency_p95_ms",
                "source_stage",
                "source_artifact",
                "method",
            ],
            fault_impact_rows,
        ),
        "workload_window_table.csv": (
            [
                "coverage_id",
                "scale",
                "category",
                "row_name",
                "window_name",
                "achieved_qps",
                "error_rate",
                "latency_p95_ms",
                "sample_count",
                "source_stage",
                "source_artifact",
                "method",
            ],
            workload_rows,
        ),
        "resource_usage_table.csv": (
            [
                "coverage_id",
                "scale",
                "category",
                "execution_mode",
                "node_count",
                "required_memory_mb",
                "memory_per_node_mb",
                "projected_node_memory_mb",
                "required_disk_free_mb",
                "runtime_resources_created",
                "source_stage",
                "source_artifact",
                "method",
            ],
            resource_rows,
        ),
        "cleanup_table.csv": (
            [
                "coverage_id",
                "scale",
                "category",
                "execution_mode",
                "status",
                "cleanup_status",
                "runtime_resources_created",
                "source_stage",
                "source_artifact",
                "method",
            ],
            cleanup_rows,
        ),
        "missing_data_table.csv": (
            [
                "coverage_id",
                "source_stage",
                "source_artifact",
                "row_name",
                "field",
                "status",
                "reason",
                "method",
            ],
            missing_rows,
        ),
    }
    for filename, (fieldnames, table_rows) in output_specs.items():
        write_csv(base / filename, fieldnames, table_rows)

    summary = build_summary(
        coverage_rows,
        management_latency_rows,
        management_convergence_rows,
        failover_rows,
        fault_impact_rows,
        workload_rows,
        resource_rows,
        cleanup_rows,
        missing_rows,
        source_summaries,
    )
    write_json(base / "cross_scale_analysis_summary.json", summary)
    baseline = build_regression_baseline(management_latency_rows, management_convergence_rows, failover_rows, fault_impact_rows)
    write_json(base / "regression_baseline.json", baseline)

    output_artifacts = [f"artifacts/phases/{PHASE}/{name}" for name in OUTPUT_FILES]
    source_artifacts = sorted(ctx.read_paths)
    provenance = {
        "schema_version": "v1",
        "artifact_type": "analysis_provenance",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": PRODUCER,
        "status": "PASS",
        "analysis_only": True,
        "runtime_started": False,
        "unvalidated_logs_read": False,
        "invented_values_present": False,
        "allowed_source_stages": SOURCE_STAGES,
        "allowed_source_artifacts": ["P30-P37 validated JSON/JSONL artifacts", REGISTRY_PATH],
        "source_artifacts": [
            {"path": path, "sha256": sha256_file(ROOT / path), "source_stage": source_stage_for_path(path)}
            for path in source_artifacts
        ],
        "output_artifacts": [
            {
                "path": path,
                "sha256_status": "SKIPPED_WITH_REASON",
                "reason": "Output artifact hashes are validated by external gates after generation to avoid self-referential provenance.",
            }
            for path in output_artifacts
        ],
        "row_provenance": sorted(
            ctx.row_provenance,
            key=lambda row: (row["table"], row["coverage_id"], str(row["source_line"])),
        ),
        "derived_methods": [
            "copy_source_json_field",
            "jsonl_row_projection",
            "nearest_rank_round_index from source failover curves",
            "delta_from_previous_scale = current_scale_value - previous_scale_value",
            "missing values copied only from source MISSING/SKIPPED_WITH_REASON/UNSUPPORTED_WITH_REASON encodings",
        ],
    }
    write_json(base / "analysis_provenance.json", provenance)

    quant_summary = {
        "schema_version": "v1",
        "artifact_type": "quant_summary",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": PRODUCER,
        "status": "PASS",
        "summary": "P38 analysis-only aggregation of validated P30-P37 artifacts and strict coverage registry.",
        "artifact_refs": output_artifacts,
        "missing_data": [
            {"field": row["field"], "status": row["status"], "reason": row["reason"], "coverage_id": row["coverage_id"]}
            for row in missing_rows
        ],
        "runtime_claims": {
            "real_valkey_claimed": False,
            "management_runtime_claimed": False,
            "fault_runtime_claimed": False,
            "full_flow_runtime_claimed": False,
            "analysis_only": True,
        },
        "counts": summary["counts"],
    }
    write_json(base / "quant_summary.json", quant_summary)

    phase_summary = {
        "schema_version": "v1",
        "artifact_type": "phase_summary",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": PRODUCER,
        "status": "PASS",
        "summary": "Generated deterministic cross-scale analysis tables and regression baseline from validated P30-P37 artifacts only.",
        "required_artifacts": output_artifacts,
        "missing_metrics": [
            {
                "metric": row["field"],
                "status": row["status"],
                "reason": row["reason"],
                "impact": f"Recorded in missing_data_table.csv for {row['coverage_id']}.",
            }
            for row in missing_rows
        ],
        "risks": [
            {
                "risk": "P38 is only as current as the validated P30-P37 input artifacts.",
                "mitigation": "analysis_provenance.json records exact source sha256 values for regression comparison.",
            }
        ],
        "analysis_only": True,
        "runtime_started": False,
    }
    write_json(base / "phase_summary.json", phase_summary)
    print(f"WROTE P38 cross-scale analysis artifacts under {rel(base)}")
    return 0


def validate_sources(ctx: BuildContext) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for stage in SOURCE_STAGES:
        summary_path = f"artifacts/phases/{stage}/phase_summary.json"
        summary = ctx.read_json(summary_path)
        if summary.get("status") != "PASS":
            raise SystemExit(f"{summary_path}: status must be PASS")
        execution_mode = summary.get("execution_mode", "real" if stage != P37 else "dry_run")
        if stage == P37 and execution_mode != "dry_run":
            raise SystemExit(f"{summary_path}: P37 must remain dry_run")
        if stage == P37 and summary.get("real_valkey_claimed") not in {False, None}:
            raise SystemExit(f"{summary_path}: P37 must not claim real Valkey")
        summaries.append(
            {
                "stage_id": stage,
                "status": summary.get("status"),
                "execution_mode": execution_mode,
                "source_artifact": summary_path,
            }
        )
        collect_missing_from_obj(
            ctx,
            summary,
            stage,
            summary_path,
            coverage_id=f"{stage}.analysis.phase_summary",
            row_name="phase_summary",
        )
    return summaries


def build_coverage_heatmap(ctx: BuildContext, registry_rows: list[Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in registry_rows:
        if not isinstance(row, dict):
            continue
        source_stage = str(row.get("stage_owner", "MISSING"))
        coverage_id = str(row.get("coverage_id", "MISSING"))
        output.append(
            {
                "coverage_id": coverage_id,
                "scale": row.get("scale", "MISSING"),
                "category": row.get("category", "MISSING"),
                "row_name": row.get("row_name", "MISSING"),
                "execution_mode": row.get("execution_mode", "MISSING"),
                "status": row.get("status", "MISSING"),
                "status_reason": row.get("status_reason", "MISSING"),
                "source_stage": source_stage,
                "source_artifact": REGISTRY_PATH,
                "method": "copy_strict_coverage_registry_row",
            }
        )
        ctx.add_row_provenance(
            table="coverage_heatmap_table.csv",
            coverage_id=coverage_id,
            source_stage=source_stage,
            source_artifact=REGISTRY_PATH,
            method="copy_strict_coverage_registry_row",
        )
    return sorted(output, key=lambda row: (int(row["scale"]), str(row["category"]), str(row["row_name"])))


def build_management_tables(ctx: BuildContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    latency_rows: list[dict[str, Any]] = []
    convergence_rows: list[dict[str, Any]] = []
    for scale, stage in MANAGEMENT_STAGES.items():
        artifact = f"artifacts/phases/{stage}/management_operation_results.jsonl"
        rows = ctx.read_jsonl(artifact)
        for line_no, row in enumerate(rows, start=1):
            coverage_id = str(row.get("coverage_id", f"{scale}.management.MISSING"))
            operation = str(row.get("operation_name", "MISSING"))
            missing_by_field = missing_reasons(row)
            for field, reason in missing_by_field.items():
                ctx.add_missing(
                    source_stage=stage,
                    source_artifact=artifact,
                    coverage_id=coverage_id,
                    row_name=operation,
                    field=field,
                    reason=reason,
                )
            command_ms = "MISSING" if "command_ms" in missing_by_field else row.get("command_ms", "MISSING")
            latency_rows.append(
                {
                    "coverage_id": coverage_id,
                    "scale": scale,
                    "operation_name": operation,
                    "operation_status": row.get("operation_status", "MISSING"),
                    "duration_ms": row.get("duration_ms", "MISSING"),
                    "command_ms": command_ms,
                    "prepare_ms": row.get("prepare_ms", "MISSING"),
                    "cleanup_ms": row.get("cleanup_ms", "MISSING"),
                    "latency_method": "duration_ms copied from source monotonic operation timing; command_ms MISSING when source missing_fields marks it missing",
                    "source_stage": stage,
                    "source_artifact": artifact,
                    "source_line": line_no,
                    "method": "jsonl_row_projection",
                }
            )
            convergence_rows.append(
                {
                    "coverage_id": coverage_id,
                    "scale": scale,
                    "operation_name": operation,
                    "convergence_ms": row.get("convergence_ms", "MISSING"),
                    "cluster_state_before": row.get("cluster_state_before", "MISSING"),
                    "cluster_state_after": row.get("cluster_state_after", "MISSING"),
                    "slots_ok_before": row.get("cluster_slots_ok_before", "MISSING"),
                    "slots_ok_after": row.get("cluster_slots_ok_after", "MISSING"),
                    "known_nodes_before": row.get("cluster_known_nodes_before", "MISSING"),
                    "known_nodes_after": row.get("cluster_known_nodes_after", "MISSING"),
                    "errors_total": sum_numeric((row.get("errors_by_type") or {}).values()),
                    "source_stage": stage,
                    "source_artifact": artifact,
                    "source_line": line_no,
                    "method": "jsonl_row_projection",
                }
            )
            for table in ["management_latency_table.csv", "management_convergence_table.csv"]:
                ctx.add_row_provenance(
                    table=table,
                    coverage_id=coverage_id,
                    source_stage=stage,
                    source_artifact=artifact,
                    source_line=line_no,
                    method="jsonl_row_projection",
                )
            collect_missing_from_obj(ctx, row, stage, artifact, coverage_id=coverage_id, row_name=operation)
    key = lambda row: (int(row["scale"]), str(row["operation_name"]))
    return sorted(latency_rows, key=key), sorted(convergence_rows, key=key)


def build_failover_curve_table(ctx: BuildContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    previous_by_metric: dict[str, float] = {}
    for scale, stage in sorted(FAULT_STAGES.items()):
        artifact = f"artifacts/phases/{stage}/failover_latency_curve.json"
        curve = ctx.read_json(artifact)
        collect_missing_from_obj(ctx, curve, stage, artifact, coverage_id=f"{scale}.fault.primary_stop_failover", row_name="primary_stop_failover")
        for series in curve.get("derived_series", []):
            if not isinstance(series, dict):
                continue
            metric = str(series.get("metric", "MISSING"))
            current = numeric_or_missing(series.get("p95_ms"))
            previous = previous_by_metric.get(metric)
            delta = "SKIPPED_WITH_REASON" if previous is None or not isinstance(current, (int, float)) else round(current - previous, 6)
            if isinstance(current, (int, float)):
                previous_by_metric[metric] = float(current)
            rows.append(
                {
                    "coverage_id": f"{scale}.fault.primary_stop_failover",
                    "scale": scale,
                    "metric": metric,
                    "sample_count": series.get("sample_count", "MISSING"),
                    "p50_ms": series.get("p50_ms", "MISSING"),
                    "p95_ms": series.get("p95_ms", "MISSING"),
                    "max_ms": series.get("max_ms", "MISSING"),
                    "delta_from_previous_scale_ms": delta,
                    "percentile_method": series.get("percentile_method", "MISSING"),
                    "delta_method": "delta_from_previous_scale = current p95_ms - previous real scale p95_ms; skipped for first scale",
                    "source_stage": stage,
                    "source_artifact": artifact,
                    "method": "copy_source_derived_series_with_cross_scale_delta",
                }
            )
            ctx.add_row_provenance(
                table="failover_curve_table.csv",
                coverage_id=f"{scale}.fault.primary_stop_failover",
                source_stage=stage,
                source_artifact=artifact,
                method="copy_source_derived_series_with_cross_scale_delta",
            )
            if previous is None:
                ctx.add_missing(
                    source_stage=stage,
                    source_artifact=artifact,
                    coverage_id=f"{scale}.fault.primary_stop_failover",
                    row_name=metric,
                    field="delta_from_previous_scale_ms",
                    status="SKIPPED_WITH_REASON",
                    reason="No previous real scale exists for the first failover curve point.",
                )
    return sorted(rows, key=lambda row: (str(row["metric"]), int(row["scale"])))


def build_fault_impact_table(ctx: BuildContext) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for scale, stage in FAULT_STAGES.items():
        artifact = f"artifacts/phases/{stage}/fault_workload_impact.json"
        report = ctx.read_json(artifact)
        for window in report.get("windows", []):
            if not isinstance(window, dict):
                continue
            source = window.get("source_window") if isinstance(window.get("source_window"), dict) else {}
            latency = source.get("latency_ms") if isinstance(source.get("latency_ms"), dict) else {}
            coverage_id = str(window.get("coverage_id", f"{scale}.fault.MISSING"))
            fault_type = str(window.get("fault_type", "MISSING"))
            output.append(
                {
                    "coverage_id": coverage_id,
                    "scale": scale,
                    "fault_type": fault_type,
                    "window_name": window.get("window_name", "MISSING"),
                    "status": window.get("status", "MISSING"),
                    "duration_ms": source.get("duration_ms", "MISSING"),
                    "availability_percent": source.get("availability_percent", "MISSING"),
                    "errors_total": source.get("errors_total", "MISSING"),
                    "timeouts_total": source.get("timeouts_total", "MISSING"),
                    "latency_p50_ms": latency.get("p50", "MISSING"),
                    "latency_p95_ms": latency.get("p95", "MISSING"),
                    "source_stage": stage,
                    "source_artifact": artifact,
                    "method": "copy_fault_workload_impact_event_window",
                }
            )
            ctx.add_row_provenance(
                table="fault_impact_table.csv",
                coverage_id=coverage_id,
                source_stage=stage,
                source_artifact=artifact,
                method="copy_fault_workload_impact_event_window",
            )
            collect_missing_from_obj(ctx, window, stage, artifact, coverage_id=coverage_id, row_name=fault_type)
    return sorted(output, key=lambda row: (int(row["scale"]), str(row["fault_type"])))


def build_workload_window_table(ctx: BuildContext) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    stage_specs = [(stage, "management") for stage in MANAGEMENT_STAGES.values()]
    stage_specs.extend((stage, "fault") for stage in FAULT_STAGES.values())
    stage_specs.append((P36, "lifecycle"))
    for stage, category in stage_specs:
        artifact = f"artifacts/phases/{stage}/workload_windows.json"
        report = ctx.read_json(artifact)
        for window in report.get("windows", []):
            if not isinstance(window, dict):
                continue
            metrics = window.get("metrics") if isinstance(window.get("metrics"), dict) else {}
            scale = window.get("scale", window.get("node_count", "MISSING"))
            coverage_id = str(window.get("coverage_id", f"{scale}.{category}.MISSING"))
            row_name = workload_row_name(window, coverage_id)
            output.append(
                {
                    "coverage_id": coverage_id,
                    "scale": scale,
                    "category": category,
                    "row_name": row_name,
                    "window_name": window.get("window_name", "MISSING"),
                    "achieved_qps": window.get("achieved_qps", metrics.get("achieved_qps", "MISSING")),
                    "error_rate": window.get("error_rate", metrics.get("error_rate", "MISSING")),
                    "latency_p95_ms": window.get("latency_p95_ms", metrics.get("latency_p95_ms", "MISSING")),
                    "sample_count": window.get("sample_count", metrics.get("sample_count", "MISSING")),
                    "source_stage": stage,
                    "source_artifact": artifact,
                    "method": "copy_workload_window_metrics",
                }
            )
            ctx.add_row_provenance(
                table="workload_window_table.csv",
                coverage_id=coverage_id,
                source_stage=stage,
                source_artifact=artifact,
                method="copy_workload_window_metrics",
            )
            collect_missing_from_obj(ctx, window, stage, artifact, coverage_id=coverage_id, row_name=row_name)
    return sorted(output, key=lambda row: (int(row["scale"]), str(row["category"]), str(row["row_name"]), str(row["window_name"])))


def build_resource_usage_table(ctx: BuildContext) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for scale, stage, category in [
        *[(scale, stage, "management") for scale, stage in MANAGEMENT_STAGES.items()],
        *[(scale, stage, "fault") for scale, stage in FAULT_STAGES.items()],
    ]:
        artifact = f"artifacts/phases/{stage}/resource_preflight.json"
        report = ctx.read_json(artifact)
        estimates = report.get("resource_estimates") if isinstance(report.get("resource_estimates"), dict) else {}
        output.append(
            {
                "coverage_id": f"{scale}.{category}.resource_preflight",
                "scale": scale,
                "category": category,
                "execution_mode": "real",
                "node_count": report.get("node_count", scale),
                "required_memory_mb": estimates.get("required_memory_mb", "MISSING"),
                "memory_per_node_mb": estimates.get("memory_per_node_mb", "MISSING"),
                "projected_node_memory_mb": "SKIPPED_WITH_REASON",
                "required_disk_free_mb": estimates.get("required_disk_free_mb", "MISSING"),
                "runtime_resources_created": "true",
                "source_stage": stage,
                "source_artifact": artifact,
                "method": "copy_resource_preflight_estimates",
            }
        )
        ctx.add_row_provenance(
            table="resource_usage_table.csv",
            coverage_id=f"{scale}.{category}.resource_preflight",
            source_stage=stage,
            source_artifact=artifact,
            method="copy_resource_preflight_estimates",
        )
        ctx.add_missing(
            source_stage=stage,
            source_artifact=artifact,
            coverage_id=f"{scale}.{category}.resource_preflight",
            row_name="resource_preflight",
            field="projected_node_memory_mb",
            status="SKIPPED_WITH_REASON",
            reason="Projection-only memory is not a real-runtime metric for exact-scale source stages.",
        )
    for scale in [50, 100, 200]:
        artifact = f"artifacts/phases/{P36}/full_flow_{scale}/resource_preflight.json"
        report = ctx.read_json(artifact)
        estimates = report.get("resource_estimates") if isinstance(report.get("resource_estimates"), dict) else {}
        output.append(
            {
                "coverage_id": f"{scale}.lifecycle.resource_preflight",
                "scale": scale,
                "category": "lifecycle",
                "execution_mode": "real",
                "node_count": report.get("node_count", scale),
                "required_memory_mb": estimates.get("required_memory_mb", "MISSING"),
                "memory_per_node_mb": estimates.get("memory_per_node_mb", "MISSING"),
                "projected_node_memory_mb": "SKIPPED_WITH_REASON",
                "required_disk_free_mb": estimates.get("required_disk_free_mb", "MISSING"),
                "runtime_resources_created": "true",
                "source_stage": P36,
                "source_artifact": artifact,
                "method": "copy_full_flow_resource_preflight_estimates",
            }
        )
        ctx.add_row_provenance(
            table="resource_usage_table.csv",
            coverage_id=f"{scale}.lifecycle.resource_preflight",
            source_stage=P36,
            source_artifact=artifact,
            method="copy_full_flow_resource_preflight_estimates",
        )
        ctx.add_missing(
            source_stage=P36,
            source_artifact=artifact,
            coverage_id=f"{scale}.lifecycle.resource_preflight",
            row_name="resource_preflight",
            field="projected_node_memory_mb",
            status="SKIPPED_WITH_REASON",
            reason="Projection-only memory is not a real-runtime metric for exact-scale full-flow source stages.",
        )
    for scale in [201, 250, 300, 500, 1000]:
        artifact = f"artifacts/phases/{P37}/resource_estimate_{scale}.json"
        report = ctx.read_json(artifact)
        estimates = report.get("estimates") if isinstance(report.get("estimates"), dict) else {}
        output.append(
            {
                "coverage_id": f"{scale}.dry_run.resource_preflight_dry_run",
                "scale": scale,
                "category": "dry_run",
                "execution_mode": "dry_run",
                "node_count": report.get("target_nodes", scale),
                "required_memory_mb": "SKIPPED_WITH_REASON",
                "memory_per_node_mb": "SKIPPED_WITH_REASON",
                "projected_node_memory_mb": estimates.get("projected_node_memory_mb", "MISSING"),
                "required_disk_free_mb": "SKIPPED_WITH_REASON",
                "runtime_resources_created": report.get("runtime_resources_created", "MISSING"),
                "source_stage": P37,
                "source_artifact": artifact,
                "method": "copy_p37_dry_run_resource_projection",
            }
        )
        ctx.add_row_provenance(
            table="resource_usage_table.csv",
            coverage_id=f"{scale}.dry_run.resource_preflight_dry_run",
            source_stage=P37,
            source_artifact=artifact,
            method="copy_p37_dry_run_resource_projection",
        )
        for field in ["required_memory_mb", "memory_per_node_mb", "required_disk_free_mb"]:
            ctx.add_missing(
                source_stage=P37,
                source_artifact=artifact,
                coverage_id=f"{scale}.dry_run.resource_preflight_dry_run",
                row_name="resource_preflight_dry_run",
                field=field,
                status="SKIPPED_WITH_REASON",
                reason="P37 above-200 rows are dry-run-only projections and do not have real runtime resource measurements.",
            )
    return sorted(output, key=lambda row: (int(row["scale"]), str(row["category"])))


def build_cleanup_table(ctx: BuildContext) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for scale, stage in MANAGEMENT_STAGES.items():
        output.extend(cleanup_rows_for_stage(ctx, scale, "management", stage, f"artifacts/phases/{stage}/cleanup_report.json"))
    for scale, stage in FAULT_STAGES.items():
        output.extend(cleanup_rows_for_stage(ctx, scale, "fault", stage, f"artifacts/phases/{stage}/cleanup_report.json"))
    for scale in [50, 100, 200]:
        output.extend(cleanup_rows_for_stage(ctx, scale, "lifecycle", P36, f"artifacts/phases/{P36}/full_flow_{scale}/cleanup_report.json"))
    for scale in [201, 250, 300, 500, 1000]:
        artifact = f"artifacts/phases/{P37}/no_runtime_created_proof_{scale}.json"
        report = ctx.read_json(artifact)
        row = {
            "coverage_id": f"{scale}.dry_run.no_runtime_created_proof",
            "scale": scale,
            "category": "dry_run",
            "execution_mode": "dry_run",
            "status": report.get("status", "MISSING"),
            "cleanup_status": report.get("status", "MISSING"),
            "runtime_resources_created": report.get("runtime_resources_created", "MISSING"),
            "source_stage": P37,
            "source_artifact": artifact,
            "method": "copy_no_runtime_created_proof",
        }
        output.append(row)
        ctx.add_row_provenance(
            table="cleanup_table.csv",
            coverage_id=row["coverage_id"],
            source_stage=P37,
            source_artifact=artifact,
            method="copy_no_runtime_created_proof",
        )
    return sorted(output, key=lambda row: (int(row["scale"]), str(row["category"])))


def cleanup_rows_for_stage(ctx: BuildContext, scale: int, category: str, stage: str, artifact: str) -> list[dict[str, Any]]:
    report = ctx.read_json(artifact)
    row = {
        "coverage_id": f"{scale}.{category}.cleanup_verify",
        "scale": scale,
        "category": category,
        "execution_mode": "real",
        "status": report.get("status", "MISSING"),
        "cleanup_status": report.get("status", "MISSING"),
        "runtime_resources_created": "false_after_cleanup",
        "source_stage": stage,
        "source_artifact": artifact,
        "method": "copy_cleanup_report_status",
    }
    ctx.add_row_provenance(
        table="cleanup_table.csv",
        coverage_id=row["coverage_id"],
        source_stage=stage,
        source_artifact=artifact,
        method="copy_cleanup_report_status",
    )
    collect_missing_from_obj(ctx, report, stage, artifact, coverage_id=row["coverage_id"], row_name="cleanup_verify")
    return [row]


def build_summary(
    coverage_rows: list[dict[str, Any]],
    management_latency_rows: list[dict[str, Any]],
    management_convergence_rows: list[dict[str, Any]],
    failover_rows: list[dict[str, Any]],
    fault_impact_rows: list[dict[str, Any]],
    workload_rows: list[dict[str, Any]],
    resource_rows: list[dict[str, Any]],
    cleanup_rows: list[dict[str, Any]],
    missing_rows: list[dict[str, Any]],
    source_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    counts_by_category: dict[str, int] = defaultdict(int)
    for row in coverage_rows:
        counts_by_category[str(row["category"])] += 1
    return {
        "schema_version": "v1",
        "artifact_type": "cross_scale_analysis_summary",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": PRODUCER,
        "status": "PASS",
        "analysis_only": True,
        "source_summaries": source_summaries,
        "counts": {
            "coverage_rows": len(coverage_rows),
            "management_latency_rows": len(management_latency_rows),
            "management_convergence_rows": len(management_convergence_rows),
            "failover_curve_rows": len(failover_rows),
            "fault_impact_rows": len(fault_impact_rows),
            "workload_window_rows": len(workload_rows),
            "resource_usage_rows": len(resource_rows),
            "cleanup_rows": len(cleanup_rows),
            "missing_data_rows": len(missing_rows),
            "coverage_by_category": dict(sorted(counts_by_category.items())),
            "real_scales": [50, 100, 200],
            "dry_run_scales": [201, 250, 300, 500, 1000],
        },
        "methods": {
            "percentile": "nearest_rank_round_index copied from source failover_latency_curve.json",
            "delta": "delta_from_previous_scale = current p95_ms - previous real scale p95_ms",
            "missing": "source MISSING/SKIPPED_WITH_REASON/UNSUPPORTED_WITH_REASON encodings copied with reasons",
        },
    }


def build_regression_baseline(
    latency_rows: list[dict[str, Any]],
    convergence_rows: list[dict[str, Any]],
    failover_rows: list[dict[str, Any]],
    fault_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": "regression_baseline",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": PRODUCER,
        "status": "PASS",
        "baseline_scope": "current validated P30-P37 artifacts",
        "methods": {
            "management_latency": "duration_ms copied from management_operation_results.jsonl by coverage_id and scale",
            "management_convergence": "convergence_ms copied from management_operation_results.jsonl by coverage_id and scale",
            "failover_percentiles": "p50_ms/p95_ms/max_ms copied from failover_latency_curve.json derived_series; source declares nearest_rank_round_index",
            "failover_delta": "delta_from_previous_scale = current p95_ms - previous real scale p95_ms",
            "fault_impact": "event-window availability/error/latency fields copied from fault_workload_impact.json",
        },
        "management_latency_ms": pivot_by_row(latency_rows, "operation_name", "duration_ms"),
        "management_convergence_ms": pivot_by_row(convergence_rows, "operation_name", "convergence_ms"),
        "failover_p95_ms": pivot_by_row(failover_rows, "metric", "p95_ms"),
        "failover_delta_p95_ms": pivot_by_row(failover_rows, "metric", "delta_from_previous_scale_ms"),
        "fault_impact_availability_percent": pivot_by_row(fault_rows, "fault_type", "availability_percent"),
        "source_tables": [
            f"artifacts/phases/{PHASE}/management_latency_table.csv",
            f"artifacts/phases/{PHASE}/management_convergence_table.csv",
            f"artifacts/phases/{PHASE}/failover_curve_table.csv",
            f"artifacts/phases/{PHASE}/fault_impact_table.csv",
        ],
    }


def pivot_by_row(rows: list[dict[str, Any]], row_key: str, value_key: str) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get(row_key, "MISSING"))
        scale = str(row.get("scale", "MISSING"))
        output.setdefault(name, {})[scale] = row.get(value_key, "MISSING")
    return dict(sorted(output.items()))


def collect_missing_from_obj(
    ctx: BuildContext,
    obj: Any,
    source_stage: str,
    source_artifact: str,
    *,
    coverage_id: str,
    row_name: str,
    path: str = "$",
) -> None:
    if isinstance(obj, dict):
        status = obj.get("status")
        if status in ALLOWED_MISSING:
            reason = obj.get("reason") or obj.get("status_reason")
            if reason:
                ctx.add_missing(
                    source_stage=source_stage,
                    source_artifact=source_artifact,
                    coverage_id=coverage_id,
                    row_name=row_name,
                    field=path,
                    status=str(status),
                    reason=str(reason),
                )
        for key, value in obj.items():
            collect_missing_from_obj(
                ctx,
                value,
                source_stage,
                source_artifact,
                coverage_id=coverage_id,
                row_name=row_name,
                path=f"{path}.{key}",
            )
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            collect_missing_from_obj(
                ctx,
                value,
                source_stage,
                source_artifact,
                coverage_id=coverage_id,
                row_name=row_name,
                path=f"{path}[{index}]",
            )


def missing_reasons(row: dict[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    for item in row.get("missing_fields", []):
        if isinstance(item, dict) and item.get("status") in ALLOWED_MISSING and item.get("field") and item.get("reason"):
            output[str(item["field"])] = str(item["reason"])
    return output


def workload_row_name(window: dict[str, Any], coverage_id: str) -> str:
    for key in ["operation_name", "fault_type", "sample_id"]:
        value = window.get(key)
        if value:
            return str(value)
    parts = coverage_id.split(".", 2)
    if len(parts) == 3 and parts[2]:
        return parts[2]
    return "MISSING"


def source_stage_for_path(path_text: str) -> str:
    for stage in SOURCE_STAGES:
        if f"/{stage}/" in f"/{path_text}":
            return stage
    if path_text == REGISTRY_PATH:
        return "coverage_registry"
    return "MISSING"


def sum_numeric(values: Any) -> float:
    total = 0.0
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total += float(value)
    return round(total, 6)


def numeric_or_missing(value: Any) -> float | str:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return "MISSING"


if __name__ == "__main__":
    raise SystemExit(main())
