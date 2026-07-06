#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valkey_scale_lab import __version__  # noqa: E402
from valkey_scale_lab.config.validation import load_effective_config, validate_config_file  # noqa: E402
from valkey_scale_lab.planner.plan import create_plan_file  # noqa: E402
from valkey_scale_lab.resource import run_resource_preflight  # noqa: E402
from valkey_scale_lab.server_profile import compute_effective_server_profile  # noqa: E402

PHASE = "P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG"
RUN_ID = "P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG-server-profile-20260706"
CREATED_AT = "2026-07-06T00:00:00Z"
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

    config100 = ROOT / SCALE_CONFIGS[100]
    validation = validate_config_file(config100, base / "config_validation_report.json")
    _stamp_phase(base / "config_validation_report.json")
    profile = _effective_profile(config100)
    _write_json(base / "effective_server_profile.json", _profile_artifact(profile, node_count=100, scenario="p42_server_profile_scale_100"))

    try:
        create_plan_file(config100, base / "cluster_plan.json")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"cluster_plan scale_100 failed: {exc}")

    try:
        preflight = run_resource_preflight(config100, base / "resource_preflight.json", phase_id=PHASE, scenario="p42_server_profile_scale_100")
        if preflight.get("status") != "PASS" or preflight.get("can_run") is not True:
            errors.append("resource_preflight did not PASS for scale_100")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"resource_preflight scale_100 failed: {exc}")

    _rebuild_generated_config_manifest_if_possible(base, errors)
    _write_gt_200_projection(base, errors)
    coverage_rows = _coverage_rows(base)
    _write_json(
        base / "coverage_ledger.json",
        _base_artifact(
            "coverage_ledger",
            status="PASS" if _coverage_complete(coverage_rows) else "FAIL",
            rows=coverage_rows,
        ),
    )
    _write_quant_artifacts(base, profile, coverage_rows, validation, errors)

    if not _coverage_complete(coverage_rows):
        errors.append("real Valkey coverage is incomplete for one or more P42 scale rows")
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS P42 server profile artifacts at {base}")
    return 0


def _effective_profile(config_path: Path) -> dict[str, Any]:
    config = load_effective_config(config_path)
    return compute_effective_server_profile(config)


def _profile_artifact(profile: dict[str, Any], *, node_count: int, scenario: str) -> dict[str, Any]:
    obj = dict(profile)
    obj.update(
        {
            "schema_version": "v1",
            "artifact_type": "effective_server_profile",
            "phase_id": PHASE,
            "stage_id": PHASE,
            "scenario_name": scenario,
            "run_id": RUN_ID,
            "created_at": CREATED_AT,
            "producer": {"name": "valkey-scale-lab", "version": __version__},
            "status": "PASS" if obj.get("io_thread_budget_status") in {"PASS", "DEGRADED_WITH_REASON"} else "FAIL",
            "node_count": node_count,
        }
    )
    return obj


def _rebuild_generated_config_manifest_if_possible(base: Path, errors: list[str]) -> None:
    manifest_path = base / "generated_valkey_configs_manifest.json"
    if manifest_path.exists():
        return
    run_state = _load_json(base / "run_state.json")
    nodes = run_state.get("nodes", []) if run_state else []
    if not isinstance(nodes, list) or not nodes:
        errors.append("run_state.json missing; cannot rebuild generated_valkey_configs_manifest without real runtime state")
        return
    entries: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        config_ref = node.get("config_artifact_file") or node.get("config_file")
        config_path = _resolve_path(base, str(config_ref or ""))
        text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        effective_io = _int(node.get("effective_io_threads"), 1)
        memory_mb = _int(node.get("effective_node_memory_limit_mb"), 0)
        entries.append(
            {
                "logical_id": node.get("logical_id", "MISSING"),
                "config_artifact_file": config_path.as_posix() if config_path.exists() else "MISSING",
                "effective_server_profile": node.get("effective_server_profile", "MISSING"),
                "effective_io_threads": effective_io,
                "effective_node_memory_limit_mb": memory_mb,
                "io_threads_line_required": effective_io > 1,
                "io_threads_line_present": f"io-threads {effective_io}" in text if effective_io > 1 else "SKIPPED_WITH_REASON",
                "maxmemory_line_present": f"maxmemory {memory_mb}mb" in text if memory_mb > 0 else False,
                "runtime_memory_limit_enforced": bool(node.get("runtime_memory_limit_enforced")),
                "runtime_memory_limit_method": node.get("runtime_memory_limit_method", "MISSING"),
            }
        )
    status = "PASS" if entries and all((entry["io_threads_line_present"] is True or entry["io_threads_line_required"] is False) and entry["maxmemory_line_present"] for entry in entries) else "FAIL"
    _write_json(base / "generated_valkey_configs_manifest.json", _base_artifact("generated_valkey_configs_manifest", status=status, node_count=len(entries), entries=entries))
    if status != "PASS":
        errors.append("generated_valkey_configs_manifest rebuilt from run_state but did not PASS")


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
    projection["projection_only_reason"] = "Greater-than-200 coverage is dry-run projection only under P42 policy."
    _write_json(base / "dry_run_gt_200_projection.json", projection)


