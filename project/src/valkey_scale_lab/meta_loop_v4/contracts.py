from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_control_block(control: dict[str, Any]) -> None:
    errors: list[str] = []
    if control.get("schema_version") != "v4":
        errors.append("schema_version must be v4")
    scope = control.get("scope_freeze")
    if not isinstance(scope, dict):
        errors.append("scope_freeze must be an object")
    else:
        if scope.get("required_real_scales") != [50, 200]:
            errors.append("required_real_scales must be exactly [50, 200]")
        if scope.get("supported_not_gated_scales") != [30, 100]:
            errors.append("supported_not_gated_scales must be exactly [30, 100]")
        trigger = scope.get("trigger_nodes", {})
        if trigger != {"min": 30, "max": 2000, "exact": True}:
            errors.append("trigger_nodes must freeze exact support at 30..2000")
        above = scope.get("above_200", {})
        expected = {
            "automatic": False,
            "operator_opt_in": True,
            "resource_preflight": True,
            "cost_acknowledgement": True,
            "silent_downscale": False,
        }
        if above != expected:
            errors.append("above_200 safety contract is invalid")

    policy = control.get("controller_policy")
    if not isinstance(policy, dict):
        errors.append("controller_policy must be an object")
    else:
        for key in (
            "max_attempts_per_objective",
            "stagnation_limit",
            "max_replans_per_objective",
            "max_review_rounds_per_objective",
        ):
            if not isinstance(policy.get(key), int) or int(policy[key]) < 1:
                errors.append(f"{key} must be a positive integer")
        if policy.get("max_new_gaps_per_review") != 1:
            errors.append("max_new_gaps_per_review must be exactly 1")

    objectives = control.get("objectives")
    if not isinstance(objectives, list) or not objectives:
        errors.append("objectives must be a non-empty list")
    else:
        ids = [item.get("id") for item in objectives if isinstance(item, dict)]
        if len(ids) != len(objectives) or len(ids) != len(set(ids)):
            errors.append("objective ids must be present and unique")
        known = set(ids)
        for item in objectives:
            if not isinstance(item, dict):
                continue
            oid = item.get("id", "<missing>")
            deps = item.get("depends_on")
            clauses = item.get("clauses")
            checks = item.get("checks")
            if not isinstance(deps, list) or any(dep not in known for dep in deps):
                errors.append(f"{oid}: invalid dependencies")
            if not isinstance(clauses, list) or not clauses or not all(isinstance(v, str) and v for v in clauses):
                errors.append(f"{oid}: clauses must be non-empty strings")
            if not isinstance(checks, list) or not checks:
                errors.append(f"{oid}: checks must be non-empty")
            else:
                for check in checks:
                    errors.extend(_check_errors(check, f"{oid}.checks"))

    common = control.get("common_checks")
    if not isinstance(common, list) or not common:
        errors.append("common_checks must be a non-empty list")
    else:
        for check in common:
            errors.extend(_check_errors(check, "common_checks"))

    for group in ("closure_checks", "evaluator_guard_checks"):
        checks = control.get(group)
        if not isinstance(checks, list) or not checks:
            errors.append(f"{group} must be a non-empty list")
        else:
            for check in checks:
                errors.extend(_check_errors(check, group))

    if isinstance(common, list) and isinstance(objectives, list):
        fixed_checks = [
            check
            for group in (common, control.get("closure_checks", []), control.get("evaluator_guard_checks", []))
            if isinstance(group, list)
            for check in group
            if isinstance(check, dict)
        ]
        common_ids = {check.get("id") for check in fixed_checks}
        if len(common_ids) != len(fixed_checks):
            errors.append("common, closure, and evaluator guard check ids must be globally unique")
        for item in objectives:
            if not isinstance(item, dict) or not isinstance(item.get("checks"), list):
                continue
            ids = [check.get("id") for check in item["checks"] if isinstance(check, dict)]
            if len(ids) != len(item["checks"]) or len(ids) != len(set(ids)) or common_ids.intersection(ids):
                errors.append(f"{item.get('id', '<missing>')}: check ids must be unique and not collide with common checks")

    if errors:
        raise ContractError("invalid control block:\n- " + "\n- ".join(errors))


def _check_errors(check: Any, location: str) -> list[str]:
    if not isinstance(check, dict):
        return [f"{location}: each check must be an object"]
    errors: list[str] = []
    cid = check.get("id", "<missing>")
    if not isinstance(check.get("id"), str) or not check["id"]:
        errors.append(f"{location}: check id is required")
    level = check.get("level")
    if not isinstance(level, int) or level not in range(5):
        errors.append(f"{location}.{cid}: level must be 0..4")
    command = check.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(v, str) and v for v in command):
        errors.append(f"{location}.{cid}: command must be a non-empty argv list")
    timeout = check.get("timeout_seconds")
    if not isinstance(timeout, int) or timeout < 1:
        errors.append(f"{location}.{cid}: timeout_seconds must be positive")
    inputs = check.get("inputs")
    if not isinstance(inputs, list) or not inputs or not all(isinstance(v, str) and v for v in inputs):
        errors.append(f"{location}.{cid}: inputs must be non-empty paths")
    if check.get("digest_mode") not in {None, "product_evidence", "admission"}:
        errors.append(f"{location}.{cid}: digest_mode is invalid")
    return errors
