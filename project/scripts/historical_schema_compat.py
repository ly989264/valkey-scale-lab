"""Fail-closed validation for immutable artifacts against versioned schemas."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from schema_validator import load_json, validate

REGISTRY_PATH = "codex/historical_schema_compat_registry.json"


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str]
    schema: dict[str, Any]
    schema_path: str
    compatibility_used: bool
    compatibility_reason: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def logical_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.resolve().relative_to(root.resolve()).as_posix()


def _validate_records(path: Path, schema: dict[str, Any]) -> list[str]:
    if path.suffix == ".jsonl":
        errors: list[str] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                errors.extend(validate(json.loads(line), schema, f"$[line {line_number}]"))
            except json.JSONDecodeError as exc:
                errors.append(f"$[line {line_number}]: invalid JSON: {exc}")
        return errors
    return validate(json.loads(path.read_text(encoding="utf-8")), schema)


def _load_registry(root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    path = root / REGISTRY_PATH
    errors: list[str] = []
    try:
        data = load_json(path)
    except Exception as exc:
        return {}, [f"historical compatibility registry unreadable: {exc}"]
    if data.get("schema_version") != "v1" or data.get("artifact_type") != "historical_schema_compat_registry":
        errors.append("historical compatibility registry header invalid")
    entries: dict[str, dict[str, Any]] = {}
    required = {
        "phase_id", "artifact_path", "artifact_sha256", "current_schema_path",
        "historical_schema_path", "historical_schema_sha256", "gate_manifest_sha256",
    }
    for index, entry in enumerate(data.get("entries", [])):
        if not isinstance(entry, dict) or set(entry) != required:
            errors.append(f"historical compatibility registry entry {index} has invalid fields")
            continue
        artifact_path = entry["artifact_path"]
        if artifact_path in entries:
            errors.append(f"duplicate historical compatibility artifact: {artifact_path}")
        entries[artifact_path] = entry
    return entries, errors


def validate_artifact(root: Path, path: Path, current_schema_path: Path) -> ValidationResult:
    current_schema = load_json(current_schema_path)
    current_errors = _validate_records(path, current_schema)
    current_logical = logical_path(root, current_schema_path)
    if not current_errors:
        return ValidationResult([], current_schema, current_logical, False, "current schema passed")

    entries, registry_errors = _load_registry(root)
    artifact_logical = logical_path(root, path)
    entry = entries.get(artifact_logical)
    if registry_errors or entry is None:
        reason = "; ".join(registry_errors) if registry_errors else "artifact has no exact historical binding"
        return ValidationResult(current_errors, current_schema, current_logical, False, reason)
    if entry["current_schema_path"] != current_logical:
        return ValidationResult(current_errors, current_schema, current_logical, False, "current schema path binding mismatch")
    if sha256_file(path) != entry["artifact_sha256"]:
        return ValidationResult(current_errors, current_schema, current_logical, False, "artifact SHA-256 binding mismatch")
    historical_path = root / entry["historical_schema_path"]
    if not historical_path.is_file() or sha256_file(historical_path) != entry["historical_schema_sha256"]:
        return ValidationResult(current_errors, current_schema, current_logical, False, "historical schema SHA-256 binding mismatch")
    gate_result_path = root / "artifacts" / "gates" / entry["phase_id"] / "gate_result.json"
    try:
        gate_manifest_sha = load_json(gate_result_path)["manifest_sha256"]
    except Exception as exc:
        return ValidationResult(current_errors, current_schema, current_logical, False, f"gate manifest binding unreadable: {exc}")
    if gate_manifest_sha != entry["gate_manifest_sha256"]:
        return ValidationResult(current_errors, current_schema, current_logical, False, "gate manifest SHA-256 binding mismatch")
    historical_schema = load_json(historical_path)
    historical_errors = _validate_records(path, historical_schema)
    if historical_errors:
        return ValidationResult(current_errors, current_schema, current_logical, False, "historical schema validation failed")
    return ValidationResult(
        [], historical_schema, entry["historical_schema_path"], True,
        "current schema failed; exact artifact, historical schema, and gate manifest bindings passed",
    )


def allowed_manifest_extension(root: Path, target: str, expected_sha: str, actual_sha: str) -> bool:
    try:
        registry = load_json(root / REGISTRY_PATH)
    except Exception:
        return False
    for entry in registry.get("allowed_manifest_extensions", []):
        if (
            entry.get("path") == "codex/phase_manifest.json"
            and entry.get("extension_phase") == "P46_REPOSITORY_LAYOUT_MIGRATION"
            and entry.get("expected_historical_sha256") == expected_sha
            and entry.get("current_sha256") == actual_sha
            and target in entry.get("targets", [])
            and sha256_file(root / "codex/phase_manifest.json") == actual_sha
        ):
            return True
    return False


def allowed_phase_state_extension(root: Path, target: str, expected_sha: str, actual_sha: str) -> bool:
    """Accept only the exact P46 mark-complete extension of the P40 state snapshot."""
    try:
        registry = load_json(root / REGISTRY_PATH)
    except Exception:
        return False
    for entry in registry.get("allowed_phase_state_extensions", []):
        if (
            entry.get("path") == "codex/status/phase_state.json"
            and entry.get("extension_phase") == "P46_REPOSITORY_LAYOUT_MIGRATION"
            and entry.get("expected_historical_sha256") == expected_sha
            and entry.get("current_sha256") == actual_sha
            and target in entry.get("targets", [])
            and sha256_file(root / "codex/status/phase_state.json") == actual_sha
        ):
            return True
    return False


def allowed_historical_report_commit(root: Path, declared_commit: str, html: str) -> bool:
    """Accept only the locked, immutable pre-P46 report/provenance pair."""
    try:
        registry = load_json(root / REGISTRY_PATH)
    except Exception:
        return False
    for entry in registry.get("allowed_historical_report_commit_bindings", []):
        provenance_path = root / entry.get("provenance_graph_path", "")
        html_path = root / entry.get("html_path", "")
        if (
            entry.get("declared_root_commit_sha") == declared_commit
            and provenance_path.is_file()
            and html_path.is_file()
            and sha256_file(provenance_path) == entry.get("provenance_graph_sha256")
            and sha256_file(html_path) == entry.get("html_sha256")
            and html == html_path.read_text(encoding="utf-8")
            and all(commit in html for commit in entry.get("embedded_commit_sha256es", []))
        ):
            return True
    return False
