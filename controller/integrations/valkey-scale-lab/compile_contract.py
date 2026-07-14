#!/usr/bin/env python3
"""Compile a product milestone into an unsigned CONTROLLER review draft."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Any


INTEGRATION_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = INTEGRATION_ROOT.parents[2]
DEFAULT_PROJECT_ROOT = REPOSITORY_ROOT / "project"
DEFAULT_POLICY_PATH = INTEGRATION_ROOT / "policy.json"


class CompileError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CompileError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CompileError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompileError(f"{path} must contain a JSON object")
    return value


def _catalog_by_id(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if catalog.get("schema_version") != "verification-catalog-v1":
        raise CompileError("unsupported verification catalog")
    rows = catalog.get("suites")
    if not isinstance(rows, list):
        raise CompileError("catalog.suites must be an array")
    suites: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise CompileError("catalog contains a suite without an id")
        if row["id"] in suites:
            raise CompileError(f"duplicate suite id: {row['id']}")
        suites[row["id"]] = row
    return suites


def _selected_test_inputs(
    suite_ids: set[str], suites: dict[str, dict[str, Any]]
) -> list[str]:
    selected: set[str] = set()
    for suite_id in suite_ids:
        for argument in suites[suite_id].get("argv", []):
            if isinstance(argument, str) and (
                argument == "tests" or argument.startswith("tests/")
            ):
                selected.add(f"product/{argument}")
    return sorted(selected)


def _prerequisites(project_root: Path, milestone_id: str, milestone: dict[str, Any]) -> list[str]:
    raw = milestone.get("prerequisite_milestone_ids")
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise CompileError("prerequisite_milestone_ids must be a string array")
    if len(raw) != len(set(raw)):
        raise CompileError("prerequisite milestone ids must be unique")
    if len(raw) > 1:
        raise CompileError("multiple prerequisite promotion sources require an explicit merge policy")

    visited: set[str] = set()

    def visit(current_id: str, stack: tuple[str, ...]) -> None:
        if current_id in stack:
            raise CompileError(f"milestone prerequisite cycle: {(*stack, current_id)}")
        if current_id in visited:
            return
        path = project_root / "milestones" / current_id / "milestone.json"
        document = _load(path)
        identity = document.get("milestone")
        if (
            document.get("schema_version") != "valkey-milestone-v2"
            or not isinstance(identity, dict)
            or identity.get("id") != current_id
        ):
            raise CompileError(f"invalid prerequisite milestone {current_id}")
        dependencies = document.get("prerequisite_milestone_ids")
        if not isinstance(dependencies, list) or any(
            not isinstance(item, str) for item in dependencies
        ):
            raise CompileError(f"invalid prerequisite list on {current_id}")
        for dependency in dependencies:
            visit(dependency, (*stack, current_id))
        visited.add(current_id)

    for prerequisite in raw:
        visit(prerequisite, (milestone_id,))
    return list(raw)


def _scenario_inputs(
    project_root: Path, requirements: list[dict[str, Any]]
) -> list[str]:
    values: set[str] = set()
    for requirement in requirements:
        parameters = requirement.get("parameters")
        definition = parameters.get("definition") if isinstance(parameters, dict) else None
        if definition is None:
            continue
        if not isinstance(definition, str):
            raise CompileError(f"{requirement['id']} scenario definition path is invalid")
        path = PurePosixPath(definition)
        if path.is_absolute() or ".." in path.parts or not (project_root / definition).is_file():
            raise CompileError(f"{requirement['id']} scenario definition is missing or unsafe")
        values.add(f"product/{definition}")
    return sorted(values)


def compile_contract(
    milestone_id: str,
    *,
    project_root: Path = DEFAULT_PROJECT_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    milestone_path = project_root / "milestones" / milestone_id / "milestone.json"
    catalog_path = project_root / "verification" / "catalog.json"
    milestone = _load(milestone_path)
    catalog = _load(catalog_path)
    policy = _load(Path(policy_path).resolve())
    if milestone.get("schema_version") != "valkey-milestone-v2":
        raise CompileError("unsupported project milestone")
    identity = milestone.get("milestone")
    conditions = milestone.get("success_conditions")
    source_requirements = milestone.get("real_evidence_requirements")
    if not isinstance(identity, dict) or identity.get("id") != milestone_id:
        raise CompileError("milestone identity does not match its directory")
    if not isinstance(conditions, list) or not conditions:
        raise CompileError("project milestone needs success conditions")
    if not isinstance(source_requirements, list) or any(
        not isinstance(requirement, dict) for requirement in source_requirements
    ):
        raise CompileError(
            "project milestone real_evidence_requirements must be an object array"
        )
    prerequisites = _prerequisites(project_root, milestone_id, milestone)

    suites = _catalog_by_id(catalog)
    condition_suite_ids: set[str] = set()
    for condition in conditions:
        if not isinstance(condition, dict):
            raise CompileError("success condition must be an object")
        suite_values = condition.get("suite_ids")
        if not isinstance(suite_values, list) or any(
            not isinstance(item, str) for item in suite_values
        ):
            raise CompileError("success condition suite_ids must be a string array")
        condition_suite_ids.update(suite_values)
    requirement_suite_ids = [
        requirement.get("suite_id") for requirement in source_requirements
    ]
    if any(not isinstance(item, str) or not item for item in requirement_suite_ids):
        raise CompileError(
            "real evidence requirements must reference a nonempty suite id"
        )
    all_suite_ids = set(condition_suite_ids)
    all_suite_ids.update(requirement_suite_ids)
    unknown = sorted(item for item in all_suite_ids if item not in suites)
    if unknown:
        raise CompileError(f"milestone references unknown suite ids: {unknown}")

    requirement_ids: set[str] = set()
    for requirement in source_requirements:
        requirement_id = requirement.get("id")
        if (
            not isinstance(requirement_id, str)
            or not requirement_id
            or requirement_id in requirement_ids
        ):
            raise CompileError(
                "real evidence requirement ids must be nonempty and unique"
            )
        requirement_ids.add(requirement_id)
    for requirement in source_requirements:
        source = requirement.get("promotion_source_id")
        if source is not None and source not in requirement_ids:
            raise CompileError(
                f"{requirement['id']} references an unknown promotion source"
            )
        suite = suites.get(requirement.get("suite_id"))
        if not isinstance(suite, dict) or suite.get("kind") != "real":
            raise CompileError(
                f"{requirement['id']} must reference a real verification suite"
            )
        parameters = requirement.get("parameters")
        if not isinstance(parameters, dict):
            raise CompileError(
                f"{requirement['id']} must declare object parameters"
            )
        nodes = parameters.get("nodes")
        if isinstance(nodes, bool) or not isinstance(nodes, int) or nodes < 1:
            raise CompileError(
                f"{requirement['id']} must declare a positive exact node count"
            )
        if (
            requirement.get("capture_class") != "REAL"
            or requirement.get("provenance_required") is not True
            or requirement.get("substitution_policy") != "FORBIDDEN"
            or requirement.get("operator_approval_required") is not True
        ):
            raise CompileError(
                f"{requirement['id']} weakens the real evidence trust contract"
            )

    requirement_by_id = {
        requirement["id"]: requirement for requirement in source_requirements
    }
    for requirement_id in requirement_ids:
        seen: set[str] = set()
        current: str | None = requirement_id
        while current is not None:
            if current in seen:
                raise CompileError(
                    f"real evidence promotion cycle includes {current}"
                )
            seen.add(current)
            source = requirement_by_id[current].get("promotion_source_id")
            current = source if isinstance(source, str) else None
    promotion_sources = {
        source
        for requirement in source_requirements
        if isinstance(source := requirement.get("promotion_source_id"), str)
    }
    terminal_requirements = requirement_ids - promotion_sources
    if source_requirements and len(terminal_requirements) != 1:
        raise CompileError(
            "real evidence promotion chain must have exactly one terminal requirement"
        )
    evidence_requirement_id = {
        requirement_id: f"evidence.{requirement_id}"
        for requirement_id in requirement_ids
    }
    suite_requirement_id = {
        suite_id: f"verification.{suite_id}" for suite_id in condition_suite_ids
    }

    milestone_evaluator_id = "ValkeyMilestoneEvaluator"
    verification_evaluator_id = "ValkeyVerificationAdmissionEvaluator"
    admission_evaluator_id = "ValkeyAdmissionEvaluator"
    controller_conditions: list[dict[str, Any]] = []
    acceptance_source_owners: dict[tuple[str, str], str] = {}
    referenced_real_requirements: set[str] = set()
    for condition in conditions:
        condition_id = condition.get("id")
        evidence_ids = condition.get("evidence_requirement_ids")
        suite_ids = condition.get("suite_ids")
        if (
            not isinstance(condition_id, str)
            or not isinstance(evidence_ids, list)
            or any(item not in requirement_ids for item in evidence_ids)
        ):
            raise CompileError(
                "success condition references an unknown real evidence requirement"
            )
        if condition.get("required") is not True:
            raise CompileError("every product success condition must be required")
        if len(suite_ids) + len(evidence_ids) != 1:
            raise CompileError(
                "every product success condition must bind exactly one acceptance source"
            )
        source = (
            ("suite", suite_ids[0])
            if suite_ids
            else ("real_evidence", evidence_ids[0])
        )
        if source in acceptance_source_owners:
            raise CompileError(
                f"acceptance source {source[1]} is shared by multiple success conditions"
            )
        acceptance_source_owners[source] = condition_id
        referenced_real_requirements.update(evidence_ids)
        controller_conditions.append(
            {
                "id": condition_id,
                "statement": condition["statement"],
                "evaluator_ids": [milestone_evaluator_id],
                "evidence_requirement_ids": [
                    *[suite_requirement_id[item] for item in suite_ids],
                    *[evidence_requirement_id[item] for item in evidence_ids],
                ],
                "required": condition["required"],
            }
        )
    unused_real_requirements = sorted(
        requirement_ids - referenced_real_requirements
    )
    if unused_real_requirements:
        raise CompileError(
            f"unused real evidence requirements: {unused_real_requirements}"
        )

    capabilities = sorted(
        {
            capability
            for suite_id in all_suite_ids
            for capability in suites[suite_id].get("capabilities", [])
        }
    )
    capability_limits = policy.get("capability_limits", {})
    missing_limits = [item for item in capabilities if item not in capability_limits]
    if missing_limits:
        raise CompileError(f"controller policy has no limits for capabilities: {missing_limits}")
    capability_policies = [
        {
            "id": capability,
            "operator_approval_required": True,
            "max_uses": capability_limits[capability]["max_uses"],
            "cost_units_per_use": capability_limits[capability]["cost_units_per_use"],
        }
        for capability in capabilities
    ]

    milestone_input = f"product/milestones/{milestone_id}/milestone.json"
    catalog_input = "product/verification/catalog.json"
    result_schema = "authority/schemas/evaluator_result.schema.json"
    receipt_schema = "authority/schemas/verification_receipts.schema.json"
    candidate_schema = "product/schemas/artifact/evidence_admission_candidate.schema.json"
    policy_input = "authority/verification_policy.json"
    producer_input = "authority/tools/run_verification.py"
    prerequisite_schema = "authority/schemas/prerequisite_completion.schema.json"
    prerequisite_inputs = [
        path
        for prerequisite in prerequisites
        for path in (
            f"authority/prerequisites/{prerequisite}/completion.json",
            f"authority/prerequisites/{prerequisite}/terminal.json",
        )
    ]
    prerequisite_args = [
        value
        for prerequisite in prerequisites
        for value in (
            "--prerequisite",
            f"authority/prerequisites/{prerequisite}/completion.json",
        )
    ]
    selected_tests = _selected_test_inputs(condition_suite_ids, suites)
    scenario_inputs = _scenario_inputs(project_root, source_requirements)
    timeout = int(policy["evaluator_timeout_seconds"])

    evaluators = [
        {
            "id": milestone_evaluator_id,
            "mode": "milestone",
            "authority": "independent_evaluator",
            "trust_mode": "sealed_local",
            "argv": [
                "python3",
                "authority/evaluators/milestone_evaluator.py",
                "--milestone",
                milestone_input,
                "--catalog",
                catalog_input,
                *prerequisite_args,
            ],
            "cwd": ".",
            "timeout_seconds": timeout,
            "inputs": [
                "authority/evaluators/milestone_evaluator.py",
                "authority/evaluators/_common.py",
                "authority/evaluators/_prerequisite.py",
                result_schema,
                prerequisite_schema,
                milestone_input,
                catalog_input,
                *prerequisite_inputs,
                *selected_tests,
            ],
            "output_schema": result_schema,
            "cost": "normal",
            "cost_units": 2,
            "capabilities": [],
        },
        {
            "id": verification_evaluator_id,
            "mode": "admission",
            "authority": "independent_evaluator",
            "trust_mode": "sealed_local",
            "argv": [
                "python3",
                "authority/evaluators/verification_admission.py",
                "--milestone",
                milestone_input,
                "--catalog",
                catalog_input,
                "--receipts-schema",
                receipt_schema,
                "--verification-policy",
                policy_input,
                "--verification-policy-schema",
                "authority/schemas/verification_policy.schema.json",
                "--producer",
                producer_input,
            ],
            "cwd": ".",
            "timeout_seconds": timeout,
            "inputs": [
                "authority/evaluators/verification_admission.py",
                "authority/evaluators/_common.py",
                "authority/evaluators/_schema.py",
                result_schema,
                receipt_schema,
                "authority/schemas/verification_policy.schema.json",
                milestone_input,
                catalog_input,
                "product/verification/suite-result.schema.json",
                policy_input,
                producer_input,
                *selected_tests,
            ],
            "output_schema": result_schema,
            "cost": "normal",
            "cost_units": 2,
            "capabilities": [],
        },
    ]
    if source_requirements:
        evaluators.append(
            {
                "id": admission_evaluator_id,
                "mode": "admission",
                "authority": "independent_evaluator",
                "trust_mode": "sealed_local",
                "argv": [
                    "python3",
                    "authority/evaluators/evidence_admission.py",
                    "--milestone",
                    milestone_input,
                    "--product-root",
                    "product",
                    "--candidate-schema",
                    candidate_schema,
                    *prerequisite_args,
                ],
                "cwd": ".",
                "timeout_seconds": timeout,
                "inputs": [
                    "authority/evaluators/evidence_admission.py",
                    "authority/evaluators/_common.py",
                    "authority/evaluators/_schema.py",
                    "authority/evaluators/_evidence_contract.py",
                    "authority/evaluators/_prerequisite.py",
                    result_schema,
                    prerequisite_schema,
                    candidate_schema,
                    milestone_input,
                    *scenario_inputs,
                    *prerequisite_inputs,
                ],
                "output_schema": result_schema,
                "cost": "normal",
                "cost_units": 2,
                "capabilities": [],
            }
        )

    verification_requirements = [
        {
            "id": suite_requirement_id[suite_id],
            "statement": f"Admit a fresh operator-produced receipt for capability suite {suite_id}.",
            "capture_class": "OTHER",
            "provenance_required": True,
            "freshness": {
                "max_age_seconds": policy["evidence_freshness_seconds"],
                "bind_to_product_digest": True,
                "bind_to_run_id": True,
            },
            "substitution_policy": "FORBIDDEN",
            "admission_evaluator_ids": [verification_evaluator_id],
        }
        for suite_id in sorted(condition_suite_ids)
    ]
    controller_real_requirements = [
        {
            "id": evidence_requirement_id[requirement["id"]],
            "statement": requirement["statement"],
            "capture_class": "REAL",
            "provenance_required": requirement["provenance_required"],
            "freshness": {
                "max_age_seconds": policy["evidence_freshness_seconds"],
                "bind_to_product_digest": True,
                "bind_to_run_id": True,
            },
            "substitution_policy": requirement["substitution_policy"],
            "admission_evaluator_ids": [admission_evaluator_id],
        }
        for requirement in source_requirements
    ]
    return {
        "schema_version": "controller-milestone-v2",
        "milestone": {
            "id": f"ValkeyScaleLab.{milestone_id}",
            "version": identity["version"],
            "title": identity["title"],
            "final_goal": identity["final_goal"],
        },
        "success_conditions": controller_conditions,
        "evaluators": evaluators,
        "evidence_requirements": [
            *verification_requirements,
            *controller_real_requirements,
        ],
        "safety": {
            "product_roots": ["product"],
            "context_roots": ["product"],
            "mutable_roots": [
                "product/src",
                "product/scripts",
                "product/schemas",
                "product/config",
                "product/templates",
            ],
            "immutable_roots": [
                "product/milestones",
                "product/verification",
                "product/tests",
                "authority",
            ],
            "evaluator_roots": ["authority/evaluators"],
            "authority_roots": ["authority"],
            "evidence_roots": ["run_evidence"],
            "allowed_tools": ["python3"],
            "capability_policies": capability_policies,
            "forbidden_effects": [
                "ModifyAcceptanceAuthority",
                "ModifyControllerState",
                "UseFixtureAsRealEvidence",
                "DownscaleExactRun",
            ],
        },
        "resource_budget": policy["resource_budget"],
        "termination": policy["termination"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--milestone", required=True, choices=("m1", "m2", "m3"))
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    draft = compile_contract(
        args.milestone,
        project_root=args.project_root,
        policy_path=args.policy,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(draft, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote unsigned operator-review draft: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
