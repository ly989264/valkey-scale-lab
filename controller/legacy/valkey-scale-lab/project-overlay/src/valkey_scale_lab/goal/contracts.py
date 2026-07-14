from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import CheckDefinition, GoalDefinition, KernelManifest, ObjectiveDefinition


class ContractError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{path} must contain a JSON object")
    return value


def parse_goal_definition(raw: dict[str, Any], *, expected_version: str) -> GoalDefinition:
    errors: list[str] = []
    if raw.get("schema_version") != expected_version:
        errors.append(f"schema_version must be {expected_version}")
    for key in ("goal_id", "goal"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            errors.append(f"{key} must be a non-empty string")
    _validate_scope(raw.get("scope_freeze"), errors)
    _validate_policy(raw.get("controller_policy"), errors)

    groups: dict[str, tuple[CheckDefinition, ...]] = {}
    check_ids: set[str] = set()
    for group in ("common_checks", "closure_checks", "evaluator_guard_checks"):
        groups[group] = _parse_checks(raw.get(group), group, check_ids, errors)

    objectives_raw = raw.get("objectives")
    objectives: list[ObjectiveDefinition] = []
    if not isinstance(objectives_raw, list) or not objectives_raw:
        errors.append("objectives must be a non-empty list")
        objectives_raw = []
    objective_ids = [item.get("id") for item in objectives_raw if isinstance(item, dict)]
    if len(objective_ids) != len(objectives_raw) or any(not isinstance(value, str) or not value for value in objective_ids):
        errors.append("objective ids must be non-empty strings")
    elif len(objective_ids) != len(set(objective_ids)):
        errors.append("objective ids must be unique")
    known = {value for value in objective_ids if isinstance(value, str)}
    graph: dict[str, tuple[str, ...]] = {}
    for index, item in enumerate(objectives_raw):
        if not isinstance(item, dict):
            errors.append(f"objectives[{index}] must be an object")
            continue
        oid = str(item.get("id", f"objectives[{index}]"))
        deps = item.get("depends_on")
        if not isinstance(deps, list) or not all(isinstance(dep, str) and dep in known and dep != oid for dep in deps):
            errors.append(f"{oid}: dependencies must reference other objectives")
            deps = []
        clauses = _strings(item.get("clauses"), f"{oid}.clauses", errors)
        context_paths = _strings(item.get("context_paths"), f"{oid}.context_paths", errors)
        checks = _parse_checks(item.get("checks"), f"{oid}.checks", check_ids, errors)
        title = item.get("title")
        if not isinstance(title, str) or not title:
            errors.append(f"{oid}.title must be a non-empty string")
            title = oid
        graph[oid] = tuple(deps)
        objectives.append(ObjectiveDefinition(oid, title, tuple(deps), clauses, context_paths, checks))
    _validate_dag(graph, errors)

    integrity = raw.get("integrity")
    if not isinstance(integrity, dict):
        errors.append("integrity must be an object")
        integrity = {}
    manifest_path = integrity.get("kernel_manifest")
    if not isinstance(manifest_path, str) or not manifest_path:
        errors.append("integrity.kernel_manifest must be a non-empty path")
        manifest_path = "MISSING"
    evaluator_paths = _strings(integrity.get("evaluator_paths"), "integrity.evaluator_paths", errors)
    repair_paths = _strings(integrity.get("evaluator_repair_allowed_paths"), "integrity.evaluator_repair_allowed_paths", errors)
    product_roots = _strings(integrity.get("product_roots"), "integrity.product_roots", errors)
    product_excludes = _strings(integrity.get("product_excludes"), "integrity.product_excludes", errors)
    mandatory_excludes = {"src/valkey_scale_lab/goal", "src/valkey_scale_lab/meta_loop", "scripts/meta_m1_"}
    if not mandatory_excludes.issubset(set(product_excludes)):
        errors.append("integrity.product_excludes must exclude goal, every meta_loop version, and every meta_m1 script by prefix")
    if not set(evaluator_paths).issubset(set(repair_paths)):
        errors.append("evaluator_repair_paths must include every evaluator path")
    if errors:
        raise ContractError("invalid goal definition:\n- " + "\n- ".join(errors))
    return GoalDefinition(
        schema_version=expected_version,
        goal_id=str(raw["goal_id"]),
        goal=str(raw["goal"]),
        scope_freeze=dict(raw["scope_freeze"]),
        controller_policy=dict(raw["controller_policy"]),
        common_checks=groups["common_checks"],
        closure_checks=groups["closure_checks"],
        evaluator_guard_checks=groups["evaluator_guard_checks"],
        kernel_manifest_path=manifest_path,
        evaluator_paths=evaluator_paths,
        evaluator_repair_paths=repair_paths,
        product_roots=product_roots,
        product_excludes=product_excludes,
        objectives=tuple(objectives),
    )


def load_kernel_manifest(project_root: Path, relative_path: str) -> KernelManifest:
    path = (project_root / relative_path).resolve()
    if not path.is_relative_to(project_root.resolve()):
        raise ContractError("kernel manifest escapes project root")
    raw = load_json(path)
    if raw.get("schema_version") != "meta-loop-v7-kernel-manifest-v1":
        raise ContractError("unsupported kernel manifest schema")
    files = raw.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(value, str) and value for value in files):
        raise ContractError("kernel manifest files must be a non-empty string list")
    if len(files) != len(set(files)):
        raise ContractError("kernel manifest files must be unique")
    for raw_path in files:
        candidate = (project_root / raw_path).resolve()
        if not candidate.is_relative_to(project_root.resolve()) or not candidate.is_file():
            raise ContractError(f"kernel manifest file is missing or escapes project: {raw_path}")
    return KernelManifest(relative_path, tuple(files))


