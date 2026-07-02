#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "codex" / "capability_matrix_loop" / "stage_manifest.json"
STATE = ROOT / "codex" / "capability_matrix_loop" / "state.json"
LOCK = ROOT / "codex" / "capability_matrix_loop" / "harness_lock.json"
SCHEMA_ROOT = ROOT / "schemas" / "capability_matrix_loop"
ARTIFACT_ROOT = ROOT / "artifacts" / "capability_matrix_loop"

sys.path.insert(0, str(ROOT / "scripts"))
from schema_validator import load_json, validate  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


NEGATIVE_CASE_CREATED_AT = "2026-07-02T00:00:00Z"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def write_json_if_missing(path: Path, data: Any) -> None:
    if path.exists():
        return
    write_json(path, data)


def load_manifest() -> dict[str, Any]:
    return load_json(MANIFEST)


def load_state() -> dict[str, Any]:
    return load_json(STATE)


def stage_by_id(stage_id: str) -> dict[str, Any]:
    for stage in load_manifest().get("stages", []):
        if stage.get("id") == stage_id:
            return stage
    raise SystemExit(f"unknown capability stage: {stage_id}")


def schema_errors(path: Path, schema_path_text: str) -> list[str]:
    schema_path = ROOT / schema_path_text
    if not schema_path.exists():
        return [f"schema missing: {schema_path_text}"]
    try:
        data = load_json(path)
    except json.JSONDecodeError as exc:
        return [f"{rel(path)} invalid JSON: {exc}"]
    return [f"{rel(path)} {err}" for err in validate(data, load_json(schema_path))]


def jsonl_schema_errors(path: Path, schema_path_text: str) -> list[str]:
    errors: list[str] = []
    schema_path = ROOT / schema_path_text
    if not schema_path.exists():
        return [f"schema missing: {schema_path_text}"]
    if not path.exists():
        return [f"jsonl artifact missing: {rel(path)}"]
    schema = load_json(schema_path)
    rows = 0
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            rows += 1
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                errors.append(f"{rel(path)} line {line_number} invalid JSON: {exc}")
                continue
            errors.extend(f"{rel(path)} line {line_number} {err}" for err in validate(data, schema))
    if rows == 0:
        errors.append(f"{rel(path)} has no JSONL records")
    return errors


def check_manifest() -> list[str]:
    errors: list[str] = []
    manifest = load_manifest()
    if manifest.get("schema_version") != "v1":
        errors.append("stage_manifest schema_version must be v1")
    if manifest.get("default_max_real_nodes") != 100:
        errors.append("default_max_real_nodes must be exactly 100")
    if set(manifest.get("forbidden_default_real_scales", [])) != {200, 500, 1000}:
        errors.append("forbidden_default_real_scales must include exactly 200, 500, 1000")
    seen: set[str] = set()
    for stage in manifest.get("stages", []):
        stage_id = stage.get("id", "")
        if not stage_id.startswith("CML"):
            errors.append(f"invalid CML stage id: {stage_id!r}")
        if stage_id in seen:
            errors.append(f"duplicate CML stage id: {stage_id}")
        seen.add(stage_id)
        max_real_nodes = int(stage.get("max_real_nodes", 0))
        if stage.get("automatic", True) and max_real_nodes > 100:
            errors.append(f"{stage_id}: automatic stage exceeds 100 real nodes")
        if stage.get("profile", "").startswith("real-") and max_real_nodes in {200, 500, 1000}:
            errors.append(f"{stage_id}: forbidden default real scale {max_real_nodes}")
        if stage_id == "CML00_CAPABILITY_LOOP_BOOTSTRAP":
            if not stage.get("negative_requirements"):
                errors.append("CML00 must declare negative requirements")
            if stage.get("real_valkey_required"):
                errors.append("CML00 must not require real Valkey")
        if stage_id == "CML01_UNIFIED_OBSERVATION_AND_ARTIFACT_MODEL":
            if int(stage.get("max_real_nodes", 0)) > 6:
                errors.append("CML01 must remain capped at 6 real nodes")
            if not stage.get("real_valkey_required"):
                errors.append("CML01 must require real Valkey evidence")
            required_paths = {artifact.get("path") for artifact in stage.get("required_artifacts", [])}
            for suffix in [
                "samples/operation_event.jsonl",
                "samples/fault_event.jsonl",
                "samples/metrics_window.jsonl",
                "samples/workload_window.jsonl",
                "capability_matrix.json",
                "analysis_summary.json",
                "reports/report_index.json",
            ]:
                if not any(str(path).endswith(suffix) for path in required_paths):
                    errors.append(f"CML01 manifest missing required artifact suffix: {suffix}")
    return errors


def check_state() -> list[str]:
    errors: list[str] = []
    state = load_state()
    if state.get("schema_version") != "v1":
        errors.append("state schema_version must be v1")
    if state.get("loop_id") != "capability_matrix_loop":
        errors.append("state loop_id must be capability_matrix_loop")
    if "completed_stages" not in state:
        errors.append("state missing completed_stages")
    return errors


def check_lock() -> list[str]:
    errors: list[str] = []
    lock = load_json(LOCK)
    if lock.get("schema_version") != "v1":
        errors.append("harness_lock schema_version must be v1")
    for item in lock.get("files", []):
        path_text = item.get("path", "")
        path = ROOT / path_text
        if not path.exists():
            errors.append(f"locked CML harness file missing: {path_text}")
            continue
        actual = sha256_file(path)
        if actual != item.get("sha256"):
            errors.append(f"locked CML harness file changed: {path_text}")
    return errors


def validate_required_artifacts(stage: dict[str, Any], *, include_gate_result: bool = False) -> list[str]:
    errors: list[str] = []
    for artifact in stage.get("required_artifacts", []):
        path_text = artifact["path"]
        if path_text.endswith("validation/current_stage_gate_result.json") and not include_gate_result:
            continue
        if not include_gate_result and (
            path_text.endswith("/stage_result.json")
            or path_text.endswith("/next_stage_context.md")
            or path_text.endswith("/AUDIT.md")
            or path_text.endswith("/audit_decision.json")
        ):
            continue
        path = ROOT / path_text
        if not path.exists():
            errors.append(f"required artifact missing: {path_text}")
            continue
        if artifact.get("schema"):
            errors.extend(schema_errors(path, artifact["schema"]))
    return errors


def validate_baseline(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"baseline missing: {rel(path)}"]
    baseline = load_json(path)
    for idx, row in enumerate(baseline.get("capabilities", [])):
        status = row.get("status")
        evidence_paths = row.get("evidence_paths", [])
        if status == "PASS" and not evidence_paths:
            errors.append(f"baseline row {idx} PASS without evidence_paths")
        if row.get("real_valkey_required"):
            for evidence_path in evidence_paths:
                evidence_file = ROOT / evidence_path
                if not evidence_file.exists():
                    errors.append(f"baseline row {idx} evidence missing: {evidence_path}")
                    continue
                try:
                    evidence = load_json(evidence_file)
                except json.JSONDecodeError as exc:
                    errors.append(f"baseline row {idx} evidence invalid JSON: {exc}")
                    continue
                if evidence.get("real_valkey") is not True:
                    errors.append(f"baseline row {idx} fake real_valkey evidence: {evidence_path}")
                if evidence.get("valkey_version_prefix_required") != "9.1.":
                    errors.append(f"baseline row {idx} wrong Valkey version requirement: {evidence_path}")
                if evidence.get("probe_result") != "PASS":
                    errors.append(f"baseline row {idx} probe_result not PASS: {evidence_path}")
        if row.get("cleanup_required") and status in {"PASS", "PARTIAL"} and not row.get("cleanup_evidence_paths"):
            errors.append(f"baseline row {idx} cleanup required but missing evidence")
        if status == "SKIPPED_WITH_REASON" and row.get("target_capability"):
            errors.append(f"baseline row {idx} target capability cannot pass as skipped")
        for report in row.get("report_artifacts", []):
            if not report.get("source_artifacts"):
                errors.append(f"baseline row {idx} report artifact missing source_artifacts")
            for source in report.get("source_artifacts", []):
                if not source.get("sha256"):
                    errors.append(f"baseline row {idx} report source missing sha256")
        if row.get("source_stage") and row.get("source_stage") != row.get("current_stage", row.get("source_stage")):
            errors.append(f"baseline row {idx} old artifact reused as current stage evidence")
    return errors


