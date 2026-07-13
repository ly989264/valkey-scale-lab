from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from .contracts import ContractError, load_bundle


VALIDATION_SCHEMA = "vpro-milestone-validation-v1"
TEMPLATE_RELATIVE_PATH = Path("templates/vpro/milestone_bundle.template.json")


def load_milestone_template(framework_root: Path) -> dict[str, Any]:
    path = Path(framework_root) / TEMPLATE_RELATIVE_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load the sealed milestone template: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("the sealed milestone template must be a JSON object")
    return value


def validate_milestone(
    bundle_path: Path,
    *,
    project_root: Path,
    schema_path: Path,
) -> dict[str, Any]:
    bundle_path = Path(bundle_path).absolute()
    report: dict[str, Any] = {
        "schema_version": VALIDATION_SCHEMA,
        "status": "FAIL",
        "bundle_path": str(bundle_path),
        "missing_fields": [],
        "errors": [],
        "template_command": "vpro milestone-template",
    }
    try:
        raw = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report["errors"] = [f"cannot load milestone bundle: {exc}"]
        return report
    try:
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load the sealed milestone schema: {exc}") from exc
    if not isinstance(schema, dict):
        raise ContractError("the sealed milestone schema must be a JSON object")
    report["missing_fields"] = missing_required_fields(raw, schema)
    try:
        bundle = load_bundle(bundle_path, project_root=project_root)
    except ContractError as exc:
        report["errors"] = [str(exc)]
        return report
    report.update(
        {
            "status": "PASS",
            "milestone_id": bundle.milestone.id,
            "bundle_version": bundle.milestone.version,
            "profile_ids": [profile.id for profile in bundle.profiles],
            "execution_readiness": execution_readiness(bundle, Path(project_root)),
        }
    )
    return report


def execution_readiness(bundle: Any, project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    authority_roots = (
        *bundle.integrity.authoritative_check_paths,
        *bundle.integrity.evaluator_paths,
    )
    authority_inputs = {
        path
        for check in bundle.checks
        for path in check.inputs
        if any(_path_covered(path, authority) for authority in authority_roots)
    }
    required_paths = {*authority_roots, *authority_inputs}
    missing_paths = sorted(
        path
        for path in required_paths
        if not (root / path).exists()
    )
    missing_tools = sorted(
        tool for tool in bundle.integrity.allowed_tools if shutil.which(tool) is None
    )
    return {
        "status": "READY" if not missing_paths and not missing_tools else "BLOCKED",
        "scope": "STATIC_AUTHORITY_PATHS_AND_DECLARED_TOOLS",
        "missing_authority_paths": missing_paths,
        "missing_tools": missing_tools,
        "dynamic_preflight_required": any(check.capabilities for check in bundle.checks),
    }


def missing_required_fields(value: Any, schema: Mapping[str, Any]) -> list[str]:
    return sorted(set(_missing(value, schema, schema, "$")))


def _missing(
    value: Any,
    fragment: Mapping[str, Any],
    root: Mapping[str, Any],
    location: str,
) -> list[str]:
    resolved = _resolve(fragment, root)
    missing: list[str] = []
    if isinstance(value, dict):
        required = resolved.get("required", [])
        if isinstance(required, list):
            missing.extend(
                f"{location}.{key}"
                for key in required
                if isinstance(key, str) and key not in value
            )
        properties = resolved.get("properties", {})
        if isinstance(properties, dict):
            for key, child in properties.items():
                if key in value and isinstance(child, dict):
                    missing.extend(_missing(value[key], child, root, f"{location}.{key}"))
    elif isinstance(value, list):
        items = resolved.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                missing.extend(_missing(item, items, root, f"{location}[{index}]"))
    all_of = resolved.get("allOf", [])
    if isinstance(all_of, list):
        for child in all_of:
            if not isinstance(child, dict):
                continue
            condition = child.get("if")
            selected = child.get("then") if isinstance(condition, dict) and _matches(value, condition) else None
            if isinstance(selected, dict):
                missing.extend(_missing(value, selected, root, location))
            elif condition is None:
                missing.extend(_missing(value, child, root, location))
    return missing


def _resolve(fragment: Mapping[str, Any], root: Mapping[str, Any]) -> Mapping[str, Any]:
    reference = fragment.get("$ref")
    if not isinstance(reference, str):
        return fragment
    if not reference.startswith("#/"):
        raise ContractError(f"milestone schema uses an unsupported reference: {reference}")
    current: Any = root
    for part in reference[2:].split("/"):
        if not isinstance(current, dict) or part not in current:
            raise ContractError(f"milestone schema reference is unresolved: {reference}")
        current = current[part]
    if not isinstance(current, dict):
        raise ContractError(f"milestone schema reference is not an object: {reference}")
    return current


def _matches(value: Any, condition: Mapping[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    properties = condition.get("properties")
    if not isinstance(properties, dict):
        return False
    for key, expected in properties.items():
        if key not in value or not isinstance(expected, dict):
            return False
        if "const" in expected and value[key] != expected["const"]:
            return False
        if "enum" in expected and value[key] not in expected["enum"]:
            return False
    return True


def _path_covered(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")