def parse_check(raw: Any, location: str = "check") -> CheckDefinition:
    errors: list[str] = []
    checks = _parse_checks([raw], location, set(), errors)
    if errors:
        raise ContractError("invalid check:\n- " + "\n- ".join(errors))
    return checks[0]


def _parse_checks(raw: Any, location: str, known_ids: set[str], errors: list[str]) -> tuple[CheckDefinition, ...]:
    if not isinstance(raw, list) or not raw:
        errors.append(f"{location} must be a non-empty list")
        return ()
    parsed: list[CheckDefinition] = []
    for index, item in enumerate(raw):
        here = f"{location}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{here} must be an object")
            continue
        cid = item.get("id")
        if not isinstance(cid, str) or not cid:
            errors.append(f"{here}.id must be a non-empty string")
            continue
        if cid in known_ids:
            errors.append(f"check id {cid!r} is not globally unique")
        known_ids.add(cid)
        level = item.get("level")
        command = item.get("command")
        timeout = item.get("timeout_seconds")
        inputs = item.get("inputs")
        digest_mode = item.get("digest_mode")
        if not isinstance(level, int) or level not in range(5):
            errors.append(f"{here}.level must be 0..4")
            level = 0
        if not isinstance(command, list) or not command or not all(isinstance(value, str) and value for value in command):
            errors.append(f"{here}.command must be a non-empty argv list")
            command = ["python3", "missing.py"]
        if not isinstance(timeout, int) or timeout < 1:
            errors.append(f"{here}.timeout_seconds must be positive")
            timeout = 1
        if not isinstance(inputs, list) or not inputs or not all(isinstance(value, str) and value for value in inputs):
            errors.append(f"{here}.inputs must be non-empty paths")
            inputs = ["MISSING"]
        if digest_mode not in {None, "product_evidence", "admission"}:
            errors.append(f"{here}.digest_mode is invalid")
            digest_mode = None
        parsed.append(CheckDefinition(cid, level, tuple(command), timeout, tuple(inputs), digest_mode))
    return tuple(parsed)


def _strings(raw: Any, location: str, errors: list[str]) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw or not all(isinstance(value, str) and value for value in raw):
        errors.append(f"{location} must be a non-empty string list")
        return ()
    return tuple(raw)


def _validate_scope(raw: Any, errors: list[str]) -> None:
    if not isinstance(raw, dict):
        errors.append("scope_freeze must be an object")
        return
    if raw.get("required_real_scales") != [50, 200]:
        errors.append("required_real_scales must be exactly [50, 200]")
    if raw.get("supported_not_gated_scales") != [30, 100]:
        errors.append("supported_not_gated_scales must be exactly [30, 100]")
    if raw.get("trigger_nodes") != {"min": 30, "max": 2000, "exact": True}:
        errors.append("trigger_nodes must freeze exact support at 30..2000")
    if raw.get("normal_development_max_nodes") != 100:
        errors.append("normal_development_max_nodes must be exactly 100")
    if raw.get("required_200_bounded_exception") is not True:
        errors.append("required_200_bounded_exception must be true")
    expected = {"automatic": False, "operator_opt_in": True, "resource_preflight": True, "cost_acknowledgement": True, "silent_downscale": False}
    if raw.get("above_200") != expected:
        errors.append("above_200 safety contract is invalid")


def _validate_policy(raw: Any, errors: list[str]) -> None:
    if not isinstance(raw, dict):
        errors.append("controller_policy must be an object")
        return
    for key in ("max_attempts_per_objective", "stagnation_limit", "max_replans_per_objective", "max_review_rounds_per_objective", "failure_excerpt_bytes", "max_context_bytes"):
        if not isinstance(raw.get(key), int) or raw[key] < 1:
            errors.append(f"{key} must be a positive integer")
    if raw.get("max_new_gaps_per_review") != 1:
        errors.append("max_new_gaps_per_review must be exactly 1")
    if raw.get("expensive_levels") != [3, 4]:
        errors.append("expensive_levels must be exactly [3, 4]")
    if raw.get("max_expensive_runs_per_input") != 1:
        errors.append("max_expensive_runs_per_input must be exactly 1")


def _validate_dag(graph: dict[str, tuple[str, ...]], errors: list[str]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            errors.append(f"objective dependency cycle includes {node}")
            return
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph.get(node, ()):
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
