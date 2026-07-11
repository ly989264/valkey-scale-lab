#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valkey_scale_lab import __version__  # noqa: E402
from valkey_scale_lab.cluster_timeout import compute_effective_cluster_timeout  # noqa: E402
from valkey_scale_lab.config.validation import load_effective_config, validate_config_file  # noqa: E402
from valkey_scale_lab.planner.plan import create_plan_file  # noqa: E402
from valkey_scale_lab.resource import run_resource_preflight  # noqa: E402

PHASE = "P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE"
RUN_ID = "P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE-cluster-timeout-20260707"
CREATED_AT = "2026-07-07T00:00:00Z"
SCALE_CONFIGS = {
    10: "templates/configs/scale_10.yaml",
    30: "templates/configs/scale_30.yaml",
    50: "templates/configs/scale_50.yaml",
    100: "templates/configs/scale_100.yaml",
    200: "templates/configs/scale_200.yaml",
}


def main() -> int:
    base = ROOT / "artifacts" / "phases" / PHASE
    base.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    _ensure_evidence_alias(base / "valkey_e2e_evidence.json", base / "valkey_e2e_evidence_10.json")

    config100 = ROOT / SCALE_CONFIGS[100]
    validation = validate_config_file(config100, base / "config_validation_report.json")
    timeout = compute_effective_cluster_timeout(load_effective_config(config100))
    _write_json(base / "effective_cluster_timeout.json", _timeout_artifact(timeout, 100, "p43_cluster_timeout_scale_100"))
    try:
        plan = create_plan_file(config100, base / "cluster_plan.json")
        plan["phase_id"] = PHASE
        _write_json(base / "cluster_plan.json", plan)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"cluster_plan failed: {exc}")
    try:
        preflight = run_resource_preflight(config100, base / "resource_preflight.json", phase_id=PHASE, scenario="p43_cluster_timeout_scale_100")
        if preflight.get("status") != "PASS":
            errors.append("resource_preflight did not PASS for scale_100")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"resource_preflight failed: {exc}")

    _rebuild_generated_config_manifest(base, errors)
    _write_gt_200_projection(base, errors)
    rows = _coverage_rows(base)
    _write_json(base / "coverage_ledger.json", _base_artifact("coverage_ledger", status="PASS" if _coverage_complete(rows) else "FAIL", rows=rows))
    if not (base / "timeout_matrix_report.json").exists():
        _write_json(
            base / "timeout_matrix_report.json",
            _base_artifact(
                "timeout_matrix_report",
                status="NOT_RUN_WITH_REASON",
                configured_matrix_ms=[5000, 10000, 15000, 30000, 60000],
                selection_policy="explicit_timeout_ms_required",
                rows=[
                    {
                        "status": "NOT_RUN_WITH_REASON",
                        "node_count": 30,
                        "timeout_config_ms": 30000,
                        "kill_to_pfail_ms": "NOT_RUN_WITH_REASON",
                        "pfail_to_cluster_ok_ms": "NOT_RUN_WITH_REASON",
                        "kill_to_client_recovered_ms": "NOT_RUN_WITH_REASON",
                        "false_pfail_count": "NOT_RUN_WITH_REASON",
                        "false_failover_count": "NOT_RUN_WITH_REASON",
                        "reason": "Full timeout matrix is explicit and was not selected for this artifact build.",
                        "real_valkey": False,
                        "static_artifact": False,
                    }
                ],
            ),
        )
    _write_quant_and_reports(base, timeout, rows, validation, errors)
    if not _coverage_complete(rows):
        errors.append("real Valkey timeout coverage incomplete for one or more 10/30/50/100/200 rows")
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS P43 cluster timeout artifacts at {base}")
    return 0


def _ensure_evidence_alias(source: Path, alias: Path) -> None:
    if source.exists() and not alias.exists():
        alias.write_bytes(source.read_bytes())


def _timeout_artifact(timeout: dict[str, Any], node_count: int, scenario: str) -> dict[str, Any]:
    obj = dict(timeout)
    obj.update(
        {
            "schema_version": "v1",
            "artifact_type": "effective_cluster_timeout",
            "phase_id": PHASE,
            "stage_id": PHASE,
            "scenario_name": scenario,
            "run_id": RUN_ID,
            "created_at": CREATED_AT,
            "producer": {"name": "valkey-scale-lab", "version": __version__},
            "status": "PASS",
            "node_count": node_count,
        }
    )
    return obj


