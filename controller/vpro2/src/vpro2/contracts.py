from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .models import (
    CapabilityPolicyDefinition,
    EvidenceFreshnessDefinition,
    EvidenceRequirementDefinition,
    EvaluatorDefinition,
    MilestoneContract,
    MilestoneIdentity,
    ResourceBudgetDefinition,
    SafetyDefinition,
    SuccessConditionDefinition,
    TerminationDefinition,
)


SCHEMA_VERSION = "vpro-milestone-v2"
FORBIDDEN_CONTROL_FIELDS = frozenset(
    {"objectives", "depends_on", "profiles", "gates", "order"}
)
ID_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", re.ASCII)
SEMVER_PATTERN = re.compile(
    r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", re.ASCII
)
SAFE_PATH_PATTERN = re.compile(
    r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", re.ASCII
)
TOOL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}", re.ASCII)
EVALUATOR_MODES = frozenset({"milestone", "admission"})
EVALUATOR_AUTHORITY = "independent_evaluator"
TRUST_MODES = frozenset({"sealed_local"})
COST_CLASSES = frozenset({"cheap", "normal", "expensive"})
CAPTURE_CLASSES = frozenset({"REAL", "OTHER"})
BANNED_TOOLS = frozenset(
    {
        "bash",
        "cmd",
        "csh",
        "env",
        "fish",
        "ksh",
        "powershell",
        "pwsh",
        "sh",
        "sudo",
        "tcsh",
        "xargs",
        "zsh",
    }
)
SHELL_TOKENS = frozenset({"|", "||", "&&", ";", ">", ">>", "<", "<<"})


class ContractError(ValueError):
    pass


def load_contract(path: Path, *, project_root: Path) -> MilestoneContract:
    project_root = Path(project_root).resolve()
    path = Path(path).absolute()
    current = path
    while True:
        # Root-owned platform aliases such as macOS /var -> /private/var are
        # part of the host trust boundary. User-controlled traversal is not.
        if current.is_symlink() and current.lstat().st_uid != 0:
            raise ContractError(f"milestone path traverses symlink {current}")
        if current == current.parent:
            break
        current = current.parent
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load VPRO2 milestone {path}: {exc}") from exc
    return parse_contract(raw, project_root=project_root, contract_path=path.resolve())


def load_milestone(path: Path, *, project_root: Path) -> MilestoneContract:
    """Explicit alias for callers that use the external artifact's name."""

    return load_contract(path, project_root=project_root)


def parse_contract(
    raw: Any,
    *,
    project_root: Path,
    contract_path: Path | None = None,
) -> MilestoneContract:
    project_root = Path(project_root).resolve()
    _object(raw, "milestone contract")
    _reject_forbidden_control_fields(raw)
    _keys(
        raw,
        required={
            "schema_version",
            "milestone",
            "success_conditions",
            "evaluators",
            "evidence_requirements",
            "safety",
            "resource_budget",
            "termination",
        },
        location="milestone contract",
    )
    if raw["schema_version"] != SCHEMA_VERSION:
        raise ContractError(
            f"milestone contract.schema_version must be {SCHEMA_VERSION!r}"
        )

    milestone = _parse_milestone(raw["milestone"])
    conditions = _parse_success_conditions(raw["success_conditions"])
    evaluators = _parse_evaluators(raw["evaluators"], project_root)
    evidence = _parse_evidence_requirements(raw["evidence_requirements"])
    safety = _parse_safety(raw["safety"], project_root)
    budget = _parse_budget(raw["resource_budget"])
    termination = _parse_termination(raw["termination"])
    contract = MilestoneContract(
        schema_version=SCHEMA_VERSION,
        milestone=milestone,
        success_conditions=conditions,
        evaluators=evaluators,
        evidence_requirements=evidence,
        safety=safety,
        resource_budget=budget,
        termination=termination,
    )
    _validate_contract(contract, project_root, contract_path)
    return contract