def _coverage_rows(base: Path) -> list[dict[str, Any]]:
    rows = [
        _row("fake_schema_unit", "PASS", ["tests/unit/test_server_profile_assertions.py"], execution_mode="unit_schema"),
        _real_row(base, "smoke_10", 10, base / "valkey_e2e_evidence.json"),
        _real_row(base, "real_30", 30, base / "valkey_e2e_evidence_30.json"),
        _real_row(base, "real_50", 50, base / "valkey_e2e_evidence_50.json"),
        _real_row(base, "real_100", 100, base / "valkey_e2e_evidence_100.json"),
        _real_row(base, "real_200", 200, base / "valkey_e2e_evidence_200.json"),
        _row("dry_run_gt_200", "DRY_RUN_PASS" if (base / "dry_run_gt_200_projection.json").exists() else "FAIL", [_artifact_ref(base / "dry_run_gt_200_projection.json")], execution_mode="dry_run_projection"),
    ]
    return rows


def _real_row(base: Path, coverage_id: str, expected_nodes: int, evidence_path: Path) -> dict[str, Any]:
    ok, reason = _real_evidence_status(evidence_path, expected_nodes)
    refs = [_artifact_ref(evidence_path)] if evidence_path.exists() else [_artifact_ref(base / "coverage_ledger.json")]
    return _row(coverage_id, "PASS" if ok else "SKIPPED_WITH_REASON", refs, reason=reason, execution_mode="real_valkey")


def _real_evidence_status(path: Path, expected_nodes: int) -> tuple[bool, str]:
    if not path.exists():
        return False, f"real Valkey evidence missing for {expected_nodes} nodes"
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, f"real Valkey evidence invalid JSON: {exc}"
    if obj.get("artifact_type") != "valkey_e2e_evidence":
        return False, "artifact_type is not valkey_e2e_evidence"
    if obj.get("status") != "PASS" or obj.get("probe_result") != "PASS":
        return False, "real Valkey evidence did not PASS"
    if obj.get("real_valkey") is not True:
        return False, "real Valkey evidence does not declare real_valkey=true"
    observed = _int(obj.get("nodes_observed"), 0)
    if observed < expected_nodes:
        return False, f"real Valkey evidence observed {observed}, expected at least {expected_nodes}"
    runtime = obj.get("runtime", {})
    profile = runtime.get("server_profile") if isinstance(runtime, dict) else {}
    if not isinstance(profile, dict) and "effective_io_threads" not in runtime:
        return False, "real Valkey evidence lacks runtime server profile fields"
    processes = obj.get("node_processes", [])
    if not isinstance(processes, list) or len(processes) < expected_nodes:
        return False, "real Valkey evidence lacks node_processes for expected nodes"
    if any(_int(item.get("effective_node_memory_limit_mb") if isinstance(item, dict) else None, 0) != 64 for item in processes[:expected_nodes]):
        return False, "real Valkey evidence node_processes do not record 64 MB memory"
    return True, ""


def _coverage_complete(rows: list[dict[str, Any]]) -> bool:
    return all(row.get("status") in {"PASS", "DRY_RUN_PASS"} for row in rows)


