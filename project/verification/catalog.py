from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$", re.ASCII)
PLACEHOLDER_PATTERN = re.compile(r"\{([^{}]+)\}")
GATE_PLACEHOLDERS = {
    "gate.project_root",
    "gate.run_id",
    "gate.artifacts_dir",
    "gate.result_path",
}
PARAMETER_TYPES = {"string", "integer", "number", "boolean", "path"}


class GateError(ValueError):
    pass


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    type: str
    required: bool
    minimum: int | float | None = None
    maximum: int | float | None = None


@dataclass(frozen=True)
class RunnerSpec:
    type: str
    argv: tuple[str, ...]
    cwd: str
    timeout_seconds: int
    result: str


@dataclass(frozen=True)
class TestSpec:
    test_id: str
    description: str
    parameters: Mapping[str, ParameterSpec]
    runner: RunnerSpec


@dataclass(frozen=True)
class SuiteSpec:
    suite_id: str
    description: str
    test_ids: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    suites: Mapping[str, SuiteSpec]
    tests: Mapping[str, TestSpec]


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GateError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except GateError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError(f"{path} must contain a JSON object")
    return value


def _require_fields(
    value: Mapping[str, Any],
    required: set[str],
    location: str,
) -> None:
    actual = set(value)
    if actual != required:
        missing = sorted(required - actual)
        extra = sorted(actual - required)
        details = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unexpected {extra}")
        raise GateError(f"{location} has invalid fields: {', '.join(details)}")


def _identifier(value: Any, location: str) -> str:
    if not isinstance(value, str) or ID_PATTERN.fullmatch(value) is None:
        raise GateError(f"{location} must be a lowercase identifier")
    return value