def _parse_milestone(raw: Any) -> MilestoneIdentity:
    location = "milestone contract.milestone"
    _object(raw, location)
    _keys(raw, required={"id", "version", "title", "final_goal"}, location=location)
    version = raw["version"]
    if not isinstance(version, str) or SEMVER_PATTERN.fullmatch(version) is None:
        raise ContractError(f"{location}.version must be semantic version text")
    return MilestoneIdentity(
        id=_id(raw["id"], f"{location}.id"),
        version=version,
        title=_text(raw["title"], f"{location}.title"),
        final_goal=_text(raw["final_goal"], f"{location}.final_goal"),
    )


def _parse_success_conditions(raw: Any) -> tuple[SuccessConditionDefinition, ...]:
    values: list[SuccessConditionDefinition] = []
    required = {
        "id",
        "statement",
        "evaluator_ids",
        "evidence_requirement_ids",
        "required",
    }
    for index, item in enumerate(
        _nonempty_list(raw, "milestone contract.success_conditions")
    ):
        location = f"milestone contract.success_conditions[{index}]"
        _object(item, location)
        _keys(item, required=required, location=location)
        is_required = _boolean(item["required"], f"{location}.required")
        if not is_required:
            raise ContractError(f"{location}.required must be true in a final-goal contract")
        values.append(
            SuccessConditionDefinition(
                id=_id(item["id"], f"{location}.id"),
                statement=_text(item["statement"], f"{location}.statement"),
                evaluator_ids=_ids(
                    item["evaluator_ids"], f"{location}.evaluator_ids", nonempty=True
                ),
                evidence_requirement_ids=_ids(
                    item["evidence_requirement_ids"],
                    f"{location}.evidence_requirement_ids",
                    nonempty=False,
                ),
                required=True,
            )
        )
    _unique_ids(values, "success condition")
    return tuple(values)


def _parse_evaluators(raw: Any, project_root: Path) -> tuple[EvaluatorDefinition, ...]:
    values: list[EvaluatorDefinition] = []
    required = {
        "id",
        "mode",
        "authority",
        "trust_mode",
        "argv",
        "cwd",
        "timeout_seconds",
        "inputs",
        "output_schema",
        "cost",
        "cost_units",
        "capabilities",
    }
    for index, item in enumerate(_nonempty_list(raw, "milestone contract.evaluators")):
        location = f"milestone contract.evaluators[{index}]"
        _object(item, location)
        _keys(item, required=required, location=location)
        mode = item["mode"]
        if mode not in EVALUATOR_MODES:
            raise ContractError(f"{location}.mode must be one of {sorted(EVALUATOR_MODES)}")
        authority = item["authority"]
        if authority != EVALUATOR_AUTHORITY:
            raise ContractError(
                f"{location}.authority must be {EVALUATOR_AUTHORITY!r}; worker or controller verdicts are forbidden"
            )
        trust_mode = item["trust_mode"]
        if trust_mode not in TRUST_MODES:
            raise ContractError(
                f"{location}.trust_mode must be one of {sorted(TRUST_MODES)}"
            )
        argv = _strings(item["argv"], f"{location}.argv", nonempty=True)
        cwd = _cwd(item["cwd"], f"{location}.cwd", project_root)
        inputs = _paths(item["inputs"], f"{location}.inputs", project_root, nonempty=True)
        output_schema = _path(
            item["output_schema"], f"{location}.output_schema", project_root
        )
        cost = item["cost"]
        if cost not in COST_CLASSES:
            raise ContractError(f"{location}.cost must be one of {sorted(COST_CLASSES)}")
        capabilities = _ids(
            item["capabilities"], f"{location}.capabilities", nonempty=False
        )
        if capabilities:
            raise ContractError(
                f"{location}.capabilities must be empty; acceptance evaluators are read-only and unprivileged"
            )
        values.append(
            EvaluatorDefinition(
                id=_id(item["id"], f"{location}.id"),
                mode=mode,
                authority=authority,
                trust_mode=trust_mode,
                argv=argv,
                cwd=cwd,
                timeout_seconds=_positive_int(
                    item["timeout_seconds"], f"{location}.timeout_seconds"
                ),
                inputs=inputs,
                output_schema=output_schema,
                cost=cost,
                cost_units=_positive_int(item["cost_units"], f"{location}.cost_units"),
                capabilities=(),
            )
        )
    _unique_ids(values, "evaluator")
    return tuple(values)