def make_negative_cases() -> list[dict[str, Any]]:
    base = {
        "capability": "negative_fake_real",
        "scale_nodes": 30,
        "status": "PASS",
        "evidence_paths": [],
        "real_valkey_required": True,
        "cleanup_required": True,
        "cleanup_evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/cleanup_report_scale_30.json"],
        "report_artifacts": [
            {
                "path": "reports/fake.html",
                "source_artifacts": [
                    {"path": "artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json", "sha256": "x"}
                ]
            }
        ],
    }
    cases: list[tuple[str, dict[str, Any], str]] = [
        ("missing_artifact", {"capabilities": []}, "required artifact missing"),
        ("fake_real_valkey_evidence", {"capabilities": [base | {"evidence_paths": ["artifacts/capability_matrix_loop/CML00_CAPABILITY_LOOP_BOOTSTRAP/validation/fake_valkey_evidence.json"]}]}, "fake real_valkey evidence"),
        ("skip_as_pass", {"capabilities": [base | {"status": "SKIPPED_WITH_REASON", "target_capability": True, "evidence_paths": []}]}, "target capability cannot pass as skipped"),
        ("cleanup_missing", {"capabilities": [base | {"evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json"], "cleanup_evidence_paths": []}]}, "cleanup required"),
        ("report_without_checksum", {"capabilities": [base | {"evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json"], "report_artifacts": [{"path": "reports/no_checksum.html", "source_artifacts": [{"path": "artifact.json"}]}]}]}, "report source missing sha256"),
        ("old_artifact_reuse", {"capabilities": [base | {"evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json"], "source_stage": "P12_SCALE_LADDER_10_30", "current_stage": "CML00_CAPABILITY_LOOP_BOOTSTRAP"}]}, "old artifact reused"),
    ]
    results: list[dict[str, Any]] = []
    fake_path = ROOT / "artifacts" / "capability_matrix_loop" / "CML00_CAPABILITY_LOOP_BOOTSTRAP" / "validation" / "fake_valkey_evidence.json"
    write_json_if_missing(
        fake_path,
        {
            "schema_version": "v1",
            "artifact_type": "valkey_e2e_evidence",
            "phase_id": "P12_SCALE_LADDER_10_30",
            "run_id": "fake-negative-case",
            "created_at": NEGATIVE_CASE_CREATED_AT,
            "producer": {"name": "capability_matrix_gate", "version": "negative"},
            "status": "PASS",
            "real_valkey": False,
            "valkey_version_prefix_required": "9.1.",
            "probe_result": "PASS",
            "nodes_observed": 30,
            "cluster_state_observed": "ok",
            "data_path_result": "PASS",
            "probes": [{"logical_id": "fake", "host": "127.0.0.1", "port": 1, "status": "PASS"}],
            "cleanup": {"status": "PASS"},
        },
    )
    for name, payload, expected in cases:
        if name == "missing_artifact":
            errors = ["required artifact missing: synthetic"]
        else:
            tmp = ROOT / "artifacts" / "capability_matrix_loop" / "CML00_CAPABILITY_LOOP_BOOTSTRAP" / "validation" / f"{name}.baseline.json"
            write_json_if_missing(
                tmp,
                {
                    "schema_version": "v1",
                    "artifact_type": "capability_matrix_baseline",
                    "stage_id": "CML00_CAPABILITY_LOOP_BOOTSTRAP",
                    "status": "PASS",
                    "created_at": NEGATIVE_CASE_CREATED_AT,
                    **payload,
                },
            )
            errors = validate_baseline(tmp)
        results.append(
            {
                "name": name,
                "status": "PASS" if any(expected in error for error in errors) else "FAIL",
                "expected_error_fragment": expected,
                "observed_errors": errors,
            }
        )
    return results


def cml01_paths(stage_id: str) -> dict[str, Path]:
    stage_root = ARTIFACT_ROOT / stage_id
    return {
        "operation": stage_root / "samples" / "operation_event.jsonl",
        "fault": stage_root / "samples" / "fault_event.jsonl",
        "metrics": stage_root / "samples" / "metrics_window.jsonl",
        "workload": stage_root / "samples" / "workload_window.jsonl",
        "evidence": stage_root / "samples" / "real_valkey_evidence.json",
        "matrix": stage_root / "capability_matrix.json",
        "analysis": stage_root / "analysis_summary.json",
        "report_index": stage_root / "reports" / "report_index.json",
    }


def cml02_paths(stage_id: str) -> dict[str, Path]:
    stage_root = ARTIFACT_ROOT / stage_id
    return {
        "operation": stage_root / "samples" / "operation_event.jsonl",
        "fault": stage_root / "samples" / "fault_event.jsonl",
        "metrics": stage_root / "samples" / "metrics_window.jsonl",
        "workload": stage_root / "samples" / "workload_window.jsonl",
        "evidence": stage_root / "samples" / "real_valkey_evidence_30.json",
        "state": stage_root / "samples" / "state_scale_30.json",
        "cleanup": stage_root / "samples" / "cleanup_report_scale_30.json",
        "matrix": stage_root / "capability_matrix.json",
        "analysis": stage_root / "analysis_summary.json",
        "report_index": stage_root / "reports" / "report_index.json",
    }


def cml03_paths(stage_id: str) -> dict[str, Path]:
    stage_root = ARTIFACT_ROOT / stage_id
    return {
        "operation": stage_root / "samples" / "operation_event.jsonl",
        "fault": stage_root / "samples" / "fault_event.jsonl",
        "metrics": stage_root / "samples" / "metrics_window.jsonl",
        "workload": stage_root / "samples" / "workload_window.jsonl",
        "evidence": stage_root / "samples" / "real_valkey_evidence_fault_30.json",
        "fault_report": stage_root / "samples" / "fault_report_30.json",
        "failover_report": stage_root / "samples" / "failover_report_30.json",
        "workload_report": stage_root / "samples" / "workload_window_report_30.json",
        "cleanup": stage_root / "samples" / "cleanup_report_fault_30.json",
        "matrix": stage_root / "capability_matrix.json",
        "analysis": stage_root / "analysis_summary.json",
        "report_index": stage_root / "reports" / "report_index.json",
    }


def cml04_paths(stage_id: str) -> dict[str, Path]:
    stage_root = ARTIFACT_ROOT / stage_id
    return {
        "operation": stage_root / "samples" / "operation_event.jsonl",
        "fault": stage_root / "samples" / "fault_event.jsonl",
        "metrics": stage_root / "samples" / "metrics_window.jsonl",
        "workload": stage_root / "samples" / "workload_window.jsonl",
        "evidence": stage_root / "samples" / "real_valkey_evidence_network_30.json",
        "fault_report": stage_root / "samples" / "network_fault_report_30.json",
        "cleanup": stage_root / "samples" / "cleanup_report.json",
        "matrix": stage_root / "capability_matrix.json",
        "analysis": stage_root / "analysis_summary.json",
        "report_index": stage_root / "reports" / "report_index.json",
    }


def cml05_paths(stage_id: str) -> dict[str, Path]:
    stage_root = ARTIFACT_ROOT / stage_id
    return {
        "operation": stage_root / "samples" / "operation_event.jsonl",
        "fault": stage_root / "samples" / "fault_event.jsonl",
        "metrics": stage_root / "samples" / "metrics_window.jsonl",
        "workload": stage_root / "samples" / "workload_window.jsonl",
        "evidence": stage_root / "samples" / "real_valkey_evidence_failover_30.json",
        "fault_report": stage_root / "samples" / "fault_report_30.json",
        "failover_report": stage_root / "samples" / "failover_report_30.json",
        "workload_report": stage_root / "samples" / "workload_window_report_30.json",
        "cleanup": stage_root / "samples" / "cleanup_report_failover_30.json",
        "matrix": stage_root / "capability_matrix.json",
        "analysis": stage_root / "analysis_summary.json",
        "report_index": stage_root / "reports" / "report_index.json",
    }


def cml06_paths(stage_id: str) -> dict[str, Path]:
    stage_root = ARTIFACT_ROOT / stage_id
    return {
        "operation": stage_root / "samples" / "operation_event.jsonl",
        "fault": stage_root / "samples" / "fault_event.jsonl",
        "metrics": stage_root / "samples" / "metrics_window.jsonl",
        "workload": stage_root / "samples" / "workload_window.jsonl",
        "evidence": stage_root / "samples" / "real_valkey_evidence_split_brain_30.json",
        "fault_report": stage_root / "samples" / "fault_report_30.json",
        "failover_report": stage_root / "samples" / "failover_report_30.json",
        "workload_report": stage_root / "samples" / "workload_window_report_30.json",
        "cleanup": stage_root / "samples" / "cleanup_report_split_brain_30.json",
        "matrix": stage_root / "capability_matrix.json",
        "analysis": stage_root / "analysis_summary.json",
        "report_index": stage_root / "reports" / "report_index.json",
    }


