from __future__ import annotations

import json
import re
from typing import Any, Mapping


def validate(instance: Any, schema: Mapping[str, Any]) -> list[str]:
    return _validate(instance, schema, schema, "$")


def _resolve(root: Mapping[str, Any], reference: str) -> Mapping[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported schema reference: {reference}")
    value: Any = root
    for raw in reference[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, Mapping) or key not in value:
            raise ValueError(f"unresolved schema reference: {reference}")
        value = value[key]
    if not isinstance(value, Mapping):
        raise ValueError(f"schema reference is not an object: {reference}")
    return value


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _validate(
    instance: Any,
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str,
) -> list[str]:
    if "$ref" in schema:
        return _validate(instance, _resolve(root, str(schema["$ref"])), root, path)
    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _matches_type(instance, expected_type):
        return [f"{path}: expected {expected_type}"]
    if isinstance(expected_type, list) and not any(
        isinstance(item, str) and _matches_type(instance, item) for item in expected_type
    ):
        return [f"{path}: expected one of {expected_type}"]
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value is not in the declared enum")
    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if key not in instance:
                    errors.append(f"{path}: missing required key {key!r}")
        if isinstance(properties, Mapping):
            for key, subschema in properties.items():
                if key in instance and isinstance(subschema, Mapping):
                    errors.extend(_validate(instance[key], subschema, root, f"{path}.{key}"))
            if schema.get("additionalProperties") is False:
                for key in sorted(set(instance) - set(properties)):
                    errors.append(f"{path}: additional property {key!r} is forbidden")
    if isinstance(instance, list):
        if isinstance(schema.get("minItems"), int) and len(instance) < schema["minItems"]:
            errors.append(f"{path}: too few items")
        if schema.get("uniqueItems") is True:
            markers = [json.dumps(item, sort_keys=True) for item in instance]
            if len(markers) != len(set(markers)):
                errors.append(f"{path}: duplicate items are forbidden")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(instance):
                errors.extend(_validate(item, item_schema, root, f"{path}[{index}]"))
    if isinstance(instance, str):
        if isinstance(schema.get("minLength"), int) and len(instance) < schema["minLength"]:
            errors.append(f"{path}: string is too short")
        if isinstance(schema.get("pattern"), str) and re.fullmatch(schema["pattern"], instance) is None:
            errors.append(f"{path}: string does not match the declared pattern")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: number is below the minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: number is above the maximum")
    return errors