def _parse_evidence_requirements(
    raw: Any,
) -> tuple[EvidenceRequirementDefinition, ...]:
    if not isinstance(raw, list):
        raise ContractError("milestone contract.evidence_requirements must be an array")
    values: list[EvidenceRequirementDefinition] = []
    required = {
        "id",
        "statement",
        "capture_class",
        "provenance_required",
        "freshness",
        "substitution_policy",
        "admission_evaluator_ids",
    }
    for index, item in enumerate(raw):
        location = f"milestone contract.evidence_requirements[{index}]"
        _object(item, location)
        _keys(item, required=required, location=location)
        capture_class = item["capture_class"]
        if capture_class not in CAPTURE_CLASSES:
            raise ContractError(
                f"{location}.capture_class must be one of {sorted(CAPTURE_CLASSES)}"
            )
        provenance_required = _boolean(
            item["provenance_required"], f"{location}.provenance_required"
        )
        freshness_location = f"{location}.freshness"
        freshness = item["freshness"]
        _object(freshness, freshness_location)
        _keys(
            freshness,
            required={"max_age_seconds", "bind_to_product_digest", "bind_to_run_id"},
            location=freshness_location,
        )
        parsed_freshness = EvidenceFreshnessDefinition(
            max_age_seconds=_positive_int(
                freshness["max_age_seconds"], f"{freshness_location}.max_age_seconds"
            ),
            bind_to_product_digest=_boolean(
                freshness["bind_to_product_digest"],
                f"{freshness_location}.bind_to_product_digest",
            ),
            bind_to_run_id=_boolean(
                freshness["bind_to_run_id"], f"{freshness_location}.bind_to_run_id"
            ),
        )
        substitution_policy = item["substitution_policy"]
        if substitution_policy != "FORBIDDEN":
            raise ContractError(f"{location}.substitution_policy must be 'FORBIDDEN'")
        if capture_class == "REAL" and (
            not provenance_required
            or not parsed_freshness.bind_to_product_digest
            or not parsed_freshness.bind_to_run_id
        ):
            raise ContractError(
                f"{location}: REAL evidence requires provenance and product/run binding"
            )
        values.append(
            EvidenceRequirementDefinition(
                id=_id(item["id"], f"{location}.id"),
                statement=_text(item["statement"], f"{location}.statement"),
                capture_class=capture_class,
                provenance_required=provenance_required,
                freshness=parsed_freshness,
                substitution_policy="FORBIDDEN",
                admission_evaluator_ids=_ids(
                    item["admission_evaluator_ids"],
                    f"{location}.admission_evaluator_ids",
                    nonempty=True,
                ),
            )
        )
    _unique_ids(values, "evidence requirement")
    return tuple(values)