def cml07_paths(stage_id: str) -> dict[str, Path]:
    stage_root = ARTIFACT_ROOT / stage_id
    return {
        "operation": stage_root / "samples" / "operation_event.jsonl",
        "fault": stage_root / "samples" / "fault_event.jsonl",
        "metrics": stage_root / "samples" / "metrics_window.jsonl",
        "workload": stage_root / "samples" / "workload_window.jsonl",
        "evidence": stage_root / "samples" / "real_valkey_evidence_workload_windows_30.json",
        "fault_report": stage_root / "samples" / "fault_report_30.json",
        "failover_report": stage_root / "samples" / "failover_report_30.json",
        "workload_report": stage_root / "samples" / "workload_window_report_30.json",
        "cleanup": stage_root / "samples" / "cleanup_report_workload_windows_30.json",
        "matrix": stage_root / "capability_matrix.json",
        "analysis": stage_root / "analysis_summary.json",
        "report_index": stage_root / "reports" / "report_index.json",
    }


def cml08_paths(stage_id: str) -> dict[str, Path]:
    stage_root = ARTIFACT_ROOT / stage_id
    return {
        "operation": stage_root / "samples" / "operation_event.jsonl",
        "fault": stage_root / "samples" / "fault_event.jsonl",
        "metrics": stage_root / "samples" / "metrics_window.jsonl",
        "workload": stage_root / "samples" / "workload_window.jsonl",
        "evidence": stage_root / "samples" / "real_valkey_evidence_bounded_soak_30.json",
        "state": stage_root / "samples" / "state_bounded_soak_30.json",
        "soak_report": stage_root / "samples" / "bounded_soak_report_30_60.json",
        "soak_metrics": stage_root / "samples" / "soak_metrics_30_60.jsonl",
        "cleanup": stage_root / "samples" / "cleanup_report_bounded_soak_30.json",
        "matrix": stage_root / "capability_matrix.json",
        "analysis": stage_root / "analysis_summary.json",
        "report_index": stage_root / "reports" / "report_index.json",
    }


