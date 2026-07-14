from __future__ import annotations

import re
from typing import Any, Mapping


class SchemaValidationError(ValueError):
    pass


SUPPORTED = {
    "$schema",
    "$id",
    "$ref",
    "$defs",
    "title",
    "description",
    "type",
    "const",
    "enum",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "pattern",
    "oneOf",
    "allOf",
}


def validate_json_schema(value: Any, schema: Mapping[str, Any]) -> None:
    if not isinstance(schema, dict):
        raise SchemaValidationError("declared evaluator output schema must be an object")
    try:
        _validate_schema_structure(schema, schema, "$", ())
        _validate(value, schema, schema, "$")
    except SchemaValidationError:
        raise
    except (RecursionError, TypeError, ValueError) as exc:
        raise SchemaValidationError(f"malformed evaluator output schema: {exc}") from exc


def _validate_schema_structure(
    fragment: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str,
    reference_stack: tuple[str, ...],
) -> None:
    if not isinstance(fragment, dict):
        raise SchemaValidationError(f"{path} schema must be an object")
    unknown = set(fragment) - SUPPORTED
    if unknown:
        raise SchemaValidationError(f"unsupported output-schema keywords at {path}: {sorted(unknown)}")
    for keyword in ("$schema", "$id", "title", "description"):
        if keyword in fragment and not isinstance(fragment[keyword], str):
            raise SchemaValidationError(f"{path} {keyword} must be text")
    if "type" in fragment:
        names = fragment["type"]
        names = [names] if isinstance(names, str) else names
        allowed = {"object", "array", "string", "integer", "number", "boolean", "null"}
        if not isinstance(names, list) or not names or not all(isinstance(item, str) for item in names):
            raise SchemaValidationError(f"{path} type must be text or a nonempty text array")
        if set(names) - allowed:
            raise SchemaValidationError(f"{path} has unsupported schema types")
    if "enum" in fragment and not isinstance(fragment["enum"], list):
        raise SchemaValidationError(f"{path} enum must be an array")
    required = fragment.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise SchemaValidationError(f"{path} required must be a string array")
    for keyword in ("minItems", "maxItems", "minLength", "maxLength"):
        bound = fragment.get(keyword)
        if bound is not None and (
            not isinstance(bound, int) or isinstance(bound, bool) or bound < 0
        ):
            raise SchemaValidationError(f"{path} {keyword} must be a nonnegative integer")
    for keyword in ("minimum", "maximum"):
        bound = fragment.get(keyword)
        if bound is not None and (
            not isinstance(bound, (int, float)) or isinstance(bound, bool)
        ):
            raise SchemaValidationError(f"{path} {keyword} must be numeric")
    pattern = fragment.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            raise SchemaValidationError(f"{path} pattern must be text")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise SchemaValidationError(f"invalid pattern at {path}: {exc}") from exc
    properties = fragment.get("properties", {})
    definitions = fragment.get("$defs", {})
    if not isinstance(properties, dict) or not isinstance(definitions, dict):
        raise SchemaValidationError(f"{path} properties and $defs must be objects")
    for label, children in (("properties", properties), ("$defs", definitions)):
        for key, child in children.items():
            _validate_schema_structure(child, root, f"{path}.{label}.{key}", reference_stack)
    additional = fragment.get("additionalProperties", True)
    if not isinstance(additional, bool):
        _validate_schema_structure(additional, root, f"{path}.additionalProperties", reference_stack)
    items = fragment.get("items")
    if items is not None:
        _validate_schema_structure(items, root, f"{path}.items", reference_stack)
    for keyword in ("allOf", "oneOf"):
        children = fragment.get(keyword)
        if children is None:
            continue
        if not isinstance(children, list) or (keyword == "oneOf" and not children):
            raise SchemaValidationError(f"{path} {keyword} must be an array")
        for index, child in enumerate(children):
            _validate_schema_structure(child, root, f"{path}.{keyword}[{index}]", reference_stack)
    reference = fragment.get("$ref")
    if reference is not None:
        target = _resolve_reference(reference, root)
        if reference in reference_stack:
            raise SchemaValidationError(f"recursive output-schema reference is unsupported: {reference}")
        _validate_schema_structure(target, root, path, (*reference_stack, reference))