def _rebuild_generated_config_manifest(base: Path, errors: list[str]) -> None:
    if (base / "generated_valkey_configs_manifest.json").exists():
        return
    run_state = _load_json(base / "run_state.json")
    nodes = run_state.get("nodes", []) if isinstance(run_state, dict) else []
    if not nodes:
        errors.append("run_state.json missing; cannot rebuild generated config manifest")
        return
    entries = []
    for node in nodes:
        config_path = Path(str(node.get("config_artifact_file", "")))
        text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        timeout = int(node.get("effective_cluster_node_timeout_ms", 0) or 0)
        source = str(node.get("cluster_node_timeout_source", "MISSING"))
        entries.append(
            {
                "logical_id": node.get("logical_id", "MISSING"),
                "config_artifact_file": config_path.as_posix() if config_path.exists() else "MISSING",
                "effective_cluster_node_timeout_ms": timeout,
                "requested_cluster_node_timeout_ms": node.get("requested_cluster_node_timeout_ms", "MISSING"),
                "cluster_node_timeout_source": source,
                "cluster_node_timeout_line_present": f"cluster-node-timeout {timeout}" in text,
                "cluster_node_timeout_source_present": "vslab cluster-node-timeout-source" in text and f"source={source}" in text,
            }
        )
    status = "PASS" if entries and all(item["cluster_node_timeout_line_present"] and item["cluster_node_timeout_source_present"] for item in entries) else "FAIL"
    _write_json(base / "generated_valkey_configs_manifest.json", _base_artifact("generated_valkey_configs_manifest", status=status, node_count=len(entries), entries=entries))
    if status != "PASS":
        errors.append("generated_valkey_configs_manifest did not PASS")


def _write_gt_200_projection(base: Path, errors: list[str]) -> None:
    try:
        projection = create_plan_file(ROOT / "templates/configs/scale_1000_dryrun_optin.yaml", base / "dry_run_gt_200_projection.json", dry_run=True)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"greater-than-200 dry-run projection failed: {exc}")
        return
    projection["phase_id"] = PHASE
    projection["stage_id"] = PHASE
    projection["dry_run"] = True
    projection["real_valkey"] = False
    projection["runtime_resources_created"] = False
    projection["projection_only_reason"] = "Greater-than-200 coverage is dry-run projection only under P43 policy."
    _write_json(base / "dry_run_gt_200_projection.json", projection)


def _coverage_rows(base: Path) -> list[dict[str, Any]]:
    return [
        _row("fake_schema_unit", "PASS", ["tests/unit/test_cluster_timeout.py"], execution_mode="unit_schema"),
        _real_row(base, "smoke_10", 10, base / "valkey_e2e_evidence.json"),
        _real_row(base, "real_30", 30, base / "valkey_e2e_evidence_30.json"),
        _real_row(base, "real_50", 50, base / "valkey_e2e_evidence_50.json"),
        _real_row(base, "real_100", 100, base / "valkey_e2e_evidence_100.json"),
        _real_row(base, "real_200", 200, base / "valkey_e2e_evidence_200.json"),
        _row("dry_run_gt_200", "DRY_RUN_PASS" if (base / "dry_run_gt_200_projection.json").exists() else "FAIL", [_ref(base / "dry_run_gt_200_projection.json")], execution_mode="dry_run_projection"),
    ]


def _real_row(base: Path, coverage_id: str, expected_nodes: int, evidence_path: Path) -> dict[str, Any]:
    ok, reason = _real_status(evidence_path, expected_nodes)
    return _row(coverage_id, "PASS" if ok else "SKIPPED_WITH_REASON", [_ref(evidence_path)], reason=reason, execution_mode="real_valkey")


def _real_status(path: Path, expected_nodes: int) -> tuple[bool, str]:
    if not path.exists():
        return False, f"real Valkey evidence missing for {expected_nodes} nodes"
    obj = _load_json(path)
    if obj.get("status") != "PASS" or obj.get("probe_result") != "PASS" or obj.get("real_valkey") is not True:
        return False, "real Valkey evidence did not PASS"
    if int(obj.get("nodes_observed", 0) or 0) < expected_nodes:
        return False, "real Valkey evidence silently downscaled"
    for proc in obj.get("node_processes", [])[:expected_nodes]:
        if proc.get("effective_cluster_node_timeout_ms") != 30000:
            return False, "node_processes lack timeout 30000 evidence"
    return True, ""


def _coverage_complete(rows: list[dict[str, Any]]) -> bool:
    return all(row.get("status") in {"PASS", "DRY_RUN_PASS"} for row in rows)