def _description(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateError(f"{location} must be non-empty text")
    return value.strip()


def _parameter(name: str, value: Any, location: str) -> ParameterSpec:
    _identifier(name, f"{location} name")
    if not isinstance(value, dict):
        raise GateError(f"{location} must be an object")
    allowed = {"type", "required", "minimum", "maximum"}
    extra = sorted(set(value) - allowed)
    if extra:
        raise GateError(f"{location} has unexpected fields: {extra}")
    if "type" not in value or "required" not in value:
        raise GateError(f"{location} requires type and required")
    parameter_type = value["type"]
    if parameter_type not in PARAMETER_TYPES:
        raise GateError(f"{location}.type is invalid")
    required = value["required"]
    if not isinstance(required, bool):
        raise GateError(f"{location}.required must be boolean")
    minimum = value.get("minimum")
    maximum = value.get("maximum")
    if minimum is not None or maximum is not None:
        if parameter_type not in {"integer", "number"}:
            raise GateError(f"{location} bounds require a numeric type")
        for label, bound in (("minimum", minimum), ("maximum", maximum)):
            if bound is not None and (
                isinstance(bound, bool) or not isinstance(bound, (int, float))
            ):
                raise GateError(f"{location}.{label} must be numeric")
            if parameter_type == "integer" and bound is not None and not isinstance(bound, int):
                raise GateError(f"{location}.{label} must be an integer")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise GateError(f"{location}.minimum cannot exceed maximum")
    return ParameterSpec(name, parameter_type, required, minimum, maximum)


def _template_names(value: str, location: str) -> set[str]:
    names = set(PLACEHOLDER_PATTERN.findall(value))
    residue = PLACEHOLDER_PATTERN.sub("", value)
    if "{" in residue or "}" in residue:
        raise GateError(f"{location} contains malformed template syntax")
    return names


def _runner(
    value: Any,
    parameters: Mapping[str, ParameterSpec],
    location: str,
) -> RunnerSpec:
    if not isinstance(value, dict):
        raise GateError(f"{location} must be an object")
    _require_fields(
        value,
        {"type", "argv", "cwd", "timeout_seconds", "result"},
        location,
    )
    runner_type = value["type"]
    result_type = value["result"]
    valid_pair = (runner_type == "pytest" and result_type == "junit") or (
        runner_type == "command" and result_type in {"exit_code", "json"}
    )
    if not valid_pair:
        raise GateError(
            f"{location} must use pytest+junit or command+exit_code/json"
        )
    argv = value["argv"]
    if not isinstance(argv, list) or not argv or any(
        not isinstance(item, str) or not item for item in argv
    ):
        raise GateError(f"{location}.argv must be a non-empty string array")
    cwd = value["cwd"]
    if not isinstance(cwd, str) or not cwd:
        raise GateError(f"{location}.cwd must be non-empty text")
    timeout = value["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise GateError(f"{location}.timeout_seconds must be a positive integer")

    template_values = [*argv, cwd]
    referenced_parameters: set[str] = set()
    all_names: set[str] = set()
    for index, template in enumerate(template_values):
        names = _template_names(template, f"{location}.template[{index}]")
        all_names.update(names)
        for name in names:
            if name.startswith("param."):
                parameter_name = name.removeprefix("param.")
                if parameter_name not in parameters:
                    raise GateError(
                        f"{location} references undeclared parameter {parameter_name!r}"
                    )
                referenced_parameters.add(parameter_name)
            elif name not in GATE_PLACEHOLDERS:
                raise GateError(f"{location} uses unknown placeholder {{{name}}}")
    unused = sorted(set(parameters) - referenced_parameters)
    if unused:
        raise GateError(f"{location} declares unused parameters: {unused}")
    optional_references = sorted(
        name for name in referenced_parameters if not parameters[name].required
    )
    if optional_references:
        raise GateError(
            f"{location} template parameters must be required: {optional_references}"
        )
    if result_type in {"junit", "json"} and "gate.result_path" not in all_names:
        raise GateError(
            f"{location} must pass {{gate.result_path}} for {result_type} results"
        )
    return RunnerSpec(runner_type, tuple(argv), cwd, timeout, result_type)


def load_catalog(path: Path) -> Catalog:
    document = load_json_object(path)
    _require_fields(document, {"schema_version", "suites", "tests"}, "catalog")
    if document["schema_version"] != "verification-catalog-v2":
        raise GateError("catalog.schema_version must be 'verification-catalog-v2'")
    raw_tests = document["tests"]
    raw_suites = document["suites"]
    if not isinstance(raw_tests, list) or not raw_tests:
        raise GateError("catalog.tests must be a non-empty array")
    if not isinstance(raw_suites, list) or not raw_suites:
        raise GateError("catalog.suites must be a non-empty array")

    tests: dict[str, TestSpec] = {}
    for index, raw_test in enumerate(raw_tests):
        location = f"catalog.tests[{index}]"
        if not isinstance(raw_test, dict):
            raise GateError(f"{location} must be an object")
        _require_fields(
            raw_test,
            {"test_id", "description", "parameters", "runner"},
            location,
        )
        test_id = _identifier(raw_test["test_id"], f"{location}.test_id")
        if test_id in tests:
            raise GateError(f"duplicate test id: {test_id}")
        raw_parameters = raw_test["parameters"]
        if not isinstance(raw_parameters, dict):
            raise GateError(f"{location}.parameters must be an object")
        parameters = {
            name: _parameter(name, value, f"{location}.parameters.{name}")
            for name, value in raw_parameters.items()
        }
        tests[test_id] = TestSpec(
            test_id,
            _description(raw_test["description"], f"{location}.description"),
            parameters,
            _runner(raw_test["runner"], parameters, f"{location}.runner"),
        )

    suites: dict[str, SuiteSpec] = {}
    for index, raw_suite in enumerate(raw_suites):
        location = f"catalog.suites[{index}]"
        if not isinstance(raw_suite, dict):
            raise GateError(f"{location} must be an object")
        _require_fields(
            raw_suite,
            {"suite_id", "description", "test_ids"},
            location,
        )
        suite_id = _identifier(raw_suite["suite_id"], f"{location}.suite_id")
        if suite_id in suites:
            raise GateError(f"duplicate suite id: {suite_id}")
        if suite_id in tests:
            raise GateError(f"test and suite ids must be globally unique: {suite_id}")
        test_ids = raw_suite["test_ids"]
        if not isinstance(test_ids, list) or not test_ids or any(
            not isinstance(item, str) for item in test_ids
        ):
            raise GateError(f"{location}.test_ids must be a non-empty string array")
        if len(test_ids) != len(set(test_ids)):
            raise GateError(f"{location}.test_ids must be unique")
        unknown = sorted(set(test_ids) - set(tests))
        if unknown:
            raise GateError(f"{location} references unknown tests: {unknown}")
        suites[suite_id] = SuiteSpec(
            suite_id,
            _description(raw_suite["description"], f"{location}.description"),
            tuple(test_ids),
        )
    return Catalog(suites=suites, tests=tests)