def _resolve_reference(reference: Any, root: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(reference, str) or not reference.startswith("#/"):
        raise SchemaValidationError("only local output-schema references are supported")
    target: Any = root
    for raw in reference[2:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, dict) or part not in target:
            raise SchemaValidationError(f"unresolved output-schema reference {reference!r}")
        target = target[part]
    if not isinstance(target, dict):
        raise SchemaValidationError(f"output-schema reference {reference!r} is not an object")
    return target


def _validate(value: Any, fragment: Mapping[str, Any], root: Mapping[str, Any], path: str) -> None:
    unknown = set(fragment) - SUPPORTED
    if unknown:
        raise SchemaValidationError(f"unsupported output-schema keywords at {path}: {sorted(unknown)}")
    reference = fragment.get("$ref")
    if reference is not None:
        target = _resolve_reference(reference, root)
        _validate(value, target, root, path)
    expected_type = fragment.get("type")
    if expected_type is not None and not _matches_type(value, expected_type):
        raise SchemaValidationError(f"{path} does not match declared type {expected_type!r}")
    if "const" in fragment and value != fragment["const"]:
        raise SchemaValidationError(f"{path} does not match declared const")
    if "enum" in fragment:
        enum = fragment["enum"]
        if not isinstance(enum, list) or value not in enum:
            raise SchemaValidationError(f"{path} is outside the declared enum")
    if isinstance(value, dict):
        required = fragment.get("required", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise SchemaValidationError(f"{path} required must be a string array")
        missing = set(required) - set(value)
        if missing:
            raise SchemaValidationError(f"{path} is missing declared fields {sorted(missing)}")
        properties = fragment.get("properties", {})
        if not isinstance(properties, dict):
            raise SchemaValidationError(f"{path} properties must be an object")
        for key, child in properties.items():
            if key in value:
                if not isinstance(child, dict):
                    raise SchemaValidationError(f"{path}.{key} schema must be an object")
                _validate(value[key], child, root, f"{path}.{key}")
        additional = fragment.get("additionalProperties", True)
        if additional is False:
            extra = set(value) - set(properties)
            if extra:
                raise SchemaValidationError(f"{path} has undeclared fields {sorted(extra)}")
        elif isinstance(additional, dict):
            for key in set(value) - set(properties):
                _validate(value[key], additional, root, f"{path}.{key}")
        elif additional is not True:
            raise SchemaValidationError(f"{path} additionalProperties is invalid")
    if isinstance(value, list):
        _bound(len(value), fragment.get("minItems"), fragment.get("maxItems"), path)
        items = fragment.get("items")
        if items is not None:
            if not isinstance(items, dict):
                raise SchemaValidationError(f"{path} items must be an object")
            for index, item in enumerate(value):
                _validate(item, items, root, f"{path}[{index}]")
    if isinstance(value, str):
        _bound(len(value), fragment.get("minLength"), fragment.get("maxLength"), path)
        pattern = fragment.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str):
                raise SchemaValidationError(f"{path} pattern must be text")
            try:
                matched = re.search(pattern, value)
            except re.error as exc:
                raise SchemaValidationError(f"invalid pattern at {path}: {exc}") from exc
            if matched is None:
                raise SchemaValidationError(f"{path} does not match declared pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = fragment.get("minimum")
        maximum = fragment.get("maximum")
        if minimum is not None and (
            not isinstance(minimum, (int, float)) or isinstance(minimum, bool)
        ):
            raise SchemaValidationError(f"{path} minimum must be numeric")
        if maximum is not None and (
            not isinstance(maximum, (int, float)) or isinstance(maximum, bool)
        ):
            raise SchemaValidationError(f"{path} maximum must be numeric")
        if minimum is not None and value < minimum:
            raise SchemaValidationError(f"{path} is below declared minimum")
        if maximum is not None and value > maximum:
            raise SchemaValidationError(f"{path} is above declared maximum")
    all_of = fragment.get("allOf", [])
    if not isinstance(all_of, list):
        raise SchemaValidationError(f"{path} allOf must be an array")
    for child in all_of:
        if not isinstance(child, dict):
            raise SchemaValidationError(f"{path} allOf entry must be an object")
        _validate(value, child, root, path)
    one_of = fragment.get("oneOf")
    if one_of is not None:
        if not isinstance(one_of, list) or not one_of:
            raise SchemaValidationError(f"{path} oneOf must be a nonempty array")
        matches = 0
        for child in one_of:
            try:
                if not isinstance(child, dict):
                    raise SchemaValidationError("oneOf entry must be an object")
                _validate(value, child, root, path)
            except SchemaValidationError:
                continue
            matches += 1
        if matches != 1:
            raise SchemaValidationError(f"{path} must match exactly one declared schema")


def _matches_type(value: Any, expected: Any) -> bool:
    names = [expected] if isinstance(expected, str) else expected
    if not isinstance(names, list) or not all(isinstance(item, str) for item in names):
        raise SchemaValidationError("schema type must be text or a text array")
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if any(name not in checks for name in names):
        raise SchemaValidationError(f"unsupported schema type {names}")
    return any(checks[name](value) for name in names)


def _bound(actual: int, minimum: Any, maximum: Any, path: str) -> None:
    if minimum is not None and (not isinstance(minimum, int) or actual < minimum):
        raise SchemaValidationError(f"{path} is below its declared minimum size")
    if maximum is not None and (not isinstance(maximum, int) or actual > maximum):
        raise SchemaValidationError(f"{path} exceeds its declared maximum size")