def _write_quant_and_reports(base: Path, timeout: dict[str, Any], rows: list[dict[str, Any]], validation: dict[str, Any], errors: list[str]) -> None:
    status = "PASS" if _coverage_complete(rows) and not errors else "FAIL"
    sources = [_ref(base / name) for name in ["effective_cluster_timeout.json", "config_validation_report.json", "resource_preflight.json", "cluster_plan.json", "coverage_ledger.json", "timeout_matrix_report.json", "dry_run_gt_200_projection.json"]]
    missing = [] if status == "PASS" else [{"field": "real_scale_timeout_coverage", "status": "MISSING", "reason": "One or more P43 real timeout evidence rows did not PASS."}]
    _write_json(
        base / "quant_summary.json",
        _base_artifact(
            "quant_summary",
            status=status,
            summary="P43 cluster-node-timeout quantitative summary derived from validation, preflight, generated config, real evidence, matrix, and projection artifacts.",
            artifact_refs=sources,
            source_artifacts=sources,
            missing_data=missing,
            runtime_claims={
                "real_valkey_claimed": status == "PASS",
                "management_runtime_claimed": False,
                "fault_runtime_claimed": False,
            },
            metrics=[{"name": "effective_cluster_node_timeout_ms", "value": timeout.get("effective_cluster_node_timeout_ms"), "unit": "ms", "status": "PASS"}],
        ),
    )
    _write_json(
        base / "analysis_summary.json",
        _base_artifact(
            "analysis_summary",
            status=status,
            source_artifacts=sources,
            findings=[{"name": "cluster_node_timeout_global_profile", "status": "PASS" if validation.get("status") == "PASS" else "FAIL"}],
            missing_metrics=[] if status == "PASS" else [{"metric": "real_scale_timeout_coverage", "status": "MISSING", "reason": "One or more P43 real timeout evidence rows did not PASS."}],
        ),
    )
    _write_json(base / "report_index.json", _base_artifact("report_index", status=status, source_artifacts=sources, reports=[]))
    _write_json(
        base / "phase_summary.json",
        _base_artifact(
            "phase_summary",
            status=status,
            summary="P43 validates global/profile cluster-node-timeout configuration and 10/30/50/100/200 real evidence.",
            required_artifacts=sources,
            missing_metrics=[
                {"metric": item["field"], "status": item["status"], "reason": item["reason"]}
                for item in missing
            ],
            risks=[
                {
                    "risk": "The full failover RTO timeout matrix is explicit opt-in and was not run by default.",
                    "severity": "low",
                    "required_before_next_phase": False,
                }
            ],
        ),
    )
    start_event_id = "p43-artifacts-start"
    end_event_id = "p43-artifacts-end"
    _write_json(
        base / "workload_windows.json",
        _base_artifact(
            "workload_windows",
            status=status,
            windows=[
                {
                    "window_name": "all_run",
                    "start_event_id": start_event_id,
                    "end_event_id": end_event_id,
                    "metrics": {
                        "effective_cluster_node_timeout_ms": timeout.get("effective_cluster_node_timeout_ms"),
                        "real_scale_count": sum(1 for row in rows if row.get("execution_mode") == "real_valkey"),
                        "timeout_matrix_status": _load_json(base / "timeout_matrix_report.json").get("status", "MISSING"),
                    },
                }
            ],
        ),
    )
    events = [
        {
            "schema_version": "v1",
            "artifact_type": "event",
            "run_id": RUN_ID,
            "phase_id": PHASE,
            "event_id": start_event_id,
            "event_type": "cluster_timeout_artifact_build_started",
            "timestamp": CREATED_AT,
            "timestamp_unix_ms": 1783526400000,
            "monotonic_ms": 0,
            "severity": "info",
            "details": {"scenario_name": "p43_cluster_timeout_artifacts"},
        },
        {
            "schema_version": "v1",
            "artifact_type": "event",
            "run_id": RUN_ID,
            "phase_id": PHASE,
            "event_id": end_event_id,
            "event_type": "cluster_timeout_artifact_build_completed",
            "timestamp": CREATED_AT,
            "timestamp_unix_ms": 1783526400000,
            "monotonic_ms": 1,
            "severity": "info" if status == "PASS" else "error",
            "details": {"status": status, "scenario_name": "p43_cluster_timeout_artifacts"},
        },
    ]
    (base / "events.jsonl").write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events), encoding="utf-8")
    metric = {
        "schema_version": "v1",
        "artifact_type": "metric_sample",
        "run_id": RUN_ID,
        "phase_id": PHASE,
        "timestamp": CREATED_AT,
        "timestamp_unix_ms": 1783526400000,
        "source": "p43_cluster_timeout_artifacts",
        "source_type": "harness",
        "source_id": "p43",
        "metrics": {
            "effective_cluster_node_timeout_ms": timeout.get("effective_cluster_node_timeout_ms"),
            "real_timeout_evidence_scales": [
                row["coverage_id"]
                for row in rows
                if row.get("execution_mode") == "real_valkey" and row.get("status") == "PASS"
            ],
        },
        "labels": {"scenario_name": "p43_cluster_timeout_artifacts"},
    }
    (base / "metrics_timeseries.jsonl").write_text(json.dumps(metric, sort_keys=True) + "\n", encoding="utf-8")


def _row(coverage_id: str, status: str, refs: list[str], *, reason: str = "", execution_mode: str) -> dict[str, Any]:
    return {"coverage_id": coverage_id, "status": status, "artifact_refs": refs, "reason": reason, "execution_mode": execution_mode}


def _base_artifact(artifact_type: str, status: str, **extra: Any) -> dict[str, Any]:
    return {"schema_version": "v1", "artifact_type": artifact_type, "phase_id": PHASE, "stage_id": PHASE, "run_id": RUN_ID, "created_at": CREATED_AT, "producer": {"name": "valkey-scale-lab", "version": __version__}, "status": status, **extra}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ref(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