def _parse_safety(raw: Any, project_root: Path) -> SafetyDefinition:
    location = "milestone contract.safety"
    _object(raw, location)
    _keys(
        raw,
        required={
            "product_roots",
            "context_roots",
            "mutable_roots",
            "immutable_roots",
            "evaluator_roots",
            "authority_roots",
            "evidence_roots",
            "allowed_tools",
            "capability_policies",
            "forbidden_effects",
        },
        location=location,
    )
    policies: list[CapabilityPolicyDefinition] = []
    for index, item in enumerate(
        _array(
            raw["capability_policies"],
            f"{location}.capability_policies",
            nonempty=False,
        )
    ):
        item_location = f"{location}.capability_policies[{index}]"
        _object(item, item_location)
        _keys(
            item,
            required={
                "id",
                "operator_approval_required",
                "max_uses",
                "cost_units_per_use",
            },
            location=item_location,
        )
        approval = _boolean(
            item["operator_approval_required"],
            f"{item_location}.operator_approval_required",
        )
        if not approval:
            raise ContractError(
                f"{item_location}.operator_approval_required must be true"
            )
        policies.append(
            CapabilityPolicyDefinition(
                id=_id(item["id"], f"{item_location}.id"),
                operator_approval_required=True,
                max_uses=_positive_int(item["max_uses"], f"{item_location}.max_uses"),
                cost_units_per_use=_positive_int(
                    item["cost_units_per_use"],
                    f"{item_location}.cost_units_per_use",
                ),
            )
        )
    _unique_ids(policies, "capability policy")
    allowed_tools = _ids(raw["allowed_tools"], f"{location}.allowed_tools", nonempty=True)
    for tool in allowed_tools:
        if TOOL_PATTERN.fullmatch(tool) is None or tool in BANNED_TOOLS:
            raise ContractError(f"{location}.allowed_tools contains unsafe tool {tool!r}")
    return SafetyDefinition(
        product_roots=_paths(
            raw["product_roots"], f"{location}.product_roots", project_root, nonempty=True
        ),
        context_roots=_paths(
            raw["context_roots"], f"{location}.context_roots", project_root, nonempty=True
        ),
        mutable_roots=_paths(
            raw["mutable_roots"], f"{location}.mutable_roots", project_root, nonempty=True
        ),
        immutable_roots=_paths(
            raw["immutable_roots"], f"{location}.immutable_roots", project_root, nonempty=True
        ),
        evaluator_roots=_paths(
            raw["evaluator_roots"], f"{location}.evaluator_roots", project_root, nonempty=True
        ),
        authority_roots=_paths(
            raw["authority_roots"], f"{location}.authority_roots", project_root, nonempty=True
        ),
        evidence_roots=_paths(
            raw["evidence_roots"], f"{location}.evidence_roots", project_root, nonempty=True
        ),
        allowed_tools=allowed_tools,
        capability_policies=tuple(policies),
        forbidden_effects=_ids(
            raw["forbidden_effects"], f"{location}.forbidden_effects", nonempty=True
        ),
    )


def _parse_budget(raw: Any) -> ResourceBudgetDefinition:
    location = "milestone contract.resource_budget"
    _object(raw, location)
    positive = {
        "max_iterations",
        "max_objective_attempts",
        "max_planning_rounds_per_iteration",
        "max_wall_seconds",
        "max_worker_seconds",
        "max_evaluator_seconds",
        "max_cost_units",
        "max_context_bytes",
        "max_write_bytes",
        "max_evidence_bytes",
        "max_transaction_bytes",
    }
    nonnegative = {
        "max_capability_runs",
        "max_operator_runs",
        "max_diagnostic_iterations",
    }
    _keys(raw, required=positive | nonnegative, location=location)
    values = {
        key: _positive_int(raw[key], f"{location}.{key}") for key in positive
    }
    values.update(
        {key: _nonnegative_int(raw[key], f"{location}.{key}") for key in nonnegative}
    )
    if values["max_objective_attempts"] < values["max_iterations"]:
        raise ContractError(
            f"{location}.max_objective_attempts must cover max_iterations"
        )
    if values["max_diagnostic_iterations"] > values["max_iterations"]:
        raise ContractError(
            f"{location}.max_diagnostic_iterations must not exceed max_iterations"
        )
    return ResourceBudgetDefinition(**values)


def _parse_termination(raw: Any) -> TerminationDefinition:
    location = "milestone contract.termination"
    _object(raw, location)
    _keys(
        raw,
        required={
            "max_consecutive_no_material_progress",
            "max_consecutive_environment_blocked",
            "max_no_legal_plan_rounds",
            "integrity_anomaly",
            "budget_exhaustion",
            "operator_abort",
        },
        location=location,
    )
    if raw["integrity_anomaly"] != "FAIL_IMMEDIATE":
        raise ContractError(f"{location}.integrity_anomaly must be 'FAIL_IMMEDIATE'")
    for key in ("budget_exhaustion", "operator_abort"):
        if raw[key] != "FAIL":
            raise ContractError(f"{location}.{key} must be 'FAIL'")
    return TerminationDefinition(
        max_consecutive_no_material_progress=_positive_int(
            raw["max_consecutive_no_material_progress"],
            f"{location}.max_consecutive_no_material_progress",
        ),
        max_consecutive_environment_blocked=_positive_int(
            raw["max_consecutive_environment_blocked"],
            f"{location}.max_consecutive_environment_blocked",
        ),
        max_no_legal_plan_rounds=_positive_int(
            raw["max_no_legal_plan_rounds"],
            f"{location}.max_no_legal_plan_rounds",
        ),
        integrity_anomaly="FAIL_IMMEDIATE",
        budget_exhaustion="FAIL",
        operator_abort="FAIL",
    )