def cml09_paths(stage_id: str) -> dict[str, Path]:
    stage_root = ARTIFACT_ROOT / stage_id
    return {
        "operation": stage_root / "samples" / "operation_event.jsonl",
        "fault": stage_root / "samples" / "fault_event.jsonl",
        "metrics": stage_root / "samples" / "metrics_window.jsonl",
        "workload": stage_root / "samples" / "workload_window.jsonl",
        "evidence": stage_root / "samples" / "real_valkey_evidence_reporting_close_30.json",
        "evidence_index": stage_root / "samples" / "evidence_index_30.json",
        "matrix": stage_root / "capability_matrix.json",
        "analysis": stage_root / "analysis_summary.json",
        "report_index": stage_root / "reports" / "report_index.json",
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def source_checksum_errors(source_artifacts: list[dict[str, Any]], owner: str) -> list[str]:
    errors: list[str] = []
    for idx, source in enumerate(source_artifacts):
        path_text = source.get("path")
        checksum = source.get("sha256")
        if not path_text:
            errors.append(f"{owner} source {idx} missing path")
            continue
        path = ROOT / path_text
        if not path.exists():
            errors.append(f"{owner} source {idx} missing artifact: {path_text}")
            continue
        if not checksum:
            errors.append(f"{owner} source {idx} missing sha256")
            continue
        actual = sha256_file(path)
        if actual != checksum:
            errors.append(f"{owner} source {idx} sha256 mismatch: {path_text}")
    return errors


def validate_observation_model(stage_id: str, paths: dict[str, Path] | None = None) -> list[str]:
    paths = paths or cml01_paths(stage_id)
    errors: list[str] = []
    schema_pairs = [
        ("operation", "schemas/capability_matrix_loop/operation_event.schema.json"),
        ("fault", "schemas/capability_matrix_loop/fault_event.schema.json"),
        ("metrics", "schemas/capability_matrix_loop/metrics_window.schema.json"),
        ("workload", "schemas/capability_matrix_loop/workload_window.schema.json"),
    ]
    for key, schema in schema_pairs:
        errors.extend(jsonl_schema_errors(paths[key], schema))
    errors.extend(schema_errors(paths["matrix"], "schemas/capability_matrix_loop/capability_matrix.schema.json"))
    errors.extend(schema_errors(paths["analysis"], "schemas/capability_matrix_loop/capability_analysis_summary.schema.json"))
    errors.extend(schema_errors(paths["report_index"], "schemas/capability_matrix_loop/capability_report_index.schema.json"))
    if errors:
        return errors

    evidence = load_json(paths["evidence"])
    if evidence.get("real_valkey") is not True:
        errors.append("CML01 real sample is not real_valkey evidence")
    if evidence.get("probe_result") != "PASS":
        errors.append("CML01 real sample probe_result is not PASS")
    if evidence.get("data_path_result") != "PASS":
        errors.append("CML01 real sample data_path_result is not PASS")
    if int(evidence.get("nodes_observed", 0)) < 6:
        errors.append("CML01 real sample must observe at least 6 nodes")
    versions = evidence.get("valkey_versions", [])
    if not versions or any(not str(version).startswith("9.1.") for version in versions):
        errors.append("CML01 real sample must record Valkey 9.1.x versions")

    metrics_rows = load_jsonl(paths["metrics"])
    workload_rows = load_jsonl(paths["workload"])
    all_windows = {"before", "operation_or_fault_apply", "during", "clear_or_recovery_start", "after_recovery", "all_run"}
    metrics_windows = {str(row.get("window_id")) for row in metrics_rows}
    workload_windows = {str(row.get("window_id")) for row in workload_rows}
    if metrics_windows != all_windows:
        errors.append(f"CML01 metrics windows mismatch: {sorted(metrics_windows)}")
    if workload_windows != all_windows:
        errors.append(f"CML01 workload windows mismatch: {sorted(workload_windows)}")
    for row in metrics_rows:
        owner = f"metrics_window {row.get('window_id')}"
        if row.get("current_stage") != stage_id or row.get("source_stage") != stage_id:
            errors.append(f"{owner} old artifact reused as current stage evidence")
        if row.get("status") == "PASS" and int(row.get("sample_count", 0)) <= 0:
            errors.append(f"{owner} PASS without samples")
        metrics = row.get("metrics", {})
        for key, value in metrics.items():
            if value == 0 and str(row.get("status")) in {"MISSING", "UNSUPPORTED_WITH_EVIDENCE"}:
                errors.append(f"{owner} zero-filled missing metric: {key}")
        errors.extend(source_checksum_errors(row.get("source_artifacts", []), owner))
    for row in workload_rows:
        owner = f"workload_window {row.get('window_id')}"
        if row.get("current_stage") != stage_id or row.get("source_stage") != stage_id:
            errors.append(f"{owner} old artifact reused as current stage evidence")
        if row.get("status") == "PASS" and int(row.get("sample_count", 0)) <= 0:
            errors.append(f"{owner} PASS without samples")
        errors.extend(source_checksum_errors(row.get("source_artifacts", []), owner))

    report_index = load_json(paths["report_index"])
    report_kinds = {report.get("kind") for report in report_index.get("reports", [])}
    if report_kinds != {"csv", "markdown", "html", "chart"}:
        errors.append(f"CML01 report index must include csv, markdown, html, chart: {sorted(report_kinds)}")
    for report in report_index.get("reports", []):
        report_path = ROOT / str(report.get("path", ""))
        if not report_path.exists():
            errors.append(f"report path missing: {report.get('path')}")
        errors.extend(source_checksum_errors(report.get("source_artifacts", []), f"report {report.get('kind')}"))

    matrix = load_json(paths["matrix"])
    for row in matrix.get("capabilities", []):
        chain = row.get("evidence_chain", {})
        for key, path_text in chain.items():
            if not (ROOT / str(path_text)).exists():
                errors.append(f"capability matrix chain missing {key}: {path_text}")
        if row.get("real_valkey_required") is True and row.get("status") == "PASS" and not chain:
            errors.append("capability matrix PASS without evidence chain")
    return errors


def make_cml01_negative_cases(stage_id: str) -> list[dict[str, Any]]:
    paths = cml01_paths(stage_id)
    validation_dir = ARTIFACT_ROOT / stage_id / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    cases: list[tuple[str, str, dict[str, Path], str]] = []

    empty_metrics = validation_dir / "negative_empty_metrics.jsonl"
    empty_metrics.write_text("", encoding="utf-8")
    cases.append(("empty_metrics", "metrics", {"metrics": empty_metrics}, "has no JSONL records"))

    zero_missing = validation_dir / "negative_zero_filled_missing.jsonl"
    rows = load_jsonl(paths["metrics"])
    bad = dict(rows[0])
    bad["status"] = "MISSING"
    bad["metrics"] = {"qps": 0}
    zero_missing.write_text(json.dumps(bad, sort_keys=True) + "\n", encoding="utf-8")
    cases.append(("zero_filled_missing", "metrics", {"metrics": zero_missing}, "zero-filled missing metric"))

    no_checksum = validation_dir / "negative_report_no_checksum.json"
    report = load_json(paths["report_index"])
    report["reports"][0]["source_artifacts"][0].pop("sha256", None)
    write_json(no_checksum, report)
    cases.append(("report_without_checksum", "report_index", {"report_index": no_checksum}, "missing required key 'sha256'"))

    old_reuse = validation_dir / "negative_old_artifact_reuse.jsonl"
    bad_old = dict(rows[0])
    bad_old["source_stage"] = "P12_SCALE_LADDER_10_30"
    old_reuse.write_text(json.dumps(bad_old, sort_keys=True) + "\n", encoding="utf-8")
    cases.append(("old_artifact_reuse", "metrics", {"metrics": old_reuse}, "old artifact reused"))

    fake_evidence = validation_dir / "negative_fake_real_valkey_evidence.json"
    fake = load_json(paths["evidence"])
    fake["real_valkey"] = False
    write_json(fake_evidence, fake)
    cases.append(("fake_real_valkey_evidence", "evidence", {"evidence": fake_evidence}, "not real_valkey evidence"))

    results: list[dict[str, Any]] = []
    for name, _, overrides, expected in cases:
        candidate_paths = dict(paths)
        candidate_paths.update(overrides)
        observed = validate_observation_model(stage_id, candidate_paths)
        results.append(
            {
                "name": name,
                "status": "PASS" if any(expected in error for error in observed) else "FAIL",
                "expected_error_fragment": expected,
                "observed_errors": observed,
            }
        )
    return results


def validate_cml02_management_ops(stage_id: str, paths: dict[str, Path] | None = None) -> list[str]:
    paths = paths or cml02_paths(stage_id)
    errors: list[str] = []
    errors.extend(validate_observation_model(stage_id, {**cml01_paths(stage_id), **{k: v for k, v in paths.items() if k in cml01_paths(stage_id)}}))
    if errors:
        return errors
    evidence = load_json(paths["evidence"])
    if int(evidence.get("nodes_observed", 0)) != 30:
        errors.append(f"CML02 evidence nodes_observed must be 30, got {evidence.get('nodes_observed')}")
    cleanup = load_json(paths["cleanup"])
    if cleanup.get("status") != "PASS" or cleanup.get("resources_remaining") not in ([], None):
        errors.append("CML02 cleanup must PASS with no resources_remaining")
    state = load_json(paths["state"])
    operations = state.get("runtime", {}).get("operations", [])
    required_ops = {
        "tree_fanout_meet_primaries",
        "parallel_add_slots",
        "tree_fanout_meet_replicas",
        "parallel_add_replicas",
        "final_cluster_check",
    }
    observed_ops = {str(op.get("operation")) for op in operations if op.get("status") == "PASS"}
    missing = sorted(required_ops - observed_ops)
    if missing:
        errors.append(f"CML02 missing PASS management operations: {missing}")
    for op in operations:
        if op.get("operation") in required_ops and not isinstance(op.get("duration_seconds"), (int, float)):
            errors.append(f"CML02 operation missing numeric duration: {op.get('operation')}")
    operation_rows = load_jsonl(paths["operation"])
    operation_ids = {row.get("operation_id") for row in operation_rows if row.get("status") == "PASS"}
    missing_rows = sorted(required_ops - operation_ids)
    if missing_rows:
        errors.append(f"CML02 operation_event missing required operations: {missing_rows}")
    workload_rows = load_jsonl(paths["workload"])
    required_windows = {"before", "operation_or_fault_apply", "during", "clear_or_recovery_start", "after_recovery", "all_run"}
    pass_windows = {row.get("window_id") for row in workload_rows if row.get("status") == "PASS"}
    if pass_windows != required_windows:
        errors.append(f"CML02 workload windows must all PASS: {sorted(pass_windows)}")
    return errors


def make_cml02_negative_cases(stage_id: str) -> list[dict[str, Any]]:
    paths = cml02_paths(stage_id)
    validation_dir = ARTIFACT_ROOT / stage_id / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    cases: list[tuple[str, dict[str, Path], str]] = []

    bad_evidence = validation_dir / "negative_wrong_node_count_evidence.json"
    evidence = load_json(paths["evidence"])
    evidence["nodes_observed"] = 29
    write_json(bad_evidence, evidence)
    cases.append(("wrong_node_count", {"evidence": bad_evidence}, "nodes_observed must be 30"))

    missing_ops_state = validation_dir / "negative_missing_management_op_state.json"
    state = load_json(paths["state"])
    state["runtime"]["operations"] = [op for op in state.get("runtime", {}).get("operations", []) if op.get("operation") != "parallel_add_replicas"]
    write_json(missing_ops_state, state)
    cases.append(("missing_management_operation", {"state": missing_ops_state}, "missing PASS management operations"))

    bad_cleanup = validation_dir / "negative_cleanup_not_clean.json"
    cleanup = load_json(paths["cleanup"])
    cleanup["resources_remaining"] = [{"type": "container", "id": "leaked"}]
    write_json(bad_cleanup, cleanup)
    cases.append(("cleanup_residue", {"cleanup": bad_cleanup}, "cleanup must PASS"))

    empty_workload = validation_dir / "negative_empty_workload.jsonl"
    empty_workload.write_text("", encoding="utf-8")
    cases.append(("empty_workload_windows", {"workload": empty_workload}, "has no JSONL records"))

    results: list[dict[str, Any]] = []
    for name, overrides, expected in cases:
        candidate_paths = dict(paths)
        candidate_paths.update(overrides)
        observed = validate_cml02_management_ops(stage_id, candidate_paths)
        results.append(
            {
                "name": name,
                "status": "PASS" if any(expected in error for error in observed) else "FAIL",
                "expected_error_fragment": expected,
                "observed_errors": observed,
            }
        )
    return results


def validate_cml03_faults(stage_id: str, paths: dict[str, Path] | None = None) -> list[str]:
    paths = paths or cml03_paths(stage_id)
    errors: list[str] = []
    observation_paths = {**cml01_paths(stage_id), **{k: v for k, v in paths.items() if k in cml01_paths(stage_id)}}
    errors.extend(validate_observation_model(stage_id, observation_paths))
    if errors:
        return errors
    evidence = load_json(paths["evidence"])
    if int(evidence.get("nodes_observed_before", 0)) != 30:
        errors.append("CML03 evidence must observe 30 nodes before fault")
    if int(evidence.get("nodes_observed_after_clear", 0)) != 30:
        errors.append("CML03 evidence must recover to 30 nodes after clear")
    if evidence.get("data_path_result") != "PASS":
        errors.append("CML03 data_path_result must be PASS")
    fault_report = load_json(paths["fault_report"])
    faults = fault_report.get("faults", [])
    if not faults:
        errors.append("CML03 fault_report missing faults")
    else:
        fault = faults[0]
        if fault.get("fault_type") != "node_stop":
            errors.append("CML03 fault type must be node_stop")
        if fault.get("scope") != "owned_container_or_process":
            errors.append("CML03 fault scope must be owned_container_or_process")
        if fault.get("apply_status") != "PASS" or fault.get("clear_status") != "PASS":
            errors.append("CML03 fault apply and clear must PASS")
    safety = fault_report.get("safety_checks", {})
    if safety.get("host_network_mutated") is not False or safety.get("global_firewall_mutated") is not False or safety.get("sandbox_only") is not True:
        errors.append("CML03 safety checks must prove sandbox-only fault")
    failover = load_json(paths["failover_report"])
    if failover.get("status") != "PASS" or not failover.get("failovers"):
        errors.append("CML03 failover_report must PASS with a failover")
    workload_report = load_json(paths["workload_report"])
    windows = {window.get("name"): window for window in workload_report.get("windows", [])}
    for required in ["before_fault", "during_fault", "after_recovery"]:
        if required not in windows:
            errors.append(f"CML03 workload report missing {required}")
    cleanup = load_json(paths["cleanup"])
    if cleanup.get("status") != "PASS" or cleanup.get("resources_remaining") not in ([], None):
        errors.append("CML03 cleanup must PASS with no resources_remaining")
    return errors


def make_cml03_negative_cases(stage_id: str) -> list[dict[str, Any]]:
    paths = cml03_paths(stage_id)
    validation_dir = ARTIFACT_ROOT / stage_id / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    cases: list[tuple[str, dict[str, Path], str]] = []
    bad_fault = validation_dir / "negative_wrong_fault_scope.json"
    fault_report = load_json(paths["fault_report"])
    fault_report["faults"][0]["scope"] = "host_network"
    write_json(bad_fault, fault_report)
    cases.append(("wrong_fault_scope", {"fault_report": bad_fault}, "owned_container_or_process"))
    bad_recovery = validation_dir / "negative_no_recovery_evidence.json"
    evidence = load_json(paths["evidence"])
    evidence["nodes_observed_after_clear"] = 29
    write_json(bad_recovery, evidence)
    cases.append(("missing_after_clear_recovery", {"evidence": bad_recovery}, "recover to 30"))
    bad_workload = validation_dir / "negative_missing_after_recovery_workload.json"
    workload = load_json(paths["workload_report"])
    workload["windows"] = [window for window in workload.get("windows", []) if window.get("name") != "after_recovery"]
    write_json(bad_workload, workload)
    cases.append(("missing_after_recovery_workload", {"workload_report": bad_workload}, "missing after_recovery"))
    bad_cleanup = validation_dir / "negative_cleanup_residue.json"
    cleanup = load_json(paths["cleanup"])
    cleanup["resources_remaining"] = [{"type": "process", "id": "leaked"}]
    write_json(bad_cleanup, cleanup)
    cases.append(("cleanup_residue", {"cleanup": bad_cleanup}, "cleanup must PASS"))
    results: list[dict[str, Any]] = []
    for name, overrides, expected in cases:
        candidate_paths = dict(paths)
        candidate_paths.update(overrides)
        observed = validate_cml03_faults(stage_id, candidate_paths)
        results.append(
            {
                "name": name,
                "status": "PASS" if any(expected in error for error in observed) else "FAIL",
                "expected_error_fragment": expected,
                "observed_errors": observed,
            }
        )
    return results


def validate_cml04_network_faults(stage_id: str, paths: dict[str, Path] | None = None) -> list[str]:
    paths = paths or cml04_paths(stage_id)
    errors: list[str] = []
    for key, schema in [
        ("operation", "schemas/capability_matrix_loop/operation_event.schema.json"),
        ("fault", "schemas/capability_matrix_loop/fault_event.schema.json"),
        ("metrics", "schemas/capability_matrix_loop/metrics_window.schema.json"),
        ("workload", "schemas/capability_matrix_loop/workload_window.schema.json"),
    ]:
        errors.extend(jsonl_schema_errors(paths[key], schema))
    errors.extend(schema_errors(paths["matrix"], "schemas/capability_matrix_loop/capability_matrix.schema.json"))
    errors.extend(schema_errors(paths["analysis"], "schemas/capability_matrix_loop/capability_analysis_summary.schema.json"))
    errors.extend(schema_errors(paths["report_index"], "schemas/capability_matrix_loop/capability_report_index.schema.json"))
    if errors:
        return errors
    evidence = load_json(paths["evidence"])
    if evidence.get("real_valkey") is not True or evidence.get("probe_result") != "PASS":
        errors.append("CML04 evidence must be real Valkey with PASS probe_result")
    if int(evidence.get("nodes_observed", 0)) != 30:
        errors.append("CML04 evidence nodes_observed must be 30")
    if evidence.get("data_path_result") != "SKIPPED_WITH_REASON":
        errors.append("CML04 network safety evidence must explicitly skip data path with reason")
    fault_report = load_json(paths["fault_report"])
    fault = (fault_report.get("faults") or [{}])[0]
    if fault.get("fault_type") not in {"network_delay", "network_partition"}:
        errors.append("CML04 fault type must be network_delay or network_partition")
    if fault.get("scope") != "container_namespace_or_sandbox_proxy":
        errors.append("CML04 fault scope must be container_namespace_or_sandbox_proxy")
    if fault.get("apply_status") != "PASS" or fault.get("clear_status") != "PASS":
        errors.append("CML04 network fault apply and clear must PASS")
    safety = fault_report.get("safety_checks", {})
    if safety.get("host_network_mutated") is not False or safety.get("global_firewall_mutated") is not False or safety.get("sandbox_only") is not True:
        errors.append("CML04 safety checks must prove sandbox-only network fault")
    cleanup = load_json(paths["cleanup"])
    if cleanup.get("status") != "PASS" or cleanup.get("resources_remaining") not in ([], None):
        errors.append("CML04 cleanup must PASS with no resources_remaining")
    for row in load_jsonl(paths["metrics"]) + load_jsonl(paths["workload"]):
        if row.get("source_stage") != stage_id or row.get("current_stage") != stage_id:
            errors.append(f"CML04 old artifact reused in {row.get('artifact_type')} {row.get('window_id')}")
        errors.extend(source_checksum_errors(row.get("source_artifacts", []), f"CML04 {row.get('artifact_type')} {row.get('window_id')}"))
    report_index = load_json(paths["report_index"])
    for report in report_index.get("reports", []):
        errors.extend(source_checksum_errors(report.get("source_artifacts", []), f"CML04 report {report.get('kind')}"))
    return errors


def make_cml04_negative_cases(stage_id: str) -> list[dict[str, Any]]:
    paths = cml04_paths(stage_id)
    validation_dir = ARTIFACT_ROOT / stage_id / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    cases: list[tuple[str, dict[str, Path], str]] = []
    bad_scope = validation_dir / "negative_host_network_scope.json"
    report = load_json(paths["fault_report"])
    report["faults"][0]["scope"] = "host_network"
    write_json(bad_scope, report)
    cases.append(("host_network_scope", {"fault_report": bad_scope}, "container_namespace_or_sandbox_proxy"))
    bad_nodes = validation_dir / "negative_wrong_node_count.json"
    evidence = load_json(paths["evidence"])
    evidence["nodes_observed"] = 29
    write_json(bad_nodes, evidence)
    cases.append(("wrong_node_count", {"evidence": bad_nodes}, "nodes_observed must be 30"))
    bad_safety = validation_dir / "negative_host_network_mutated.json"
    safety_report = load_json(paths["fault_report"])
    safety_report["safety_checks"]["host_network_mutated"] = True
    write_json(bad_safety, safety_report)
    cases.append(("host_network_mutated", {"fault_report": bad_safety}, "sandbox-only network fault"))
    results: list[dict[str, Any]] = []
    for name, overrides, expected in cases:
        candidate = dict(paths)
        candidate.update(overrides)
        observed = validate_cml04_network_faults(stage_id, candidate)
        results.append({"name": name, "status": "PASS" if any(expected in e for e in observed) else "FAIL", "expected_error_fragment": expected, "observed_errors": observed})
    return results


def validate_cml05_failover(stage_id: str, paths: dict[str, Path] | None = None) -> list[str]:
    paths = paths or cml05_paths(stage_id)
    errors: list[str] = []
    observation_paths = {**cml01_paths(stage_id), **{k: v for k, v in paths.items() if k in cml01_paths(stage_id)}}
    errors.extend(validate_observation_model(stage_id, observation_paths))
    if errors:
        return errors
    evidence = load_json(paths["evidence"])
    if int(evidence.get("nodes_observed_before", 0)) != 30 or int(evidence.get("nodes_observed_after_clear", 0)) != 30:
        errors.append("CML05 must observe 30 nodes before fault and after clear")
    if evidence.get("data_path_result") != "PASS":
        errors.append("CML05 data path must PASS")
    latency = evidence.get("failover_latency_ms")
    if not isinstance(latency, (int, float)) or latency <= 0:
        errors.append("CML05 failover_latency_ms must be positive numeric")
    failover = load_json(paths["failover_report"])
    summary = failover.get("summary", {})
    if summary.get("promotion_observed") is not True:
        errors.append("CML05 promotion_observed must be true")
    cleanup = load_json(paths["cleanup"])
    if cleanup.get("status") != "PASS" or cleanup.get("resources_remaining") not in ([], None):
        errors.append("CML05 cleanup must PASS with no resources_remaining")
    workload = load_json(paths["workload_report"])
    names = {window.get("name") for window in workload.get("windows", [])}
    for required in {"before_fault", "during_fault", "after_recovery"}:
        if required not in names:
            errors.append(f"CML05 workload missing {required}")
    return errors


def make_cml05_negative_cases(stage_id: str) -> list[dict[str, Any]]:
    paths = cml05_paths(stage_id)
    validation_dir = ARTIFACT_ROOT / stage_id / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    cases: list[tuple[str, dict[str, Path], str]] = []
    bad_latency = validation_dir / "negative_missing_latency.json"
    evidence = load_json(paths["evidence"])
    evidence["failover_latency_ms"] = "MISSING"
    write_json(bad_latency, evidence)
    cases.append(("missing_latency", {"evidence": bad_latency}, "failover_latency_ms"))
    bad_promotion = validation_dir / "negative_no_promotion.json"
    failover = load_json(paths["failover_report"])
    failover["summary"]["promotion_observed"] = False
    write_json(bad_promotion, failover)
    cases.append(("no_promotion", {"failover_report": bad_promotion}, "promotion_observed"))
    bad_cleanup = validation_dir / "negative_cleanup_residue.json"
    cleanup = load_json(paths["cleanup"])
    cleanup["resources_remaining"] = [{"type": "process", "id": "leaked"}]
    write_json(bad_cleanup, cleanup)
    cases.append(("cleanup_residue", {"cleanup": bad_cleanup}, "cleanup must PASS"))
    results: list[dict[str, Any]] = []
    for name, overrides, expected in cases:
        candidate = dict(paths)
        candidate.update(overrides)
        observed = validate_cml05_failover(stage_id, candidate)
        results.append({"name": name, "status": "PASS" if any(expected in e for e in observed) else "FAIL", "expected_error_fragment": expected, "observed_errors": observed})
    return results


def validate_cml06_split_brain(stage_id: str, paths: dict[str, Path] | None = None) -> list[str]:
    paths = paths or cml06_paths(stage_id)
    errors: list[str] = []
    observation_paths = {**cml01_paths(stage_id), **{k: v for k, v in paths.items() if k in cml01_paths(stage_id)}}
    errors.extend(validate_observation_model(stage_id, observation_paths))
    if errors:
        return errors
    evidence = load_json(paths["evidence"])
    if int(evidence.get("nodes_observed_before", 0)) != 30 or int(evidence.get("nodes_observed_after_clear", 0)) != 30:
        errors.append("CML06 must observe 30 nodes before fault and after clear")
    failover = load_json(paths["failover_report"])
    split = failover.get("summary", {}).get("split_brain_duration_ms", {})
    if not isinstance(split, dict):
        errors.append("CML06 split_brain_duration_ms must be explicit MISSING evidence")
        return errors
    if split.get("status") != "MISSING":
        errors.append("CML06 split_brain_duration_ms must be explicit MISSING evidence")
    if "conflicting_primaries" not in str(split.get("reason", "")):
        errors.append("CML06 split-brain reason must mention conflicting primaries not observed")
    cleanup = load_json(paths["cleanup"])
    if cleanup.get("status") != "PASS" or cleanup.get("resources_remaining") not in ([], None):
        errors.append("CML06 cleanup must PASS with no resources_remaining")
    return errors


def make_cml06_negative_cases(stage_id: str) -> list[dict[str, Any]]:
    paths = cml06_paths(stage_id)
    validation_dir = ARTIFACT_ROOT / stage_id / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    cases: list[tuple[str, dict[str, Path], str]] = []
    zero_split = validation_dir / "negative_zero_filled_split_brain.json"
    failover = load_json(paths["failover_report"])
    failover["summary"]["split_brain_duration_ms"] = 0
    write_json(zero_split, failover)
    cases.append(("zero_filled_split_brain", {"failover_report": zero_split}, "explicit MISSING"))
    no_reason = validation_dir / "negative_missing_conflict_reason.json"
    failover2 = load_json(paths["failover_report"])
    failover2["summary"]["split_brain_duration_ms"]["reason"] = "missing"
    write_json(no_reason, failover2)
    cases.append(("missing_conflicting_primary_reason", {"failover_report": no_reason}, "conflicting primaries"))
    results = []
    for name, overrides, expected in cases:
        candidate = dict(paths)
        candidate.update(overrides)
        observed = validate_cml06_split_brain(stage_id, candidate)
        results.append({"name": name, "status": "PASS" if any(expected in e for e in observed) else "FAIL", "expected_error_fragment": expected, "observed_errors": observed})
    return results


def validate_cml07_workload_windows(stage_id: str, paths: dict[str, Path] | None = None) -> list[str]:
    paths = paths or cml07_paths(stage_id)
    errors: list[str] = []
    observation_paths = {**cml01_paths(stage_id), **{k: v for k, v in paths.items() if k in cml01_paths(stage_id)}}
    errors.extend(validate_observation_model(stage_id, observation_paths))
    if errors:
        return errors
    evidence = load_json(paths["evidence"])
    if int(evidence.get("nodes_observed_before", 0)) != 30 or int(evidence.get("nodes_observed_after_clear", 0)) != 30:
        errors.append("CML07 must observe 30 nodes before fault and after clear")
    if evidence.get("data_path_result") != "PASS":
        errors.append("CML07 data path must PASS")
    failover = load_json(paths["failover_report"])
    if failover.get("summary", {}).get("promotion_observed") is not True:
        errors.append("CML07 promotion_observed must be true")
    workload = load_json(paths["workload_report"])
    if workload.get("status") != "PASS" or int(workload.get("node_count", 0)) != 30:
        errors.append("CML07 workload report must PASS with node_count 30")
    windows = {window.get("name"): window for window in workload.get("windows", [])}
    required_order = ["before_fault", "during_fault", "after_recovery"]
    if [window.get("name") for window in workload.get("windows", [])] != required_order:
        errors.append("CML07 workload windows must be ordered before_fault, during_fault, after_recovery")
    for name in required_order:
        window = windows.get(name)
        if not isinstance(window, dict):
            errors.append(f"CML07 workload missing {name}")
            continue
        if window.get("status") != "MEASURED":
            errors.append(f"CML07 workload {name} must be MEASURED")
        if int(window.get("operation_count", 0)) <= 0 or not window.get("samples"):
            errors.append(f"CML07 workload {name} must include operations and samples")
        availability = window.get("availability_percent")
        if not isinstance(availability, (int, float)):
            errors.append(f"CML07 workload {name} availability_percent must be numeric")
        latency = window.get("latency_ms", {})
        if not all(isinstance(latency.get(key), (int, float)) for key in ["p50", "p95", "p99"]):
            errors.append(f"CML07 workload {name} latency percentiles must be numeric")
    cleanup = load_json(paths["cleanup"])
    if cleanup.get("status") != "PASS" or cleanup.get("resources_remaining") not in ([], None):
        errors.append("CML07 cleanup must PASS with no resources_remaining")
    return errors


def make_cml07_negative_cases(stage_id: str) -> list[dict[str, Any]]:
    paths = cml07_paths(stage_id)
    validation_dir = ARTIFACT_ROOT / stage_id / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    cases: list[tuple[str, dict[str, Path], str]] = []
    missing_window = validation_dir / "negative_missing_during_window.json"
    workload = load_json(paths["workload_report"])
    workload["windows"] = [window for window in workload.get("windows", []) if window.get("name") != "during_fault"]
    write_json(missing_window, workload)
    cases.append(("missing_during_window", {"workload_report": missing_window}, "before_fault, during_fault, after_recovery"))
    empty_samples = validation_dir / "negative_empty_after_samples.json"
    workload2 = load_json(paths["workload_report"])
    for window in workload2.get("windows", []):
        if window.get("name") == "after_recovery":
            window["operation_count"] = 0
            window["samples"] = []
    write_json(empty_samples, workload2)
    cases.append(("empty_after_samples", {"workload_report": empty_samples}, "operations and samples"))
    bad_data_path = validation_dir / "negative_data_path_missing.json"
    evidence = load_json(paths["evidence"])
    evidence["data_path_result"] = "MISSING"
    write_json(bad_data_path, evidence)
    cases.append(("data_path_missing", {"evidence": bad_data_path}, "data_path_result is not PASS"))
    results = []
    for name, overrides, expected in cases:
        candidate = dict(paths)
        candidate.update(overrides)
        observed = validate_cml07_workload_windows(stage_id, candidate)
        results.append({"name": name, "status": "PASS" if any(expected in e for e in observed) else "FAIL", "expected_error_fragment": expected, "observed_errors": observed})
    return results


def validate_cml08_bounded_soak(stage_id: str, paths: dict[str, Path] | None = None) -> list[str]:
    paths = paths or cml08_paths(stage_id)
    errors: list[str] = []
    observation_paths = {**cml01_paths(stage_id), **{k: v for k, v in paths.items() if k in cml01_paths(stage_id)}}
    errors.extend(validate_observation_model(stage_id, observation_paths))
    if errors:
        return errors
    evidence = load_json(paths["evidence"])
    if int(evidence.get("nodes_observed", 0)) != 30:
        errors.append("CML08 evidence nodes_observed must be 30")
    if evidence.get("data_path_result") != "PASS":
        errors.append("CML08 data path must PASS")
    soak = load_json(paths["soak_report"])
    if soak.get("status") != "PASS" or int(soak.get("node_count", 0)) != 30:
        errors.append("CML08 soak report must PASS with node_count 30")
    if float(soak.get("duration_seconds", 0.0)) < 3600.0:
        errors.append("CML08 soak duration_seconds must reach at least 3600")
    checkpoints = {int(item.get("checkpoint_seconds", -1)): item for item in soak.get("checkpoints", [])}
    for checkpoint in (1800, 3600):
        item = checkpoints.get(checkpoint)
        if not isinstance(item, dict) or item.get("status") != "PASS":
            errors.append(f"CML08 checkpoint {checkpoint} must PASS")
        elif float(item.get("observed_elapsed_seconds", 0.0)) < float(checkpoint):
            errors.append(f"CML08 checkpoint {checkpoint} observed elapsed is too short")
    soak_rows = load_jsonl(paths["soak_metrics"])
    if not soak_rows:
        errors.append("CML08 soak metrics must have samples")
    elif max(float(row.get("elapsed_seconds", 0.0)) for row in soak_rows) < 3600.0:
        errors.append("CML08 soak metrics must include a 60-minute sample")
    cleanup = load_json(paths["cleanup"])
    if cleanup.get("status") != "PASS" or cleanup.get("resources_remaining") not in ([], None):
        errors.append("CML08 cleanup must PASS with no resources_remaining")
    return errors


def make_cml08_negative_cases(stage_id: str) -> list[dict[str, Any]]:
    paths = cml08_paths(stage_id)
    validation_dir = ARTIFACT_ROOT / stage_id / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    cases: list[tuple[str, dict[str, Path], str]] = []
    short_duration = validation_dir / "negative_short_duration.json"
    soak = load_json(paths["soak_report"])
    soak["duration_seconds"] = 120.0
    write_json(short_duration, soak)
    cases.append(("short_duration", {"soak_report": short_duration}, "duration_seconds must reach"))
    missing_checkpoint = validation_dir / "negative_missing_60m_checkpoint.json"
    soak2 = load_json(paths["soak_report"])
    soak2["checkpoints"] = [item for item in soak2.get("checkpoints", []) if int(item.get("checkpoint_seconds", -1)) != 3600]
    write_json(missing_checkpoint, soak2)
    cases.append(("missing_60m_checkpoint", {"soak_report": missing_checkpoint}, "checkpoint 3600 must PASS"))
    wrong_nodes = validation_dir / "negative_wrong_node_count.json"
    evidence = load_json(paths["evidence"])
    evidence["nodes_observed"] = 29
    write_json(wrong_nodes, evidence)
    cases.append(("wrong_node_count", {"evidence": wrong_nodes}, "nodes_observed must be 30"))
    results = []
    for name, overrides, expected in cases:
        candidate = dict(paths)
        candidate.update(overrides)
        observed = validate_cml08_bounded_soak(stage_id, candidate)
        results.append({"name": name, "status": "PASS" if any(expected in e for e in observed) else "FAIL", "expected_error_fragment": expected, "observed_errors": observed})
    return results


def validate_cml09_reporting_close(stage_id: str, paths: dict[str, Path] | None = None) -> list[str]:
    paths = paths or cml09_paths(stage_id)
    errors: list[str] = []
    observation_paths = {**cml01_paths(stage_id), **{k: v for k, v in paths.items() if k in cml01_paths(stage_id)}}
    errors.extend(validate_observation_model(stage_id, observation_paths))
    if errors:
        return errors
    evidence = load_json(paths["evidence"])
    if evidence.get("real_valkey") is not True or evidence.get("probe_result") != "PASS":
        errors.append("CML09 aggregate evidence must be real Valkey PASS")
    if int(evidence.get("nodes_observed", 0)) != 30:
        errors.append("CML09 aggregate evidence nodes_observed must be 30")
    index = load_json(paths["evidence_index"])
    required_capabilities = {
        "cluster_management_scale_30",
        "process_nodehost_faults_30",
        "network_az_faults_30",
        "failover_latency_recovery_30",
        "split_brain_indicators_30",
        "workload_fault_windows_30",
        "bounded_soak_30_60_minutes",
    }
    entries = {entry.get("capability_id"): entry for entry in index.get("capabilities", [])}
    missing = required_capabilities - set(entries)
    if missing:
        errors.append(f"CML09 evidence index missing capabilities: {sorted(missing)}")
    for capability_id in sorted(required_capabilities & set(entries)):
        entry = entries[capability_id]
        if entry.get("status") != "PASS":
            errors.append(f"CML09 capability {capability_id} must be PASS")
        if int(entry.get("scale_nodes", 0)) != 30:
            errors.append(f"CML09 capability {capability_id} scale_nodes must be 30")
        for source in entry.get("source_artifacts", []):
            errors.extend(source_checksum_errors([source], f"CML09 capability {capability_id}"))
        evidence_path = ROOT / str(entry.get("real_valkey_evidence", ""))
        if not evidence_path.exists():
            errors.append(f"CML09 capability {capability_id} missing real evidence")
            continue
        real = load_json(evidence_path)
        if real.get("real_valkey") is not True:
            errors.append(f"CML09 capability {capability_id} evidence is not real_valkey")
        observed_values: list[int] = []
        for observed_key in [
            "nodes_observed",
            "nodes_observed_before",
            "nodes_observed_after_clear",
            "node_count",
        ]:
            observed_value = real.get(observed_key)
            if isinstance(observed_value, int):
                observed_values.append(observed_value)
            elif isinstance(observed_value, str) and observed_value.isdigit():
                observed_values.append(int(observed_value))
        if not observed_values or max(observed_values) < 30:
            errors.append(f"CML09 capability {capability_id} evidence must observe at least 30 nodes")
    matrix = load_json(paths["matrix"])
    capability_statuses = {row.get("capability_id"): row.get("status") for row in matrix.get("capabilities", [])}
    if required_capabilities - set(capability_statuses):
        errors.append("CML09 capability matrix must include every required 30-node capability")
    if any(status != "PASS" for status in capability_statuses.values()):
        errors.append("CML09 capability matrix statuses must all be PASS")
    return errors


def make_cml09_negative_cases(stage_id: str) -> list[dict[str, Any]]:
    paths = cml09_paths(stage_id)
    validation_dir = ARTIFACT_ROOT / stage_id / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    cases: list[tuple[str, dict[str, Path], str]] = []
    missing_capability = validation_dir / "negative_missing_capability.json"
    index = load_json(paths["evidence_index"])
    index["capabilities"] = [entry for entry in index.get("capabilities", []) if entry.get("capability_id") != "bounded_soak_30_60_minutes"]
    write_json(missing_capability, index)
    cases.append(("missing_capability", {"evidence_index": missing_capability}, "missing capabilities"))
    fake_evidence = validation_dir / "negative_fake_aggregate_evidence.json"
    evidence = load_json(paths["evidence"])
    evidence["real_valkey"] = False
    write_json(fake_evidence, evidence)
    cases.append(("fake_aggregate_evidence", {"evidence": fake_evidence}, "real_valkey"))
    wrong_nodes = validation_dir / "negative_wrong_node_count.json"
    evidence2 = load_json(paths["evidence"])
    evidence2["nodes_observed"] = 29
    write_json(wrong_nodes, evidence2)
    cases.append(("wrong_node_count", {"evidence": wrong_nodes}, "nodes_observed must be 30"))
    results = []
    for name, overrides, expected in cases:
        candidate = dict(paths)
        candidate.update(overrides)
        observed = validate_cml09_reporting_close(stage_id, candidate)
        results.append({"name": name, "status": "PASS" if any(expected in e for e in observed) else "FAIL", "expected_error_fragment": expected, "observed_errors": observed})
    return results


def build_baseline() -> dict[str, Any]:
    capabilities = [
        {
            "capability": "cluster_management_scale_30",
            "scale_nodes": 30,
            "status": "PARTIAL",
            "real_valkey_required": True,
            "cleanup_required": True,
            "evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json"],
            "cleanup_evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/cleanup_report_scale_30.json"],
            "missing_or_partial": ["remove_node", "add_node", "reshard", "rebalance", "rolling_restart workload windows require CML02 closure"],
            "report_artifacts": [],
        },
        {
            "capability": "fault_failover_scale_30",
            "scale_nodes": 30,
            "status": "PARTIAL",
            "real_valkey_required": True,
            "cleanup_required": True,
            "evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_fault_30.json"],
            "cleanup_evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/cleanup_report_fault_30.json"],
            "missing_or_partial": ["network partition", "nodehost kill/restart", "split-brain ABSENT_OBSERVED proof", "full before/during/after workload windows"],
            "report_artifacts": [],
        },
        {
            "capability": "scale_ladder_50_100",
            "scale_nodes": 100,
            "status": "PARTIAL",
            "real_valkey_required": True,
            "cleanup_required": True,
            "evidence_paths": ["artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json"],
            "cleanup_evidence_paths": ["artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report_scale_100.json"],
            "missing_or_partial": ["capability suite replay for management/fault/failover/split-brain/workload/soak across 50 and 100"],
            "report_artifacts": [],
        },
        {
            "capability": "bounded_soak_30_60_minutes",
            "scale_nodes": 30,
            "status": "MISSING",
            "real_valkey_required": True,
            "cleanup_required": True,
            "evidence_paths": [],
            "cleanup_evidence_paths": [],
            "missing_or_partial": ["30-minute soak", "60-minute soak"],
            "report_artifacts": [],
        },
    ]
    return {
        "schema_version": "v1",
        "artifact_type": "capability_matrix_baseline",
        "stage_id": "CML00_CAPABILITY_LOOP_BOOTSTRAP",
        "status": "PASS",
        "created_at": utc_now(),
        "capabilities": capabilities,
    }


