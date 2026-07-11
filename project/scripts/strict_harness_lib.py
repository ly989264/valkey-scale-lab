#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]

STRICT_STAGES: list[dict[str, Any]] = [
    {"id": "P27_STRICT_MATRIX_REBASE_HARNESS", "real": False, "max_nodes": 0, "category": "harness"},
    {"id": "P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER", "real": False, "max_nodes": 0, "category": "coverage"},
    {"id": "P29_QUANT_TELEMETRY_COLLECTOR_HARDENING", "real": True, "max_nodes": 6, "category": "telemetry"},
    {"id": "P30_MANAGEMENT_MATRIX_50_REAL", "real": True, "max_nodes": 50, "category": "management"},
    {"id": "P31_MANAGEMENT_MATRIX_100_REAL", "real": True, "max_nodes": 100, "category": "management"},
    {"id": "P32_MANAGEMENT_MATRIX_200_REAL", "real": True, "max_nodes": 200, "category": "management"},
    {"id": "P33_FAULT_FAILOVER_MATRIX_50_REAL", "real": True, "max_nodes": 50, "category": "fault"},
    {"id": "P34_FAULT_FAILOVER_MATRIX_100_REAL", "real": True, "max_nodes": 100, "category": "fault"},
    {"id": "P35_FAULT_FAILOVER_MATRIX_200_REAL", "real": True, "max_nodes": 200, "category": "fault"},
    {"id": "P36_FULL_FLOW_E2E_50_100_200_REAL", "real": True, "max_nodes": 200, "category": "full_flow"},
    {"id": "P37_200_PLUS_DRY_RUN_SUPPORT", "real": False, "max_nodes": 0, "category": "dry_run"},
    {"id": "P38_CROSS_SCALE_ANALYSIS_REGRESSION", "real": False, "max_nodes": 0, "category": "analysis"},
    {"id": "P39_VISUAL_REPORT_QUALITY_GATE", "real": False, "max_nodes": 0, "category": "report"},
    {"id": "P40_STRICT_FINAL_AUDIT_CLOSEOUT", "real": False, "max_nodes": 0, "category": "audit"},
]

STRICT_STAGE_IDS = [stage["id"] for stage in STRICT_STAGES]
STRICT_COMMON_GATE_NAMES = {
    "harness_precheck",
    "safety_static_scan",
    "scripts_compile",
    "unit_integration_tests",
    "strict_stage_contract",
    "anti_bypass",
}
STRICT_200_EXCEPTIONS = {
    "P32_MANAGEMENT_MATRIX_200_REAL",
    "P35_FAULT_FAILOVER_MATRIX_200_REAL",
    "P36_FULL_FLOW_E2E_50_100_200_REAL",
}
STRICT_NON_RUNTIME_STAGES = {
    "P27_STRICT_MATRIX_REBASE_HARNESS",
    "P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER",
    "P37_200_PLUS_DRY_RUN_SUPPORT",
    "P38_CROSS_SCALE_ANALYSIS_REGRESSION",
    "P39_VISUAL_REPORT_QUALITY_GATE",
    "P40_STRICT_FINAL_AUDIT_CLOSEOUT",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: Path) -> list[Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"empty JSONL artifact: {path}")
    rows: list[Any] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
    if not rows:
        raise ValueError(f"empty JSONL artifact: {path}")
    return rows


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        try:
            return path.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            return path.as_posix()


def phase_dir(phase: str) -> Path:
    return ROOT / "artifacts" / "phases" / phase


def manifest_path() -> Path:
    return ROOT / "codex" / "phase_manifest.json"


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    return load_json(path or manifest_path())


def phase_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {phase["id"]: phase for phase in manifest.get("phases", []) if isinstance(phase.get("id"), str)}


def strict_stage_doc(stage_id: str) -> Path:
    return ROOT / "docs" / "codex" / "goal-loop-strict" / "stages" / f"{stage_id}.md"


def strict_handoff_dir(stage_id: str) -> Path:
    return ROOT / "artifacts" / "goal_loop_strict" / stage_id


def add_missing_data_errors(obj: Any, errors: list[str], path: str = "$") -> None:
    if obj is None:
        errors.append(f"{path}: null is not an allowed missing-data encoding")
        return
    if isinstance(obj, dict):
        status = obj.get("status")
        if status in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"} and not obj.get("reason"):
            errors.append(f"{path}: {status} requires a non-empty reason")
        for key, value in obj.items():
            add_missing_data_errors(value, errors, f"{path}.{key}")
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            add_missing_data_errors(value, errors, f"{path}[{idx}]")


def require_file(path: Path, errors: list[str], label: str | None = None) -> bool:
    if not path.exists():
        errors.append(f"{label or 'file'} missing: {rel(path)}")
        return False
    if path.is_file() and path.suffix == ".jsonl":
        try:
            load_jsonl(path)
        except Exception as exc:
            errors.append(f"{rel(path)}: {exc}")
            return False
    return True


def require_json(path: Path, errors: list[str], label: str | None = None) -> dict[str, Any] | None:
    if not require_file(path, errors, label):
        return None
    try:
        obj = load_json(path)
    except Exception as exc:
        errors.append(f"{rel(path)}: invalid JSON: {exc}")
        return None
    if not isinstance(obj, dict):
        errors.append(f"{rel(path)}: expected JSON object")
        return None
    add_missing_data_errors(obj, errors)
    return obj


def print_errors(errors: Iterable[str]) -> int:
    items = list(errors)
    if not items:
        return 0
    for error in items:
        print(f"FAIL: {error}", file=sys.stderr)
    return 1


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def add_phase_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--phase", required=True)