def _validate_contract(
    contract: MilestoneContract,
    project_root: Path,
    contract_path: Path | None,
) -> None:
    evaluator_by_id = {item.id: item for item in contract.evaluators}
    evidence_by_id = {item.id: item for item in contract.evidence_requirements}
    global_ids = [
        *(item.id for item in contract.success_conditions),
        *(item.id for item in contract.evaluators),
        *(item.id for item in contract.evidence_requirements),
        *(item.id for item in contract.safety.capability_policies),
    ]
    if len(global_ids) != len(set(global_ids)):
        raise ContractError("condition, evaluator, evidence, and capability IDs must be globally unique")

    used_evaluators: set[str] = set()
    used_evidence: set[str] = set()
    for condition in contract.success_conditions:
        unknown_evaluators = set(condition.evaluator_ids) - set(evaluator_by_id)
        if unknown_evaluators:
            raise ContractError(
                f"condition {condition.id!r} references unknown evaluators {sorted(unknown_evaluators)}"
            )
        unknown_evidence = set(condition.evidence_requirement_ids) - set(evidence_by_id)
        if unknown_evidence:
            raise ContractError(
                f"condition {condition.id!r} references unknown evidence requirements {sorted(unknown_evidence)}"
            )
        used_evaluators.update(condition.evaluator_ids)
        used_evidence.update(condition.evidence_requirement_ids)
    for requirement in contract.evidence_requirements:
        unknown = set(requirement.admission_evaluator_ids) - set(evaluator_by_id)
        if unknown:
            raise ContractError(
                f"evidence requirement {requirement.id!r} references unknown admission evaluators {sorted(unknown)}"
            )
        for evaluator_id in requirement.admission_evaluator_ids:
            if evaluator_by_id[evaluator_id].mode != "admission":
                raise ContractError(
                    f"evidence requirement {requirement.id!r} evaluator {evaluator_id!r} must use admission mode"
                )
        used_evaluators.update(requirement.admission_evaluator_ids)
    unused_evaluators = set(evaluator_by_id) - used_evaluators
    if unused_evaluators:
        raise ContractError(f"unused evaluators are forbidden: {sorted(unused_evaluators)}")
    unused_evidence = set(evidence_by_id) - used_evidence
    if unused_evidence:
        raise ContractError(f"unused evidence requirements are forbidden: {sorted(unused_evidence)}")

    safety = contract.safety
    for mutable in safety.mutable_roots:
        if not _covered(mutable, safety.product_roots):
            raise ContractError(f"mutable root {mutable!r} is outside product_roots")
        if not _covered(mutable, safety.context_roots):
            raise ContractError(f"mutable root {mutable!r} is outside context_roots")
    for context in safety.context_roots:
        if not _covered(context, safety.product_roots):
            raise ContractError(f"context root {context!r} is outside product_roots")
    overlap = _overlaps(safety.mutable_roots, safety.immutable_roots)
    if overlap is not None:
        raise ContractError(f"mutable and immutable roots overlap: {overlap}")
    overlap = _overlaps(safety.mutable_roots, safety.evidence_roots)
    if overlap is not None:
        raise ContractError(f"mutable and evidence roots overlap: {overlap}")
    for root in (*safety.evaluator_roots, *safety.authority_roots):
        if not _covered(root, safety.immutable_roots):
            raise ContractError(f"evaluator/authority root {root!r} is not immutable")

    for evaluator in contract.evaluators:
        if evaluator.argv[0] not in safety.allowed_tools:
            raise ContractError(
                f"evaluator {evaluator.id!r} tool {evaluator.argv[0]!r} is not allowed"
            )
        _validate_argv(evaluator.argv, evaluator.cwd, project_root, evaluator.id)
        adapter = _argv_project_path(evaluator.cwd, evaluator.argv[1])
        if adapter not in evaluator.inputs:
            raise ContractError(
                f"evaluator {evaluator.id!r} adapter must be declared in inputs"
            )
        if not _covered(adapter, (*safety.evaluator_roots, *safety.authority_roots)):
            raise ContractError(
                f"evaluator {evaluator.id!r} adapter is outside sealed evaluator/authority roots"
            )
        if evaluator.output_schema not in evaluator.inputs:
            raise ContractError(
                f"evaluator {evaluator.id!r} output_schema must be declared in inputs"
            )
        if not _covered(
            evaluator.output_schema, (*safety.evaluator_roots, *safety.authority_roots)
        ):
            raise ContractError(
                f"evaluator {evaluator.id!r} output_schema is outside sealed authority roots"
            )
        allowed_inputs = (
            *safety.product_roots,
            *safety.evaluator_roots,
            *safety.authority_roots,
        )
        for input_path in evaluator.inputs:
            if not _covered(input_path, allowed_inputs):
                raise ContractError(
                    f"evaluator {evaluator.id!r} input {input_path!r} is outside declared authority/product roots"
                )
        if evaluator.timeout_seconds > contract.resource_budget.max_evaluator_seconds:
            raise ContractError(
                f"evaluator {evaluator.id!r} timeout exceeds evaluator budget"
            )
        if evaluator.cost_units > contract.resource_budget.max_cost_units:
            raise ContractError(f"evaluator {evaluator.id!r} cost exceeds total budget")

    if sum(item.timeout_seconds for item in contract.evaluators) > contract.resource_budget.max_evaluator_seconds:
        raise ContractError("one complete Milestone evaluation exceeds the evaluator time budget")
    if sum(item.timeout_seconds for item in contract.evaluators) > contract.resource_budget.max_wall_seconds:
        raise ContractError("one complete Milestone evaluation exceeds the run wall-clock budget")
    if sum(item.cost_units for item in contract.evaluators) > contract.resource_budget.max_cost_units:
        raise ContractError("one complete Milestone evaluation exceeds the cost budget")

    total_capability_uses = sum(
        policy.max_uses for policy in safety.capability_policies
    )
    if total_capability_uses > contract.resource_budget.max_capability_runs:
        raise ContractError(
            "capability policy max_uses exceed resource_budget.max_capability_runs"
        )
    if total_capability_uses > contract.resource_budget.max_operator_runs:
        raise ContractError(
            "capability policy max_uses exceed resource_budget.max_operator_runs"
        )

    limits = contract.termination
    if limits.max_consecutive_no_material_progress > contract.resource_budget.max_iterations:
        raise ContractError("stagnation threshold exceeds max_iterations")
    if limits.max_consecutive_environment_blocked > contract.resource_budget.max_iterations:
        raise ContractError("environment-blocked threshold exceeds max_iterations")
    if (
        limits.max_no_legal_plan_rounds
        > contract.resource_budget.max_planning_rounds_per_iteration
    ):
        raise ContractError("no-legal-plan threshold exceeds planning rounds per iteration")

    if contract_path is not None:
        try:
            contract_path.relative_to(project_root)
        except ValueError:
            return
        else:
            raise ContractError("milestone contract must be external to the product project root")