def command_next(_: argparse.Namespace) -> int:
    state = load_state()
    completed = set(state.get("completed_stages", []))
    for stage in load_manifest().get("stages", []):
        if stage.get("automatic", True) and stage["id"] not in completed:
            print(stage["id"])
            return 0
    print("COMPLETE")
    return 0


def command_build_baseline(args: argparse.Namespace) -> int:
    out = Path(args.out) if args.out else ARTIFACT_ROOT / args.stage / "reports" / "capability_matrix_baseline.json"
    write_json(out, build_baseline())
    errors = schema_errors(out, "schemas/capability_matrix_loop/capability_matrix_baseline.schema.json")
    errors.extend(validate_baseline(out))
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(rel(out))
    return 0


def command_run(args: argparse.Namespace) -> int:
    stage = stage_by_id(args.stage)
    checks: list[dict[str, Any]] = []

    def add_check(name: str, errors: list[str]) -> None:
        checks.append({"name": name, "status": "PASS" if not errors else "FAIL", "errors": errors})

    add_check("manifest", check_manifest())
    add_check("state", check_state())
    add_check("harness_lock", check_lock())
    add_check("required_artifacts", validate_required_artifacts(stage))

    if args.stage == "CML01_UNIFIED_OBSERVATION_AND_ARTIFACT_MODEL":
        observation_errors = validate_observation_model(args.stage)
        add_check("observation_model", observation_errors)
        negative_cases = make_cml01_negative_cases(args.stage) if not observation_errors else []
        add_check("negative_cases", [case["name"] for case in negative_cases if case["status"] != "PASS"])
    elif args.stage == "CML02_CLUSTER_MANAGEMENT_REAL_OPS_30":
        management_errors = validate_cml02_management_ops(args.stage)
        add_check("management_ops_30", management_errors)
        negative_cases = make_cml02_negative_cases(args.stage) if not management_errors else []
        add_check("negative_cases", [case["name"] for case in negative_cases if case["status"] != "PASS"])
    elif args.stage == "CML03_PROCESS_AND_NODEHOST_FAULTS_30":
        fault_errors = validate_cml03_faults(args.stage)
        add_check("process_nodehost_faults_30", fault_errors)
        negative_cases = make_cml03_negative_cases(args.stage) if not fault_errors else []
        add_check("negative_cases", [case["name"] for case in negative_cases if case["status"] != "PASS"])
    elif args.stage == "CML04_NETWORK_PARTITION_AND_AZ_FAULTS_30":
        network_errors = validate_cml04_network_faults(args.stage)
        add_check("network_az_faults_30", network_errors)
        negative_cases = make_cml04_negative_cases(args.stage) if not network_errors else []
        add_check("negative_cases", [case["name"] for case in negative_cases if case["status"] != "PASS"])
    elif args.stage == "CML05_FAILOVER_LATENCY_AND_RECOVERY_30":
        failover_errors = validate_cml05_failover(args.stage)
        add_check("failover_latency_recovery_30", failover_errors)
        negative_cases = make_cml05_negative_cases(args.stage) if not failover_errors else []
        add_check("negative_cases", [case["name"] for case in negative_cases if case["status"] != "PASS"])
    elif args.stage == "CML06_SPLIT_BRAIN_INDICATORS_30":
        split_errors = validate_cml06_split_brain(args.stage)
        add_check("split_brain_indicators_30", split_errors)
        negative_cases = make_cml06_negative_cases(args.stage) if not split_errors else []
        add_check("negative_cases", [case["name"] for case in negative_cases if case["status"] != "PASS"])
    elif args.stage == "CML07_WORKLOAD_FAULT_WINDOWS_30":
        workload_errors = validate_cml07_workload_windows(args.stage)
        add_check("workload_fault_windows_30", workload_errors)
        negative_cases = make_cml07_negative_cases(args.stage) if not workload_errors else []
        add_check("negative_cases", [case["name"] for case in negative_cases if case["status"] != "PASS"])
    elif args.stage == "CML08_BOUNDED_SOAK_30_60_MINUTES":
        soak_errors = validate_cml08_bounded_soak(args.stage)
        add_check("bounded_soak_30_60_minutes", soak_errors)
        negative_cases = make_cml08_negative_cases(args.stage) if not soak_errors else []
        add_check("negative_cases", [case["name"] for case in negative_cases if case["status"] != "PASS"])
    elif args.stage == "CML09_REPORTING_AND_CAPABILITY_MATRIX_CLOSE_30":
        reporting_errors = validate_cml09_reporting_close(args.stage)
        add_check("reporting_capability_matrix_close_30", reporting_errors)
        negative_cases = make_cml09_negative_cases(args.stage) if not reporting_errors else []
        add_check("negative_cases", [case["name"] for case in negative_cases if case["status"] != "PASS"])
    else:
        baseline_path = ROOT / "artifacts" / "capability_matrix_loop" / args.stage / "reports" / "capability_matrix_baseline.json"
        baseline_errors = schema_errors(baseline_path, "schemas/capability_matrix_loop/capability_matrix_baseline.schema.json") if baseline_path.exists() else [f"baseline missing: {rel(baseline_path)}"]
        baseline_errors.extend(validate_baseline(baseline_path) if baseline_path.exists() else [])
        add_check("capability_matrix_baseline", baseline_errors)
        negative_cases = make_negative_cases()
        add_check("negative_cases", [case["name"] for case in negative_cases if case["status"] != "PASS"])
    status = "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL"
    result = {
        "schema_version": "v1",
        "artifact_type": "capability_stage_gate_result",
        "stage_id": args.stage,
        "status": status,
        "created_at": utc_now(),
        "checks": checks,
        "negative_cases": negative_cases,
    }
    out = ARTIFACT_ROOT / args.stage / "validation" / "current_stage_gate_result.json"
    write_json(out, result)
    schema_result_errors = schema_errors(out, "schemas/capability_matrix_loop/capability_stage_gate_result.schema.json")
    if schema_result_errors:
        for error in schema_result_errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": status, "path": rel(out)}, sort_keys=True))
    return 0 if status == "PASS" else 1


