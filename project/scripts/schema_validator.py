#!/usr/bin/env python3
"""Small JSON Schema subset validator used by the local Valkey harness.

This avoids making the bootstrap gate depend on external packages. It supports the
subset used by schemas/ in this repository: type, required, properties,
additionalProperties, enum, const, pattern, minimum, maximum, minLength,
maxLength, minItems, maxItems, items, allOf.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


class SchemaValidationError(Exception):
    pass


def _is_type(value: Any, typ: str) -> bool:
    if typ == "object":
        return isinstance(value, dict)
    if typ == "array":
        return isinstance(value, list)
    if typ == "string":
        return isinstance(value, str)
    if typ == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if typ == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if typ == "boolean":
        return isinstance(value, bool)
    if typ == "null":
        return value is None
    return True


def validate(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []

    if "allOf" in schema:
        for idx, subschema in enumerate(schema["allOf"]):
            errors.extend(validate(instance, subschema, f"{path}.allOf[{idx}]"))

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']!r}, got {instance!r}")

    if "type" in schema:
        typ = schema["type"]
        if isinstance(typ, list):
            if not any(_is_type(instance, t) for t in typ):
                errors.append(f"{path}: expected type one of {typ!r}, got {type(instance).__name__}")
                return errors
        elif not _is_type(instance, typ):
            errors.append(f"{path}: expected type {typ!r}, got {type(instance).__name__}")
            return errors

    if isinstance(instance, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                errors.append(f"{path}: missing required key {key!r}")

        props = schema.get("properties", {})
        for key, subschema in props.items():
            if key in instance:
                errors.extend(validate(instance[key], subschema, f"{path}.{key}"))

        if schema.get("additionalProperties") is False:
            extra = sorted(set(instance) - set(props))
            for key in extra:
                errors.append(f"{path}: additional property not allowed: {key!r}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < int(schema["minItems"]):
            errors.append(f"{path}: expected at least {schema['minItems']} items, got {len(instance)}")
        if "maxItems" in schema and len(instance) > int(schema["maxItems"]):
            errors.append(f"{path}: expected at most {schema['maxItems']} items, got {len(instance)}")
        if schema.get("uniqueItems"):
            seen = set()
            for item in instance:
                marker = json.dumps(item, sort_keys=True, default=str)
                if marker in seen:
                    errors.append(f"{path}: duplicate array item {item!r}")
                    break
                seen.add(marker)
        if "items" in schema:
            for idx, item in enumerate(instance):
                errors.extend(validate(item, schema["items"], f"{path}[{idx}]"))

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < int(schema["minLength"]):
            errors.append(f"{path}: string shorter than {schema['minLength']}")
        if "maxLength" in schema and len(instance) > int(schema["maxLength"]):
            errors.append(f"{path}: string longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(f"{path}: string {instance!r} does not match pattern {schema['pattern']!r}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: number {instance!r} below minimum {schema['minimum']!r}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: number {instance!r} above maximum {schema['maximum']!r}")

    return errors


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_file(instance_path: str | Path, schema_path: str | Path) -> list[str]:
    return validate(load_json(instance_path), load_json(schema_path))
