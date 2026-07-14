#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = Path(__file__).with_name("catalog.json")
MILESTONE_ROOT = PROJECT_ROOT / "milestones"
ID_PATTERN = re.compile(r"[a-z][a-z0-9_.-]*", re.ASCII)
PLACEHOLDER_PATTERN = re.compile(r"\{([a-z][a-z0-9_]*)\}", re.ASCII)
FORBIDDEN_MILESTONE_FIELDS = {
    "argv",
    "command",
    "objectives",
    "profiles",
    "resource_budget",
    "worker_write_paths",
}


class VerificationError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise VerificationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise VerificationError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{path} must contain a JSON object")
    return value


def _catalog() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    document = _load(CATALOG_PATH)
    errors: list[str] = []
    if document.get("schema_version") != "verification-catalog-v1":
        errors.append("catalog.schema_version must be 'verification-catalog-v1'")
    rows = document.get("suites")
    if not isinstance(rows, list) or not rows:
        errors.append("catalog.suites must be a non-empty array")
        rows = []
    by_id: dict[str, dict[str, Any]] = {}
    required = {
        "id", "title", "kind", "status", "argv", "timeout_seconds",
        "capabilities", "outputs", "skip_policy",
    }
    for index, row in enumerate(rows):
        location = f"catalog.suites[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{location} must be an object")
            continue
        if set(row) != required:
            errors.append(f"{location} fields must be {sorted(required)}")
            continue
        suite_id = row.get("id")
        if not isinstance(suite_id, str) or ID_PATTERN.fullmatch(suite_id) is None:
            errors.append(f"{location}.id is invalid")
            continue
        if suite_id in by_id:
            errors.append(f"duplicate suite id: {suite_id}")
        by_id[suite_id] = row
        if row.get("kind") not in {"pytest", "command", "real"}:
            errors.append(f"{location}.kind is invalid")
        if row.get("status") not in {"READY", "PLANNED"}:
            errors.append(f"{location}.status is invalid")
        argv = row.get("argv")
        if not isinstance(argv, list) or any(not isinstance(item, str) or not item for item in argv):
            errors.append(f"{location}.argv must be a string array")
        elif row.get("status") == "READY" and not argv:
            errors.append(f"{location}.argv is required for a READY suite")
        if not isinstance(row.get("timeout_seconds"), int) or row["timeout_seconds"] <= 0:
            errors.append(f"{location}.timeout_seconds must be positive")
        if row.get("skip_policy") not in {"FAIL", "ALLOW"}:
            errors.append(f"{location}.skip_policy is invalid")
    if errors:
        raise VerificationError("; ".join(errors))
    return document, by_id