def _validate_argv(
    argv: tuple[str, ...], cwd: str, project_root: Path, evaluator_id: str
) -> None:
    if len(argv) < 2:
        raise ContractError(
            f"evaluator {evaluator_id!r} argv requires a sealed adapter after the tool"
        )
    if argv[0] in BANNED_TOOLS or TOOL_PATTERN.fullmatch(argv[0]) is None:
        raise ContractError(f"evaluator {evaluator_id!r} uses unsafe tool {argv[0]!r}")
    for argument in argv:
        if argument in SHELL_TOKENS or "\x00" in argument or "\n" in argument:
            raise ContractError(f"evaluator {evaluator_id!r} argv contains shell/control token")
    adapter = argv[1]
    if adapter.startswith("-"):
        raise ContractError(f"evaluator {evaluator_id!r} argv[1] must be a sealed adapter")
    _argv_project_path(cwd, adapter)


def _reject_forbidden_control_fields(value: Any, location: str = "milestone contract") -> None:
    if isinstance(value, dict):
        forbidden = set(value) & FORBIDDEN_CONTROL_FIELDS
        if forbidden:
            names = ", ".join(sorted(forbidden))
            raise ContractError(
                f"{location} contains forbidden preplanned control field(s): {names}"
            )
        for key, nested in value.items():
            _reject_forbidden_control_fields(nested, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_forbidden_control_fields(nested, f"{location}[{index}]")


def _object(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{location} must be an object")
    return value


def _keys(value: Mapping[str, Any], *, required: set[str], location: str) -> None:
    missing = required - set(value)
    extra = set(value) - required
    if missing:
        raise ContractError(f"{location} is missing fields {sorted(missing)}")
    if extra:
        raise ContractError(f"{location} has unknown fields {sorted(extra)}")


def _text(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{location} must be nonempty text")
    return value


def _id(value: Any, location: str) -> str:
    if not isinstance(value, str) or ID_PATTERN.fullmatch(value) is None:
        raise ContractError(f"{location} must be a safe identifier")
    return value


def _boolean(value: Any, location: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{location} must be a boolean")
    return value


def _positive_int(value: Any, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{location} must be a positive integer")
    return value


def _nonnegative_int(value: Any, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{location} must be a nonnegative integer")
    return value


def _nonempty_list(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{location} must be a nonempty array")
    return value


def _strings(value: Any, location: str, *, nonempty: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or (nonempty and not value):
        qualifier = "nonempty " if nonempty else ""
        raise ContractError(f"{location} must be a {qualifier}array")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ContractError(f"{location}[{index}] must be nonempty text")
        result.append(item)
    return tuple(result)


def _ids(value: Any, location: str, *, nonempty: bool) -> tuple[str, ...]:
    return tuple(
        _id(item, f"{location}[{index}]")
        for index, item in enumerate(_array(value, location, nonempty=nonempty))
    )


def _array(value: Any, location: str, *, nonempty: bool) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        qualifier = "nonempty " if nonempty else ""
        raise ContractError(f"{location} must be a {qualifier}array")
    if len(value) != len({_json_identity(item) for item in value}):
        raise ContractError(f"{location} must contain unique values")
    return value


def _json_identity(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _path(value: Any, location: str, project_root: Path) -> str:
    if not isinstance(value, str) or SAFE_PATH_PATTERN.fullmatch(value) is None:
        raise ContractError(f"{location} must be a safe project-relative path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ContractError(f"{location} must be a safe project-relative path")
    target = (project_root / pure.as_posix()).resolve()
    try:
        target.relative_to(project_root)
    except ValueError as exc:
        raise ContractError(f"{location} escapes the project root") from exc
    return pure.as_posix()


def _paths(
    value: Any,
    location: str,
    project_root: Path,
    *,
    nonempty: bool,
) -> tuple[str, ...]:
    paths = tuple(
        _path(item, f"{location}[{index}]", project_root)
        for index, item in enumerate(_array(value, location, nonempty=nonempty))
    )
    if len(paths) != len(set(paths)):
        raise ContractError(f"{location} must contain unique paths")
    return paths


def _cwd(value: Any, location: str, project_root: Path) -> str:
    if value == ".":
        return "."
    return _path(value, location, project_root)


def _argv_project_path(cwd: str, argument: str) -> str:
    if not isinstance(argument, str) or SAFE_PATH_PATTERN.fullmatch(argument) is None:
        raise ContractError("evaluator adapter must be a safe project-relative path")
    joined = PurePosixPath(argument) if cwd == "." else PurePosixPath(cwd) / argument
    if any(part in {"", ".", ".."} for part in joined.parts):
        raise ContractError("evaluator adapter path escapes its working directory")
    return joined.as_posix()


def _unique_ids(values: Sequence[Any], label: str) -> None:
    ids = [value.id for value in values]
    if len(ids) != len(set(ids)):
        raise ContractError(f"duplicate {label} IDs are forbidden")


def _covered(path: str, roots: Iterable[str]) -> bool:
    return any(path == root or path.startswith(root + "/") for root in roots)


def _overlaps(left: Iterable[str], right: Iterable[str]) -> str | None:
    for left_path in left:
        for right_path in right:
            if _covered(left_path, (right_path,)) or _covered(right_path, (left_path,)):
                return f"{left_path!r} and {right_path!r}"
    return None
