from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from verification.catalog import (
    Catalog,
    GateError,
    ParameterSpec,
    TestSpec,
    load_json_object,
)


INTEGER_PATTERN = re.compile(r"^[+-]?[0-9]+$", re.ASCII)


@dataclass(frozen=True)
class PlannedTest:
    test: TestSpec
    argv: tuple[str, ...]
    cwd: Path
    run_id: str
    artifacts_dir: Path
    result_path: Path


@dataclass(frozen=True)
class ExecutionPlan:
    invocation_id: str
    selection_kind: str
    selection_id: str
    artifacts_dir: Path
    tests: tuple[PlannedTest, ...]


def select_test(catalog: Catalog, test_id: str) -> tuple[TestSpec, ...]:
    try:
        return (catalog.tests[test_id],)
    except KeyError as exc:
        raise GateError(f"unknown test id: {test_id}") from exc


def select_suite(catalog: Catalog, suite_id: str) -> tuple[TestSpec, ...]:
    try:
        suite = catalog.suites[suite_id]
    except KeyError as exc:
        raise GateError(f"unknown suite id: {suite_id}") from exc
    return tuple(catalog.tests[test_id] for test_id in suite.test_ids)


def parse_cli_parameters(values: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        name, separator, raw = value.partition("=")
        if not separator or not name:
            raise GateError(f"parameter must use NAME=VALUE: {value!r}")
        if name in result:
            raise GateError(f"duplicate parameter: {name}")
        result[name] = raw
    return result


def load_suite_parameters(path: Path | None) -> dict[str, Any]:
    return {} if path is None else load_json_object(path)


def _inside_project(path: Path, project_root: Path) -> bool:
    try:
        path.relative_to(project_root)
    except ValueError:
        return False
    return True


def _coerce_cli_value(raw: str, spec: ParameterSpec) -> Any:
    if spec.type in {"string", "path"}:
        return raw
    if spec.type == "boolean":
        lowered = raw.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        raise GateError(f"parameter {spec.name} must be true or false")
    if spec.type == "integer":
        if INTEGER_PATTERN.fullmatch(raw) is None:
            raise GateError(f"parameter {spec.name} must be an integer")
        return int(raw)
    try:
        value = float(raw)
    except ValueError as exc:
        raise GateError(f"parameter {spec.name} must be a number") from exc
    if not math.isfinite(value):
        raise GateError(f"parameter {spec.name} must be finite")
    return value


def _validate_value(
    value: Any,
    spec: ParameterSpec,
    project_root: Path,
    *,
    cli_source: bool,
) -> Any:
    if cli_source:
        if not isinstance(value, str):
            raise GateError(f"parameter {spec.name} must be text on the command line")
        value = _coerce_cli_value(value, spec)
    elif spec.type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise GateError(f"parameter {spec.name} must be an integer")
    elif spec.type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GateError(f"parameter {spec.name} must be a number")
        if not math.isfinite(float(value)):
            raise GateError(f"parameter {spec.name} must be finite")
    elif spec.type == "boolean":
        if not isinstance(value, bool):
            raise GateError(f"parameter {spec.name} must be boolean")
    elif not isinstance(value, str):
        raise GateError(f"parameter {spec.name} must be a string")

    if spec.minimum is not None and value < spec.minimum:
        raise GateError(f"parameter {spec.name} must be >= {spec.minimum}")
    if spec.maximum is not None and value > spec.maximum:
        raise GateError(f"parameter {spec.name} must be <= {spec.maximum}")
    if spec.type == "path":
        if not value or "\x00" in value:
            raise GateError(f"parameter {spec.name} must be a non-empty path")
        raw_path = Path(value)
        if raw_path.is_absolute():
            raise GateError(f"parameter {spec.name} must be relative to project root")
        resolved = (project_root / raw_path).resolve()
        if not _inside_project(resolved, project_root) or not resolved.exists():
            raise GateError(
                f"parameter {spec.name} must name an existing project path"
            )
        return resolved
    return value


def validate_parameters(
    test: TestSpec,
    raw_values: Mapping[str, Any],
    project_root: Path,
    *,
    cli_source: bool,
) -> dict[str, Any]:
    unknown = sorted(set(raw_values) - set(test.parameters))
    if unknown:
        raise GateError(f"{test.test_id} received unknown parameters: {unknown}")
    missing = sorted(
        name
        for name, spec in test.parameters.items()
        if spec.required and name not in raw_values
    )
    if missing:
        raise GateError(f"{test.test_id} is missing required parameters: {missing}")
    return {
        name: _validate_value(
            raw_values[name], spec, project_root, cli_source=cli_source
        )
        for name, spec in test.parameters.items()
        if name in raw_values
    }


def _render_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _render(template: str, values: Mapping[str, str]) -> str:
    rendered = template
    for name, value in values.items():
        rendered = rendered.replace("{" + name + "}", value)
    if "{" in rendered or "}" in rendered:
        raise GateError(f"unresolved template in {template!r}")
    return rendered


def _invocation_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"gate-{stamp}-{uuid4().hex[:8]}"


def build_plan(
    tests: Sequence[TestSpec],
    parameters_by_test: Mapping[str, Mapping[str, Any]],
    project_root: Path,
    *,
    selection_kind: str,
    selection_id: str,
    cli_source: bool,
    invocation_id: str | None = None,
) -> ExecutionPlan:
    project_root = project_root.resolve()
    invocation = invocation_id or _invocation_id()
    invocation_dir = project_root / "artifacts" / "gate-runs" / invocation
    planned: list[PlannedTest] = []
    for index, test in enumerate(tests, start=1):
        raw_values = parameters_by_test.get(test.test_id, {})
        values = validate_parameters(
            test, raw_values, project_root, cli_source=cli_source
        )
        test_dir = invocation_dir / test.test_id
        suffix = "xml" if test.runner.result == "junit" else "json"
        result_path = test_dir / f"result.{suffix}"
        run_id = f"{invocation}-{index}"
        templates = {
            "gate.project_root": str(project_root),
            "gate.run_id": run_id,
            "gate.artifacts_dir": str(test_dir),
            "gate.result_path": str(result_path),
        }
        templates.update(
            {f"param.{name}": _render_value(value) for name, value in values.items()}
        )
        cwd = Path(_render(test.runner.cwd, templates)).resolve()
        if not _inside_project(cwd, project_root):
            raise GateError(f"{test.test_id} runner cwd escapes project root")
        if not cwd.is_dir():
            raise GateError(f"{test.test_id} runner cwd is not a directory: {cwd}")
        argv = tuple(_render(argument, templates) for argument in test.runner.argv)
        planned.append(
            PlannedTest(test, argv, cwd, run_id, test_dir, result_path)
        )
    return ExecutionPlan(
        invocation,
        selection_kind,
        selection_id,
        invocation_dir,
        tuple(planned),
    )


def parameters_for_suite(
    tests: Sequence[TestSpec],
    raw_parameters: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    test_ids = {test.test_id for test in tests}
    unknown = sorted(set(raw_parameters) - test_ids)
    if unknown:
        raise GateError(f"params file contains tests outside the suite: {unknown}")
    result: dict[str, Mapping[str, Any]] = {}
    for test_id, values in raw_parameters.items():
        if not isinstance(values, dict):
            raise GateError(f"params for {test_id} must be an object")
        result[test_id] = values
    return result