def _write_quant_artifacts(
    base: Path,
    profile: dict[str, Any],
    coverage_rows: list[dict[str, Any]],
    validation: dict[str, Any],
    errors: list[str],
) -> None:
    status = "PASS" if _coverage_complete(coverage_rows) and not errors else "FAIL"
    sources = [_artifact_ref(base / name) for name in ["effective_server_profile.json", "config_validation_report.json", "resource_preflight.json", "cluster_plan.json", "coverage_ledger.json", "dry_run_gt_200_projection.json"]]
    quant_summary = _base_artifact(
        "quant_summary",
        status=status,
        summary="P42 server-profile quantitative summary derived from validation, preflight, generated config, real evidence, and projection artifacts.",
        artifact_refs=sources,
        missing_data=[] if status == "PASS" else [{"field": "real_scale_coverage", "status": "MISSING", "reason": "One or more real P42 evidence rows did not PASS."}],
        runtime_claims={
            "real_valkey_claimed": status == "PASS",
            "management_runtime_claimed": False,
            "fault_runtime_claimed": False,
        },
        metrics=[
            {"name": "effective_io_threads", "status": "PASS", "value": profile.get("effective_io_threads"), "unit": "threads_per_node"},
            {"name": "effective_node_memory_limit_mb", "status": "PASS", "value": profile.get("effective_node_memory_limit_mb"), "unit": "MiB"},
        ],
        source_artifacts=sources,
    )
    _write_json(base / "quant_summary.json", quant_summary)
    _write_json(
        base / "analysis_summary.json",
        _base_artifact(
            "analysis_summary",
            status=status,
            findings=[
                {
                    "name": "server_profile_global_config",
                    "status": "PASS" if validation.get("status") == "PASS" else "FAIL",
                    "summary": "Global server profile fields are present in the effective config and validation report.",
                }
            ],
            missing_metrics=[] if status == "PASS" else [{"metric": "real_scale_coverage", "status": "MISSING", "reason": "One or more real P42 evidence rows did not PASS."}],
            source_artifacts=sources,
        ),
    )
    _write_json(
        base / "report_index.json",
        _base_artifact("report_index", status=status, reports=[], source_artifacts=sources, analysis_path=_artifact_ref(base / "analysis_summary.json")),
    )
    _write_json(
        base / "phase_summary.json",
        _base_artifact(
            "phase_summary",
            status=status,
            summary="P42 validates the global Valkey server profile, io-thread budgets, memory evidence, real scale coverage, and greater-than-200 dry-run projection.",
            required_artifacts=sources + [_artifact_ref(base / "generated_valkey_configs_manifest.json"), _artifact_ref(base / "run_state.json")],
            missing_metrics=[
                {"metric": item["field"], "status": item["status"], "reason": item["reason"]}
                for item in quant_summary["missing_data"]
            ],
            risks=[
                {
                    "risk": "P42 real evidence is bounded to the explicit 10/30/50/100/200 scale matrix; greater-than-200 remains projection-only.",
                    "severity": "low",
                    "required_before_next_phase": False,
                }
            ],
        ),
    )
    event = {
        "schema_version": "v1",
        "run_id": RUN_ID,
        "phase_id": PHASE,
        "scenario_name": "p42_server_profile_artifacts",
        "sample_id": "aggregate",
        "event_id": "p42-profile-artifacts-aggregate",
        "event_type": "server_profile_artifacts_built",
        "timestamp_unix_ms": 1783267200000,
        "monotonic_ms": 0,
        "severity": "INFO" if status == "PASS" else "ERROR",
        "subject_type": "stage",
        "subject_id": PHASE,
        "operation_id": "SKIPPED_WITH_REASON",
        "fault_id": "SKIPPED_WITH_REASON",
        "message": "P42 server profile artifact builder completed.",
        "metadata": {"status": status},
    }
    (base / "events.jsonl").write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    metric = {
        "schema_version": "v1",
        "run_id": RUN_ID,
        "phase_id": PHASE,
        "scenario_name": "p42_server_profile_artifacts",
        "sample_id": "aggregate",
        "timestamp_unix_ms": 1783267200000,
        "monotonic_ms": 0,
        "source_type": "harness",
        "source_id": "p42_server_profile_artifacts",
        "metric_name": "effective_node_memory_limit_mb",
        "metric_value": profile.get("effective_node_memory_limit_mb", "MISSING"),
        "metric_unit": "MiB",
        "labels": {"server_profile": profile.get("server_profile", "MISSING")},
        "missing_reason": "" if profile.get("effective_node_memory_limit_mb") != "MISSING" else "effective profile missing memory value",
    }
    (base / "metrics_timeseries.jsonl").write_text(json.dumps(metric, sort_keys=True) + "\n", encoding="utf-8")
    _write_json(
        base / "workload_windows.json",
        _base_artifact(
            "workload_windows",
            status=status,
            windows=[
                {
                    "window_name": "all_run",
                    "start_event_id": "p42-profile-artifacts-aggregate",
                    "end_event_id": "p42-profile-artifacts-aggregate",
                    "metrics": {
                        "requested_qps": "SKIPPED_WITH_REASON",
                        "achieved_qps": "SKIPPED_WITH_REASON",
                        "reason": "P42 artifact aggregation records server-profile evidence; workload metrics are supplied by real gate artifacts when present.",
                    },
                }
            ],
        ),
    )


def _base_artifact(artifact_type: str, *, status: str, **extra: Any) -> dict[str, Any]:
    obj = {
        "schema_version": "v1",
        "artifact_type": artifact_type,
        "phase_id": PHASE,
        "stage_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": status,
    }
    obj.update(extra)
    return obj


def _row(coverage_id: str, status: str, refs: list[str], *, execution_mode: str, reason: str = "") -> dict[str, Any]:
    row = {
        "coverage_id": coverage_id,
        "status": status,
        "execution_mode": execution_mode,
        "artifact_refs": refs,
    }
    if reason:
        row["reason"] = reason
    return row


def _stamp_phase(path: Path) -> None:
    obj = _load_json(path)
    if not obj:
        return
    obj["phase_id"] = PHASE
    obj["stage_id"] = PHASE
    obj["run_id"] = RUN_ID
    _write_json(path, obj)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _artifact_ref(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


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


if __name__ == "__main__":
    raise SystemExit(main())
