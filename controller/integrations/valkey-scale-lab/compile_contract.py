#!/usr/bin/env python3
"""Compile a Valkey product Milestone into the minimal Controller format."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


INTEGRATION_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = INTEGRATION_ROOT.parents[2]
DEFAULT_PROJECT_ROOT = REPOSITORY_ROOT / "project"
DEFAULT_POLICY_PATH = INTEGRATION_ROOT / "policy.json"


class CompileError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError, CompileError) as exc:
        raise CompileError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompileError(f"{path} must contain an object")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CompileError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def compile_contract(
    milestone_id: str,
    *,
    project_root: Path = DEFAULT_PROJECT_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    source = _load(project_root / "milestones" / milestone_id / "milestone.json")
    catalog = _load(project_root / "verification" / "catalog.json")
    policy = _load(Path(policy_path).resolve())
    if source.get("schema_version") != "valkey-milestone-v2":
        raise CompileError("unsupported project milestone")
    if catalog.get("schema_version") != "verification-catalog-v1":
        raise CompileError("unsupported verification catalog")
    if policy.get("schema_version") != "valkey-controller-run-policy-v1":
        raise CompileError("unsupported Controller run policy")

    identity = source.get("milestone")
    conditions = source.get("success_conditions")
    requirements = source.get("real_evidence_requirements")
    if not isinstance(identity, dict) or identity.get("id") != milestone_id:
        raise CompileError("milestone identity does not match its directory")
    if not isinstance(conditions, list) or not conditions:
        raise CompileError("project milestone must contain success conditions")
    if not isinstance(requirements, list):
        raise CompileError("real_evidence_requirements must be an array")

    suites = _catalog(catalog)
    requirement_by_id = _requirements(requirements, suites)
    compiled_conditions: list[dict[str, Any]] = []
    referenced_evidence: set[str] = set()
    referenced_suites: set[str] = set()
    seen_conditions: set[str] = set()
    for index, raw in enumerate(conditions):
        if not isinstance(raw, dict):
            raise CompileError(f"success_conditions[{index}] must be an object")
        condition_id = raw.get("id")
        suite_ids = raw.get("suite_ids")
        evidence_ids = raw.get("evidence_requirement_ids")
        if not isinstance(condition_id, str) or not condition_id or condition_id in seen_conditions:
            raise CompileError("success condition ids must be nonempty and unique")
        seen_conditions.add(condition_id)
        if raw.get("required") is not True:
            raise CompileError(f"success condition {condition_id} must remain required")
        if not isinstance(suite_ids, list) or any(item not in suites for item in suite_ids):
            raise CompileError(f"success condition {condition_id} references an unknown suite")
        if not isinstance(evidence_ids, list) or any(item not in requirement_by_id for item in evidence_ids):
            raise CompileError(f"success condition {condition_id} references unknown evidence")
        if len(suite_ids) + len(evidence_ids) != 1:
            raise CompileError(
                f"success condition {condition_id} must bind exactly one acceptance source"
            )
        referenced_evidence.update(evidence_ids)
        referenced_suites.update(suite_ids)
        statement = raw.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            raise CompileError(f"success condition {condition_id} needs a statement")
        compiled_conditions.append(
            {
                "id": condition_id,
                "statement": statement,
                "evidence_requirement_ids": [
                    *[f"verification.{suite_id}" for suite_id in suite_ids],
                    *[f"evidence.{evidence_id}" for evidence_id in evidence_ids],
                ],
            }
        )
    unused = set(requirement_by_id) - referenced_evidence
    if unused:
        raise CompileError(f"unused real evidence requirements: {sorted(unused)}")

    termination = policy.get("termination")
    required_limits = {
        "max_iterations",
        "max_stagnant_iterations",
        "max_environment_retries",
        "max_no_plan_rounds",
        "max_wall_seconds",
    }
    if not isinstance(termination, dict) or set(termination) != required_limits:
        raise CompileError("policy termination limits are incomplete")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in termination.values()):
        raise CompileError("policy termination limits must be positive integers")
    freshness = policy.get("evidence_freshness_seconds")
    if isinstance(freshness, bool) or not isinstance(freshness, int) or freshness < 1:
        raise CompileError("policy evidence freshness must be a positive integer")

    verification_requirements = [
        {
            "id": f"verification.{suite_id}",
            "statement": f"The current structured result for suite {suite_id} passes without skips.",
            "kind": "VERIFICATION",
            "source_id": suite_id,
            "freshness_seconds": freshness,
            "provenance_required": True,
            "substitution_policy": "FORBIDDEN",
            "parameters": {
                "suite_id": suite_id,
                "skip_policy": suites[suite_id].get("skip_policy"),
            },
        }
        for suite_id in sorted(referenced_suites)
    ]
    real_requirements = [
        {
            "id": f"evidence.{item['id']}",
            "statement": item["statement"],
            "kind": "REAL",
            "source_id": item["id"],
            "freshness_seconds": freshness,
            "provenance_required": True,
            "substitution_policy": "FORBIDDEN",
            "parameters": {
                **item["parameters"],
                "suite_id": item["suite_id"],
                "promotion_source_id": item.get("promotion_source_id"),
            },
        }
        for item in requirements
    ]

    return {
        "schema_version": "controller-milestone-v1",
        "milestone": {
            "id": identity["id"],
            "title": identity["title"],
            "goal": identity["final_goal"],
        },
        "success_conditions": compiled_conditions,
        "evidence_requirements": [*verification_requirements, *real_requirements],
        "termination": dict(termination),
    }


def _catalog(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = document.get("suites")
    if not isinstance(raw, list):
        raise CompileError("catalog.suites must be an array")
    suites: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise CompileError("catalog suite needs an id")
        if item["id"] in suites:
            raise CompileError(f"duplicate suite id: {item['id']}")
        suites[item["id"]] = item
    return suites


def _requirements(
    raw: list[Any], suites: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise CompileError(f"real_evidence_requirements[{index}] must be an object")
        requirement_id = item.get("id")
        if not isinstance(requirement_id, str) or not requirement_id or requirement_id in values:
            raise CompileError("real evidence ids must be nonempty and unique")
        suite = suites.get(item.get("suite_id"))
        parameters = item.get("parameters")
        if not isinstance(suite, dict) or suite.get("kind") != "real":
            raise CompileError(f"{requirement_id} must reference a real suite")
        if not isinstance(parameters, dict):
            raise CompileError(f"{requirement_id} must declare parameters")
        nodes = parameters.get("nodes")
        if isinstance(nodes, bool) or not isinstance(nodes, int) or nodes < 1:
            raise CompileError(f"{requirement_id} must declare an exact positive node count")
        if (
            item.get("capture_class") != "REAL"
            or item.get("provenance_required") is not True
            or item.get("substitution_policy") != "FORBIDDEN"
        ):
            raise CompileError(f"{requirement_id} weakens real evidence acceptance")
        statement = item.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            raise CompileError(f"{requirement_id} needs a statement")
        values[requirement_id] = item
    for requirement_id, item in values.items():
        source = item.get("promotion_source_id")
        if source is not None and source not in values:
            raise CompileError(f"{requirement_id} references unknown promotion evidence")
        seen: set[str] = set()
        current: str | None = requirement_id
        while current is not None:
            if current in seen:
                raise CompileError(f"real evidence promotion cycle includes {current}")
            seen.add(current)
            source = values[current].get("promotion_source_id")
            current = source if isinstance(source, str) else None
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--milestone", required=True)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = compile_contract(
            args.milestone,
            project_root=args.project_root,
            policy_path=args.policy,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (CompileError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