def command_previous_harness(args: argparse.Namespace) -> int:
    commands = [
        ["python3", "scripts/codex_gate.py", "precheck", "--all"],
        ["python3", "scripts/safety_scan.py"],
        ["python3", "-m", "compileall", "-q", "scripts", "src", "tests"],
    ]
    out = ARTIFACT_ROOT / args.stage / "validation" / "previous_harness.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}" + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    def remove_python_caches() -> None:
        for cache_dir in ROOT.rglob("__pycache__"):
            if ".git" not in cache_dir.parts:
                shutil.rmtree(cache_dir, ignore_errors=True)
        pytest_cache = ROOT / ".pytest_cache"
        if pytest_cache.exists():
            shutil.rmtree(pytest_cache, ignore_errors=True)

    with out.open("w", encoding="utf-8") as log:
        for command in commands:
            log.write(f"$ {' '.join(command)}\n")
            proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
            log.write(proc.stdout)
            log.write(f"\nexit_code={proc.returncode}\n\n")
            if proc.returncode != 0:
                print(rel(out))
                return proc.returncode
            if command[:3] == ["python3", "-m", "compileall"]:
                remove_python_caches()
        state = load_json(ROOT / "codex" / "status" / "phase_state.json")
        failed: list[str] = []
        for phase in state.get("completed_phases", []):
            command = ["python3", "scripts/codex_gate.py", "postcheck", "--phase", phase]
            log.write(f"$ {' '.join(command)}\n")
            proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
            log.write(proc.stdout)
            log.write(f"\nexit_code={proc.returncode}\n\n")
            if proc.returncode != 0:
                failed.append(phase)
        if failed:
            log.write(f"FAILED_PREVIOUS_POSTCHECKS {failed}\n")
            print(rel(out))
            return 1
        command = ["pytest", "-q"]
        log.write(f"$ {' '.join(command)}\n")
        proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        log.write(proc.stdout)
        log.write(f"\nexit_code={proc.returncode}\n\n")
        if proc.returncode != 0:
            print(rel(out))
            return proc.returncode
    print(rel(out))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Capability matrix loop gate")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("next").set_defaults(func=command_next)
    prev = sub.add_parser("previous-harness")
    prev.add_argument("--stage", required=True)
    prev.set_defaults(func=command_previous_harness)
    baseline = sub.add_parser("build-baseline")
    baseline.add_argument("--stage", required=True)
    baseline.add_argument("--out")
    baseline.set_defaults(func=command_build_baseline)
    run = sub.add_parser("run")
    run.add_argument("--stage", required=True)
    run.set_defaults(func=command_run)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