def _walk_keys(value: Any) -> Sequence[str]:
    keys: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.append(str(key))
            keys.extend(_walk_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.extend(_walk_keys(item))
    return keys


def _validate_prerequisites(
    milestone_id: str,
    document: Mapping[str, Any],
    errors: list[str],
) -> None:
    raw = document.get("prerequisite_milestone_ids")
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        errors.append("prerequisite_milestone_ids must be a string array")
        return
    if len(raw) != len(set(raw)):
        errors.append("prerequisite_milestone_ids must be unique")
    if milestone_id in raw:
        errors.append("milestone cannot require itself")

    visited: set[str] = set()

    def visit(current: str, stack: tuple[str, ...]) -> None:
        if current in stack:
            errors.append(f"milestone prerequisite cycle: {(*stack, current)}")
            return
        if current in visited:
            return
        path = MILESTONE_ROOT / current / "milestone.json"
        try:
            prerequisite = _load(path)
        except VerificationError as exc:
            errors.append(f"unknown prerequisite milestone {current}: {exc}")
            return
        identity = prerequisite.get("milestone")
        if not isinstance(identity, dict) or identity.get("id") != current:
            errors.append(f"prerequisite milestone identity mismatch: {current}")
            return
        nested = prerequisite.get("prerequisite_milestone_ids")
        if not isinstance(nested, list) or any(not isinstance(item, str) for item in nested):
            errors.append(f"prerequisite milestone {current} has an invalid prerequisite list")
            return
        for dependency in nested:
            visit(dependency, (*stack, current))
        visited.add(current)

    for prerequisite_id in raw:
        visit(prerequisite_id, (milestone_id,))


def validate_milestone(milestone_id: str) -> dict[str, Any]:
    _document, suites = _catalog()
    path = MILESTONE_ROOT / milestone_id / "milestone.json"
    document = _load(path)
    errors: list[str] = []
    if document.get("schema_version") != "valkey-milestone-v1":
        errors.append("milestone.schema_version must be 'valkey-milestone-v1'")
    identity = document.get("milestone")
    if not isinstance(identity, dict) or identity.get("id") != milestone_id:
        errors.append("milestone identity does not match its directory")
    _validate_prerequisites(milestone_id, document, errors)
    forbidden = sorted(FORBIDDEN_MILESTONE_FIELDS.intersection(_walk_keys(document)))
    if forbidden:
        errors.append(f"milestone contains controller or executable fields: {forbidden}")
    conditions = document.get("success_conditions")
    gates = document.get("evidence_gates")
    if not isinstance(conditions, list) or not conditions:
        errors.append("success_conditions must be a non-empty array")
        conditions = []
    if not isinstance(gates, list):
        errors.append("evidence_gates must be an array")
        gates = []
    gate_by_id: dict[str, dict[str, Any]] = {}
    for gate in gates:
        if not isinstance(gate, dict) or not isinstance(gate.get("id"), str):
            errors.append("every evidence gate requires an id")
            continue
        if gate["id"] in gate_by_id:
            errors.append(f"duplicate evidence gate id: {gate['id']}")
        gate_by_id[gate["id"]] = gate
    referenced_suites: set[str] = set()
    referenced_gates: set[str] = set()
    condition_ids: set[str] = set()
    for condition in conditions:
        if not isinstance(condition, dict) or not isinstance(condition.get("id"), str):
            errors.append("every success condition requires an id")
            continue
        if condition["id"] in condition_ids:
            errors.append(f"duplicate success condition id: {condition['id']}")
        condition_ids.add(condition["id"])
        suite_ids = condition.get("suite_ids")
        gate_ids = condition.get("evidence_gate_ids")
        if not isinstance(suite_ids, list) or any(not isinstance(item, str) for item in suite_ids):
            errors.append(f"{condition['id']}.suite_ids must be a string array")
        else:
            referenced_suites.update(suite_ids)
        if not isinstance(gate_ids, list) or any(not isinstance(item, str) for item in gate_ids):
            errors.append(f"{condition['id']}.evidence_gate_ids must be a string array")
        else:
            referenced_gates.update(gate_ids)
    for gate_id, gate in gate_by_id.items():
        suite_id = gate.get("suite_id")
        if isinstance(suite_id, str):
            referenced_suites.add(suite_id)
        else:
            errors.append(f"{gate_id}.suite_id is required")
        dependencies = gate.get("depends_on")
        if not isinstance(dependencies, list) or any(item not in gate_by_id for item in dependencies):
            errors.append(f"{gate_id}.depends_on references an unknown gate")
        parameters = gate.get("parameters")
        prior_gate = parameters.get("prior_gate") if isinstance(parameters, dict) else None
        if dependencies:
            if len(dependencies) != 1 or prior_gate != dependencies[0]:
                errors.append(f"{gate_id}.parameters.prior_gate must bind its single dependency")
        elif prior_gate is not None:
            errors.append(f"{gate_id}.parameters.prior_gate is not allowed without a dependency")
        serialized = json.dumps(gate, sort_keys=True)
        if "tests/" in serialized or "pytest" in serialized:
            errors.append(f"{gate_id} directly references test implementation")
    unknown_suites = sorted(referenced_suites - set(suites))
    unknown_gates = sorted(referenced_gates - set(gate_by_id))
    if unknown_suites:
        errors.append(f"unknown suite ids: {unknown_suites}")
    if unknown_gates:
        errors.append(f"unknown evidence gate ids: {unknown_gates}")
    planned = sorted(
        suite_id
        for suite_id in referenced_suites.intersection(suites)
        if suites[suite_id]["status"] == "PLANNED"
    )
    status = "INVALID" if errors else "BLOCKED" if planned else "READY"
    return {
        "schema_version": "milestone-validation-v1",
        "milestone_id": milestone_id,
        "status": status,
        "errors": errors,
        "planned_suite_ids": planned,
        "referenced_suite_ids": sorted(referenced_suites),
    }


def _parameters(values: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        key, separator, item = value.partition("=")
        if not separator or not key or not item:
            raise VerificationError(f"parameter must use NAME=VALUE: {value!r}")
        result[key] = item
    return result


def _render_argv(argv: Sequence[str], parameters: Mapping[str, str]) -> list[str]:
    rendered: list[str] = []
    missing: set[str] = set()
    for argument in argv:
        missing.update(
            name for name in PLACEHOLDER_PATTERN.findall(argument) if name not in parameters
        )
        rendered.append(argument.format_map(parameters) if not missing else argument)
    if missing:
        raise VerificationError(f"missing suite parameters: {sorted(missing)}")
    return [argument.format_map(parameters) for argument in argv]


def run_suite(
    suite_id: str,
    raw_parameters: Sequence[str],
    allowed_capabilities: Sequence[str],
    result_path: Path | None = None,
) -> int:
    started_at = int(time.time())

    def finish(status: str, exit_code: int, skipped: int = 0) -> int:
        if result_path is not None:
            value = {
                "schema_version": "verification-suite-result-v1",
                "suite_id": suite_id,
                "status": status,
                "exit_code": exit_code,
                "skipped": skipped,
                "started_at_unix": started_at,
                "captured_at_unix": int(time.time()),
            }
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        return exit_code

    _document, suites = _catalog()
    if suite_id not in suites:
        raise VerificationError(f"unknown suite id: {suite_id}")
    suite = suites[suite_id]
    if suite["status"] == "PLANNED":
        print(json.dumps({"suite_id": suite_id, "status": "BLOCKED", "reason": "suite is PLANNED"}, sort_keys=True))
        return finish("BLOCKED", 2)
    missing_capabilities = sorted(set(suite["capabilities"]) - set(allowed_capabilities))
    if missing_capabilities:
        print(json.dumps({"suite_id": suite_id, "status": "BLOCKED", "missing_capabilities": missing_capabilities}, sort_keys=True))
        return finish("BLOCKED", 2)
    parameters = _parameters(raw_parameters)
    if suite["kind"] == "real":
        artifacts = parameters.get("artifacts_dir", "")
        serialized = json.dumps(parameters, sort_keys=True).lower()
        if "fixture" in serialized or "dry_run" in serialized or "dry-run" in serialized:
            raise VerificationError("real suite parameters may not select fixtures or dry runs")
        artifact_path = (PROJECT_ROOT / artifacts).resolve()
        if not artifacts or artifact_path.is_relative_to((PROJECT_ROOT / "tests").resolve()):
            raise VerificationError("real suite artifacts_dir must be outside the test tree")
    argv = _render_argv(suite["argv"], parameters)
    if argv and argv[0] == "python3":
        argv[0] = sys.executable
    if suite["kind"] == "real" and parameters.get("prior_admission_digest"):
        argv.extend(
            ["--prior-admission-digest", parameters["prior_admission_digest"]]
        )
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    with tempfile.TemporaryDirectory(prefix="vslab-verification-") as temporary:
        junit_path = Path(temporary) / "junit.xml"
        if suite["kind"] == "pytest":
            argv.append(f"--junitxml={junit_path}")
        completed = subprocess.run(
            argv,
            cwd=PROJECT_ROOT,
            env=environment,
            check=False,
            timeout=suite["timeout_seconds"],
        )
        skipped = 0
        if suite["kind"] == "pytest":
            root = ET.parse(junit_path).getroot()
            if root.tag == "testsuites" and "skipped" in root.attrib:
                skipped = int(root.attrib.get("skipped", "0"))
            elif root.tag == "testsuite":
                skipped = int(root.attrib.get("skipped", "0"))
            else:
                skipped = sum(
                    int(element.attrib.get("skipped", "0"))
                    for element in root.iter("testsuite")
                )
        if completed.returncode != 0:
            return finish("FAIL", completed.returncode, skipped)
        if suite["kind"] == "pytest" and suite["skip_policy"] == "FAIL":
            if skipped:
                print(f"FAIL: required suite skipped {skipped} test(s)", file=sys.stderr)
                return finish("FAIL", 1, skipped)
    return finish("PASS", 0, skipped)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run framework-neutral project verification")
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("catalog")
    catalog.add_argument("action", choices=["validate"])
    milestone = commands.add_parser("milestone")
    milestone.add_argument("action", choices=["validate"])
    milestone.add_argument("--id", required=True, choices=["m1", "m2", "m3"])
    suite = commands.add_parser("suite")
    suite.add_argument("--id", required=True)
    suite.add_argument("--parameter", action="append", default=[])
    suite.add_argument("--allow-capability", action="append", default=[])
    suite.add_argument("--result", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "catalog":
            document, suites = _catalog()
            print(json.dumps({"schema_version": document["schema_version"], "status": "READY", "suite_count": len(suites)}, sort_keys=True))
            return 0
        if args.command == "milestone":
            report = validate_milestone(args.id)
            print(json.dumps(report, sort_keys=True))
            return 0 if report["status"] == "READY" else 2 if report["status"] == "BLOCKED" else 1
        return run_suite(args.id, args.parameter, args.allow_capability, args.result)
    except (VerificationError, OSError, subprocess.TimeoutExpired, ET.ParseError) as exc:
        print(f"ERROR: verification: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
