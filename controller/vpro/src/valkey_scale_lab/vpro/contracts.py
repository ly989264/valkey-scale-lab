from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .models import (
    AcceptanceDefinition,
    BudgetDefinition,
    BundleDefinition,
    CheckDefinition,
    ClauseDefinition,
    GateDefinition,
    IntegrityDefinition,
    MilestoneDefinition,
    ObjectiveDefinition,
    ProfileDefinition,
    TierDefinition,
)


SCHEMA_VERSION = "vpro-bundle-v1"
MILESTONE_COMPLETE = "MILESTONE_COMPLETE"
ID_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", re.ASCII)
TOOL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}", re.ASCII)
CHECK_MODES = frozenset({"standard", "capture", "admission"})
CHECK_AUTHORITIES = frozenset({"bundle", "evaluator"})
CHECK_CACHE_POLICIES = frozenset({"by_input_digest", "never"})
TIER_COSTS = frozenset({"cheap", "normal", "expensive", "operator"})
PROFILE_CLAIMS = frozenset({MILESTONE_COMPLETE, "PROFILE_COMPLETE"})
GATE_KINDS = frozenset({"program", "evidence"})
OBJECTIVE_RULE = "CURRENT_PROGRAM_PASS_AND_BOUNDED_REVIEW"
MILESTONE_RULE = "ALL_SELECTED_REQUIRED_OBJECTIVES_GATES_AND_CLOSURE_CURRENT"
SEMVER_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", re.ASCII)
SAFE_PATH_PATTERN = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", re.ASCII)
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


def load_bundle(path: Path, *, project_root: Path) -> BundleDefinition:
    project_root = Path(project_root).resolve()
    path = Path(path).absolute()
    current = path
    while True:
        if current.is_symlink():
            raise ContractError(f"bundle path traverses symlink {current}")
        if current == current.parent:
            break
        current = current.parent
    path = path.resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load VPRO bundle {path}: {exc}") from exc
    return parse_bundle(raw, project_root=project_root, bundle_path=path)


def parse_bundle(
    raw: Any,
    *,
    project_root: Path,
    bundle_path: Path | None = None,
) -> BundleDefinition:
    project_root = Path(project_root).resolve()
    _object(raw, "bundle")
    _keys(
        raw,
        required={
            "schema_version",
            "milestone",
            "clauses",
            "tiers",
            "checks",
            "objectives",
            "profiles",
            "gates",
            "acceptance",
            "integrity",
        },
        location="bundle",
    )
    if raw["schema_version"] != SCHEMA_VERSION:
        raise ContractError(f"bundle.schema_version must be {SCHEMA_VERSION!r}")

    milestone = _parse_milestone(raw["milestone"])
    clauses = _parse_clauses(raw["clauses"])
    tiers = _parse_tiers(raw["tiers"])
    integrity = _parse_integrity(raw["integrity"], project_root)
    checks = tuple(
        parse_check(item, tiers=tiers, integrity=integrity, project_root=project_root, location=f"bundle.checks[{index}]")
        for index, item in enumerate(_nonempty_list(raw["checks"], "bundle.checks"))
    )
    objectives = _parse_objectives(raw["objectives"], project_root)
    profiles = _parse_profiles(raw["profiles"])
    gates = _parse_gates(raw["gates"])
    acceptance = _parse_acceptance(raw["acceptance"])

    bundle = BundleDefinition(
        schema_version=SCHEMA_VERSION,
        milestone=milestone,
        clauses=clauses,
        tiers=tiers,
        checks=checks,
        objectives=objectives,
        profiles=profiles,
        gates=gates,
        acceptance=acceptance,
        integrity=integrity,
    )
    _validate_bundle(bundle, project_root, bundle_path)
    return bundle


def parse_check(
    raw: Any,
    *,
    tiers: Sequence[TierDefinition] | Mapping[str, TierDefinition],
    integrity: IntegrityDefinition,
    project_root: Path,
    location: str = "check",
) -> CheckDefinition:
    _object(raw, location)
    _keys(
        raw,
        required={
            "id",
            "tier",
            "argv",
            "cwd",
            "timeout_seconds",
            "inputs",
            "outputs",
            "mode",
            "authority",
            "capabilities",
            "cache",
        },
        location=location,
    )
    check_id = _id(raw["id"], f"{location}.id")
    tier_id = _id(raw["tier"], f"{location}.tier")
    known_tiers = set(tiers) if isinstance(tiers, Mapping) else {tier.id for tier in tiers}
    if tier_id not in known_tiers:
        raise ContractError(f"{location}.tier references unknown tier {tier_id!r}")
    argv = _strings(raw["argv"], f"{location}.argv")
    cwd = _cwd(raw["cwd"], f"{location}.cwd", Path(project_root).resolve())
    timeout = _positive_int(raw["timeout_seconds"], f"{location}.timeout_seconds")
    inputs = _paths(raw["inputs"], f"{location}.inputs", Path(project_root).resolve(), nonempty=False)
    outputs = _paths(raw.get("outputs", []), f"{location}.outputs", Path(project_root).resolve(), nonempty=False)
    overlap = _overlaps(inputs, outputs)
    if overlap is not None:
        raise ContractError(f"{location}.inputs and outputs overlap: {overlap}")
    mode = raw["mode"]
    if mode not in CHECK_MODES:
        raise ContractError(f"{location}.mode must be one of {sorted(CHECK_MODES)}")
    authority = raw["authority"]
    if authority not in CHECK_AUTHORITIES:
        raise ContractError(f"{location}.authority must be one of {sorted(CHECK_AUTHORITIES)}")
    capabilities = _ids(raw["capabilities"], f"{location}.capabilities", nonempty=False)
    cache = raw["cache"]
    if cache not in CHECK_CACHE_POLICIES:
        raise ContractError(f"{location}.cache must be one of {sorted(CHECK_CACHE_POLICIES)}")
    _validate_argv(argv, integrity, Path(project_root).resolve(), cwd, f"{location}.argv")
    declared_paths = (*inputs, *outputs)
    adapter = argv[1] if len(argv) > 1 else ""
    adapter_path = _argv_project_path(cwd, adapter)
    adapter_target = Path(project_root) / adapter_path
    if (
        adapter.startswith("-")
        or not adapter_target.exists()
        or not _covered(adapter_path, integrity.authoritative_check_paths)
    ):
        raise ContractError(f"{location}: argv[1] must be a sealed authoritative executor or adapter")
    for index, argument in enumerate(argv[1:], start=1):
        candidate = argument.split("=", 1)[1] if argument.startswith("--") and "=" in argument else argument
        candidate = candidate.split("::", 1)[0]
        if candidate.startswith("-") or candidate.startswith(("http://", "https://")):
            continue
        candidate_path = _argv_project_path(cwd, candidate)
        target = Path(project_root) / candidate_path
        if target.exists() and not _covered(candidate_path, declared_paths):
            raise ContractError(f"{location}.argv[{index}] path must be declared in inputs or outputs")
    if outputs and not all(_covered(path, integrity.runtime_write_paths) for path in outputs):
        raise ContractError(f"{location}.outputs must be contained by integrity.runtime_write_paths")
    if mode == "standard" and outputs:
        raise ContractError(f"{location}: standard checks must not write evidence outputs")
    if mode in {"capture", "admission"} and not outputs:
        raise ContractError(f"{location}: capture and admission checks require declared outputs")
    if mode == "capture" and cache != "never":
        raise ContractError(f"{location}: capture checks must use cache='never'")
    if authority == "evaluator" and not _paths_intersect(inputs, integrity.evaluator_paths):
        raise ContractError(f"{location}: evaluator authority must cover an evaluator path")
    if not _paths_intersect(inputs, integrity.authoritative_check_paths):
        raise ContractError(f"{location}: every check requires a sealed authoritative input")
    for index, argument in enumerate(argv[1:], start=1):
        candidate = argument.split("=", 1)[1] if argument.startswith("--") and "=" in argument else argument
        candidate = candidate.split("::", 1)[0]
        if candidate.startswith("-") or candidate.startswith(("http://", "https://")):
            continue
        candidate_path = _argv_project_path(cwd, candidate)
        target = Path(project_root) / candidate_path
        if target.exists() and not _covered(candidate_path, integrity.authoritative_check_paths):
            raise ContractError(f"{location}.argv[{index}] executable input is outside authoritative_check_paths")
    return CheckDefinition(
        check_id,
        tier_id,
        argv,
        cwd,
        timeout,
        inputs,
        outputs,
        authority,
        capabilities,
        cache,
        mode,
    )


def _parse_milestone(raw: Any) -> MilestoneDefinition:
    _object(raw, "bundle.milestone")
    _keys(raw, required={"id", "version", "title", "goal"}, location="bundle.milestone")
    version = raw["version"]
    if not isinstance(version, str) or SEMVER_PATTERN.fullmatch(version) is None:
        raise ContractError("bundle.milestone.version must be semantic version text")
    return MilestoneDefinition(
        _id(raw["id"], "bundle.milestone.id"),
        version,
        _text(raw["title"], "bundle.milestone.title"),
        _text(raw["goal"], "bundle.milestone.goal"),
    )


def _parse_clauses(raw: Any) -> tuple[ClauseDefinition, ...]:
    values = []
    for index, item in enumerate(_nonempty_list(raw, "bundle.clauses")):
        location = f"bundle.clauses[{index}]"
        _object(item, location)
        _keys(item, required={"id", "text"}, location=location)
        values.append(ClauseDefinition(_id(item["id"], f"{location}.id"), _text(item["text"], f"{location}.text")))
    return tuple(values)


def _parse_tiers(raw: Any) -> tuple[TierDefinition, ...]:
    values = []
    for index, item in enumerate(_nonempty_list(raw, "bundle.tiers")):
        location = f"bundle.tiers[{index}]"
        _object(item, location)
        _keys(item, required={"id", "rank", "cost", "reviewer_admissible"}, location=location)
        cost = item["cost"]
        if cost not in TIER_COSTS:
            raise ContractError(f"{location}.cost must be one of {sorted(TIER_COSTS)}")
        values.append(
            TierDefinition(
                _id(item["id"], f"{location}.id"),
                _nonnegative_int(item["rank"], f"{location}.rank"),
                cost,
                _boolean(item["reviewer_admissible"], f"{location}.reviewer_admissible"),
            )
        )
    ranks = [tier.rank for tier in values]
    if len(ranks) != len(set(ranks)):
        raise ContractError("bundle.tiers ranks must be unique")
    if values != sorted(values, key=lambda tier: tier.rank):
        raise ContractError("bundle.tiers must be ordered by ascending rank")
    if any(tier.reviewer_admissible and tier.cost in {"expensive", "operator"} for tier in values):
        raise ContractError("expensive and operator tiers must not be reviewer-admissible")
    return tuple(values)


def _parse_objectives(raw: Any, project_root: Path) -> tuple[ObjectiveDefinition, ...]:
    values = []
    required = {
        "id",
        "title",
        "depends_on",
        "clause_ids",
        "check_ids",
        "context_paths",
        "worker_write_paths",
        "required_for_milestone",
    }
    for index, item in enumerate(_nonempty_list(raw, "bundle.objectives")):
        location = f"bundle.objectives[{index}]"
        _object(item, location)
        _keys(item, required=required, location=location)
        values.append(
            ObjectiveDefinition(
                _id(item["id"], f"{location}.id"),
                _text(item["title"], f"{location}.title"),
                _ids(item["depends_on"], f"{location}.depends_on", nonempty=False),
                _ids(item["clause_ids"], f"{location}.clause_ids", nonempty=True),
                _ids(item["check_ids"], f"{location}.check_ids", nonempty=True),
                _paths(item["context_paths"], f"{location}.context_paths", project_root, nonempty=False),
                _paths(item["worker_write_paths"], f"{location}.worker_write_paths", project_root, nonempty=False),
                _boolean(item["required_for_milestone"], f"{location}.required_for_milestone"),
            )
        )
    return tuple(values)


def _parse_profiles(raw: Any) -> tuple[ProfileDefinition, ...]:
    values = []
    required = {"id", "objective_ids", "include_dependency_closure", "gate_ids", "claim"}
    for index, item in enumerate(_nonempty_list(raw, "bundle.profiles")):
        location = f"bundle.profiles[{index}]"
        _object(item, location)
        _keys(item, required=required, location=location)
        claim = item["claim"]
        if claim not in PROFILE_CLAIMS:
            raise ContractError(f"{location}.claim must be one of {sorted(PROFILE_CLAIMS)}")
        include_closure = _boolean(item["include_dependency_closure"], f"{location}.include_dependency_closure")
        if include_closure is not True:
            raise ContractError(f"{location}.include_dependency_closure must be true in bundle v1")
        values.append(
            ProfileDefinition(
                _id(item["id"], f"{location}.id"),
                _ids(item["objective_ids"], f"{location}.objective_ids", nonempty=True),
                include_closure,
                _ids(item["gate_ids"], f"{location}.gate_ids", nonempty=False),
                claim,
            )
        )
    return tuple(values)


def _parse_gates(raw: Any) -> tuple[GateDefinition, ...]:
    values = []
    base_required = {
        "id",
        "kind",
        "after_objective_ids",
        "operator_approval_required",
        "required_for_milestone",
    }
    for index, item in enumerate(_list(raw, "bundle.gates")):
        location = f"bundle.gates[{index}]"
        _object(item, location)
        kind = item.get("kind")
        if kind not in GATE_KINDS:
            raise ContractError(f"{location}.kind must be one of {sorted(GATE_KINDS)}")
        if kind == "program":
            _keys(item, required=base_required | {"check_ids"}, location=location)
            program_checks = _ids(item["check_ids"], f"{location}.check_ids", nonempty=True)
            preflight_checks = program_checks
            capture = None
            admission_checks: tuple[str, ...] = ()
        else:
            _keys(
                item,
                required=base_required | {"preflight_check_ids", "capture_check_id", "admission_check_ids"},
                location=location,
            )
            program_checks = ()
            preflight_checks = _ids(item["preflight_check_ids"], f"{location}.preflight_check_ids", nonempty=True)
            capture = _id(item["capture_check_id"], f"{location}.capture_check_id")
            admission_checks = _ids(item["admission_check_ids"], f"{location}.admission_check_ids", nonempty=True)
        values.append(
            GateDefinition(
                _id(item["id"], f"{location}.id"),
                kind,
                _ids(item["after_objective_ids"], f"{location}.after_objective_ids", nonempty=True),
                program_checks,
                preflight_checks,
                capture,
                admission_checks,
                _boolean(item["operator_approval_required"], f"{location}.operator_approval_required"),
                _boolean(item["required_for_milestone"], f"{location}.required_for_milestone"),
            )
        )
    return tuple(values)


def _parse_acceptance(raw: Any) -> AcceptanceDefinition:
    location = "bundle.acceptance"
    _object(raw, location)
    budget_keys = {
        "max_attempts",
        "stagnation_limit",
        "max_replans",
        "max_review_rounds",
        "max_new_gaps_per_review",
        "max_context_bytes",
        "failure_excerpt_bytes",
        "cache_unchanged_results",
        "max_expensive_runs_per_input",
    }
    required = {
        "objective_rule",
        "milestone_rule",
        "common_check_ids",
        "closure_check_ids",
        "evaluator_guard_check_ids",
        *budget_keys,
    }
    _keys(raw, required=required, location=location)
    if raw["objective_rule"] != OBJECTIVE_RULE:
        raise ContractError(f"{location}.objective_rule must be {OBJECTIVE_RULE!r}")
    if raw["milestone_rule"] != MILESTONE_RULE:
        raise ContractError(f"{location}.milestone_rule must be {MILESTONE_RULE!r}")
    budgets = BudgetDefinition(
        _positive_int(raw["max_attempts"], f"{location}.max_attempts"),
        _positive_int(raw["stagnation_limit"], f"{location}.stagnation_limit"),
        _nonnegative_int(raw["max_replans"], f"{location}.max_replans"),
        _positive_int(raw["max_review_rounds"], f"{location}.max_review_rounds"),
        _positive_int(raw["max_new_gaps_per_review"], f"{location}.max_new_gaps_per_review"),
        _positive_int(raw["max_context_bytes"], f"{location}.max_context_bytes"),
        _positive_int(raw["failure_excerpt_bytes"], f"{location}.failure_excerpt_bytes"),
        _boolean(raw["cache_unchanged_results"], f"{location}.cache_unchanged_results"),
        _positive_int(raw["max_expensive_runs_per_input"], f"{location}.max_expensive_runs_per_input"),
    )
    if budgets.max_new_gaps_per_review != 1:
        raise ContractError(f"{location}.max_new_gaps_per_review must be exactly 1")
    if budgets.cache_unchanged_results is not True:
        raise ContractError(f"{location}.cache_unchanged_results must be true")
    if budgets.max_context_bytes < budgets.failure_excerpt_bytes:
        raise ContractError(f"{location}.max_context_bytes must cover failure_excerpt_bytes")
    return AcceptanceDefinition(
        OBJECTIVE_RULE,
        MILESTONE_RULE,
        _ids(raw["common_check_ids"], f"{location}.common_check_ids", nonempty=False),
        _ids(raw["closure_check_ids"], f"{location}.closure_check_ids", nonempty=False),
        _ids(raw["evaluator_guard_check_ids"], f"{location}.evaluator_guard_check_ids", nonempty=False),
        budgets,
    )


def _parse_integrity(raw: Any, project_root: Path) -> IntegrityDefinition:
    location = "bundle.integrity"
    _object(raw, location)
    keys = {
        "product_roots",
        "evaluator_paths",
        "evaluator_repair_paths",
        "authoritative_check_paths",
        "allowed_tools",
        "evidence_roots",
    }
    _keys(raw, required=keys, location=location)
    allowed_tools = _strings(raw["allowed_tools"], f"{location}.allowed_tools")
    for index, tool in enumerate(allowed_tools):
        if not TOOL_PATTERN.fullmatch(tool) or tool in BANNED_TOOLS:
            raise ContractError(f"{location}.allowed_tools[{index}] is not an allowed direct executable")
    evidence_roots = _paths(raw["evidence_roots"], f"{location}.evidence_roots", project_root, nonempty=False)
    if any(PurePosixPath(path).parts[0] in {"logs", "pycache", "state"} for path in evidence_roots):
        raise ContractError(f"{location}.evidence_roots use controller-reserved names")
    integrity = IntegrityDefinition(
        _paths(raw["product_roots"], f"{location}.product_roots", project_root, nonempty=True),
        _paths(raw["evaluator_paths"], f"{location}.evaluator_paths", project_root, nonempty=True),
        _paths(raw["evaluator_repair_paths"], f"{location}.evaluator_repair_paths", project_root, nonempty=True),
        _paths(raw["authoritative_check_paths"], f"{location}.authoritative_check_paths", project_root, nonempty=True),
        evidence_roots,
        allowed_tools,
    )
    zones = (
        ("product_roots", integrity.product_roots),
        ("evaluator_repair_paths", integrity.evaluator_repair_paths),
        ("authoritative_check_paths", integrity.authoritative_check_paths),
        ("evidence_roots", integrity.evidence_roots),
    )
    for index, (left_name, left_paths) in enumerate(zones):
        for right_name, right_paths in zones[index + 1 :]:
            overlap = _overlaps(left_paths, right_paths)
            if overlap is not None:
                raise ContractError(f"authority write overlap between {left_name} and {right_name}: {overlap}")
    return integrity


def _validate_bundle(bundle: BundleDefinition, project_root: Path, bundle_path: Path | None) -> None:
    groups: tuple[tuple[str, Iterable[Any]], ...] = (
        ("milestone", (bundle.milestone,)),
        ("clauses", bundle.clauses),
        ("tiers", bundle.tiers),
        ("checks", bundle.checks),
        ("objectives", bundle.objectives),
        ("profiles", bundle.profiles),
        ("gates", bundle.gates),
    )
    owner: dict[str, str] = {}
    for group, values in groups:
        for value in values:
            if value.id in owner:
                raise ContractError(f"global id {value.id!r} is duplicated by {owner[value.id]} and {group}")
            owner[value.id] = group

    clause_ids = {clause.id for clause in bundle.clauses}
    check_ids = {check.id for check in bundle.checks}
    objective_ids = {objective.id for objective in bundle.objectives}
    gate_ids = {gate.id for gate in bundle.gates}
    _validate_dag({objective.id: objective.depends_on for objective in bundle.objectives}, "objective")

    used_checks = set(bundle.acceptance.common_check_ids) | set(bundle.acceptance.closure_check_ids) | set(bundle.acceptance.evaluator_guard_check_ids)
    used_clauses: set[str] = set()
    for objective in bundle.objectives:
        _references(objective.depends_on, objective_ids - {objective.id}, f"objective {objective.id} dependencies")
        _references(objective.clause_ids, clause_ids, f"objective {objective.id} clauses")
        _references(objective.check_ids, check_ids, f"objective {objective.id} checks")
        if not all(_covered(path, bundle.integrity.product_roots) for path in objective.worker_write_paths):
            raise ContractError(f"objective {objective.id} worker_write_paths must be contained by integrity.product_roots")
        objective_inputs = tuple(path for check_id in objective.check_ids for path in bundle.check(check_id).inputs)
        if not all(_covered(path, objective_inputs) for path in objective.worker_write_paths):
            raise ContractError(f"objective {objective.id} checks must cover every worker_write_path")
        used_checks.update(objective.check_ids)
        used_clauses.update(objective.clause_ids)

    acceptance_groups = (
        ("common_check_ids", bundle.acceptance.common_check_ids),
        ("closure_check_ids", bundle.acceptance.closure_check_ids),
        ("evaluator_guard_check_ids", bundle.acceptance.evaluator_guard_check_ids),
    )
    seen_acceptance: set[str] = set()
    for label, values in acceptance_groups:
        _references(values, check_ids, f"acceptance.{label}")
        overlap = seen_acceptance.intersection(values)
        if overlap:
            raise ContractError(f"acceptance check categories overlap: {sorted(overlap)}")
        seen_acceptance.update(values)
    if not bundle.acceptance.closure_check_ids:
        raise ContractError("acceptance.closure_check_ids must not be empty")
    if not bundle.acceptance.evaluator_guard_check_ids:
        raise ContractError("acceptance.evaluator_guard_check_ids must not be empty")
    for check_id in bundle.acceptance.evaluator_guard_check_ids:
        check = bundle.check(check_id)
        tier = bundle.tier(check.tier)
        if check.capabilities or tier.cost in {"expensive", "operator"}:
            raise ContractError(
                f"acceptance.evaluator_guard_check_ids check {check_id!r} must be unprivileged"
            )
        if check.mode != "standard" or check.outputs:
            raise ContractError(
                f"acceptance.evaluator_guard_check_ids check {check_id!r} must be a read-only standard check"
            )
    closure_inputs = tuple(
        path
        for check_id in bundle.acceptance.closure_check_ids
        for path in bundle.check(check_id).inputs
    )
    uncovered_roots = [root for root in bundle.integrity.product_roots if not _covered(root, closure_inputs)]
    if uncovered_roots:
        raise ContractError(f"closure checks do not cover product roots: {uncovered_roots}")

    tiers = {tier.id: tier for tier in bundle.tiers}
    for check in bundle.checks:
        if check.id in bundle.acceptance.evaluator_guard_check_ids and not _paths_intersect(check.inputs, bundle.integrity.evaluator_paths):
            raise ContractError(f"evaluator guard check {check.id} must cover an evaluator path")

    required_objectives = {objective.id for objective in bundle.objectives if objective.required_for_milestone}
    required_gates = {gate.id for gate in bundle.gates if gate.required_for_milestone}
    if not required_objectives:
        raise ContractError("MILESTONE_COMPLETE requires at least one required objective")
    for gate in bundle.gates:
        _references(gate.after_objective_ids, objective_ids, f"gate {gate.id} after_objective_ids")
        _require_dependency_closed(gate.after_objective_ids, bundle, f"gate {gate.id} after_objective_ids")
        _references(gate.all_check_ids, check_ids, f"gate {gate.id} checks")
        if len(gate.all_check_ids) != len(set(gate.all_check_ids)):
            raise ContractError(f"gate {gate.id} check roles must not overlap")
        if gate.kind == "program" and any(bundle.check(check_id).mode != "standard" for check_id in gate.check_ids):
            raise ContractError(f"program gate {gate.id} check_ids must reference standard checks")
        if gate.kind == "evidence" and any(
            bundle.check(check_id).mode != "standard" for check_id in gate.preflight_check_ids
        ):
            raise ContractError(f"evidence gate {gate.id} preflight_check_ids must reference standard checks")
        if gate.capture_check_id is not None and bundle.check(gate.capture_check_id).mode != "capture":
            raise ContractError(f"gate {gate.id} capture_check_id must reference a capture check")
        if any(bundle.check(check_id).mode != "admission" for check_id in gate.admission_check_ids):
            raise ContractError(f"gate {gate.id} admission_check_ids must reference admission checks")
        if gate.kind == "evidence" and gate.capture_check_id is not None:
            capture_outputs = bundle.check(gate.capture_check_id).outputs
            admission_inputs = tuple(path for check_id in gate.admission_check_ids for path in bundle.check(check_id).inputs)
            if not all(_covered(path, admission_inputs) for path in capture_outputs):
                raise ContractError(f"gate {gate.id} admission checks must consume every capture output")
        privileged = any(
            bundle.check(check_id).capabilities
            or tiers[bundle.check(check_id).tier].cost in {"expensive", "operator"}
            for check_id in gate.all_check_ids
        )
        if privileged and not gate.operator_approval_required:
            raise ContractError(f"gate {gate.id} has privileged checks and requires operator approval")
        used_checks.update(gate.all_check_ids)

    objective_and_acceptance_ids = {
        *seen_acceptance,
        *(check_id for objective in bundle.objectives for check_id in objective.check_ids),
    }
    for check_id in objective_and_acceptance_ids:
        check = bundle.check(check_id)
        if check.mode != "standard" or check.capabilities or tiers[check.tier].cost == "operator":
            raise ContractError(
                f"objective/common/closure check {check_id} must be standard and unprivileged"
            )
    gated_capture = {gate.capture_check_id for gate in bundle.gates if gate.capture_check_id is not None}
    gated_admission = {check_id for gate in bundle.gates for check_id in gate.admission_check_ids}
    if {check.id for check in bundle.checks if check.mode == "capture"} != gated_capture:
        raise ContractError("capture checks must appear exactly once in evidence gate capture positions")
    if {check.id for check in bundle.checks if check.mode == "admission"} != gated_admission:
        raise ContractError("admission checks must appear in evidence gate admission positions")
    privileged_checks = {
        check.id for check in bundle.checks if check.capabilities or tiers[check.tier].cost == "operator"
    }
    approved_gate_checks = {
        check_id
        for gate in bundle.gates
        if gate.operator_approval_required
        for check_id in gate.all_check_ids
    }
    if not privileged_checks.issubset(approved_gate_checks):
        raise ContractError(
            "capability/operator checks are not confined to approved gates: "
            f"{sorted(privileged_checks - approved_gate_checks)}"
        )

    completion_profiles = []
    for profile in bundle.profiles:
        _references(profile.objective_ids, objective_ids, f"profile {profile.id} objective_ids")
        _references(profile.gate_ids, gate_ids, f"profile {profile.id} gate_ids")
        if not profile.include_dependency_closure:
            _require_dependency_closed(profile.objective_ids, bundle, f"profile {profile.id} objective_ids")
        resolved = bundle.resolve_profile(profile.id)
        for gate in resolved.gates:
            missing = set(gate.after_objective_ids) - set(resolved.objective_ids)
            if missing:
                raise ContractError(f"profile {profile.id} selects gate {gate.id} without objectives {sorted(missing)}")
        if profile.claim == MILESTONE_COMPLETE:
            completion_profiles.append(resolved)
            missing_objectives = required_objectives - set(resolved.objective_ids)
            missing_gates = required_gates - set(resolved.gate_ids)
            if missing_objectives or missing_gates:
                raise ContractError(
                    f"profile {profile.id} claims MILESTONE_COMPLETE without required objectives "
                    f"{sorted(missing_objectives)} or gates {sorted(missing_gates)}"
                )
    if not completion_profiles:
        raise ContractError("at least one profile must claim MILESTONE_COMPLETE")

    required_clauses = {
        clause_id
        for objective in bundle.objectives
        if objective.required_for_milestone
        for clause_id in objective.clause_ids
    }
    if required_clauses != clause_ids:
        raise ContractError(f"MILESTONE_COMPLETE clause coverage mismatch: {sorted(clause_ids - required_clauses)}")
    if used_checks != check_ids:
        raise ContractError(f"unreferenced checks are forbidden: {sorted(check_ids - used_checks)}")

    integrity = bundle.integrity
    if not all(_covered(path, integrity.evaluator_repair_paths) for path in integrity.evaluator_paths):
        raise ContractError("integrity.evaluator_paths must be covered by evaluator_repair_paths")
    authority_zones = (
        ("evaluator_repair_paths", integrity.evaluator_repair_paths),
        ("authoritative_check_paths", integrity.authoritative_check_paths),
        ("evidence_roots", integrity.evidence_roots),
    )
    for index, (left_name, left_paths) in enumerate(authority_zones):
        for right_name, right_paths in authority_zones[index + 1 :]:
            overlap = _overlaps(left_paths, right_paths)
            if overlap is not None:
                raise ContractError(f"authority write overlap between {left_name} and {right_name}: {overlap}")
    worker_paths = tuple(path for objective in bundle.objectives for path in objective.worker_write_paths)
    for zone_name, zone_paths in authority_zones:
        overlap = _overlaps(worker_paths, zone_paths)
        if overlap is not None:
            raise ContractError(f"authority write overlap between worker_write_paths and {zone_name}: {overlap}")

    known_input_zones = (
        *integrity.product_roots,
        *integrity.evaluator_paths,
        *integrity.authoritative_check_paths,
        *integrity.evidence_roots,
    )
    for check in bundle.checks:
        uncovered = [path for path in check.inputs if not _covered(path, known_input_zones)]
        if uncovered:
            raise ContractError(f"check {check.id} inputs are outside declared integrity zones: {uncovered}")

    output_owners: list[tuple[str, str]] = [
        (output, check.authority) for check in bundle.checks for output in check.outputs
    ]
    for index, (left_path, left_authority) in enumerate(output_owners):
        for right_path, right_authority in output_owners[index + 1 :]:
            if left_authority != right_authority and _path_overlap(left_path, right_path):
                raise ContractError(
                    f"authority write overlap between {left_authority!r} and {right_authority!r}: "
                    f"{left_path!r}, {right_path!r}"
                )

    if bundle_path is not None:
        try:
            relative = _relative_from_root(project_root, bundle_path)
        except ContractError:
            relative = None
        if relative is not None:
            _contained_path(project_root, relative, "bundle")
            if _covered(relative, bundle.integrity.product_roots):
                raise ContractError("bundle path must be outside product_roots")
            for objective in bundle.objectives:
                if any(_covered(relative, (path,)) for path in objective.worker_write_paths):
                    raise ContractError(f"objective {objective.id} worker write authority overlaps the bundle")


def _validate_argv(
    argv: tuple[str, ...],
    integrity: IntegrityDefinition,
    project_root: Path,
    cwd: str,
    location: str,
) -> None:
    tool = argv[0]
    if tool not in integrity.allowed_tools or tool in BANNED_TOOLS:
        raise ContractError(f"{location}[0] is not in integrity.allowed_tools")
    if not TOOL_PATTERN.fullmatch(tool):
        raise ContractError(f"{location}[0] must be a direct executable name")
    for index, argument in enumerate(argv):
        if "\x00" in argument or "\n" in argument or "\r" in argument:
            raise ContractError(f"{location}[{index}] contains a forbidden control character")
        if argument in SHELL_TOKENS or "$(" in argument or "`" in argument or any(
            token in argument for token in ("&&", "||", ";", ">", "<")
        ):
            raise ContractError(f"{location}[{index}] contains shell syntax")
        candidate = argument.split("=", 1)[1] if argument.startswith("--") and "=" in argument else argument
        candidate = candidate.split("::", 1)[0]
        if candidate.startswith("/") or PurePosixPath(candidate).is_absolute():
            raise ContractError(f"{location}[{index}] contains an absolute path")
        if "/" in candidate and not candidate.startswith(("http://", "https://")):
            _contained_path(project_root, _argv_project_path(cwd, candidate), f"{location}[{index}]")
    lowered = tool.lower()
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", lowered):
        if len(argv) < 2 or argv[1] in {"-", "-c", "--command"}:
            raise ContractError(f"{location} forbids inline Python")
        if argv[1] == "-m":
            raise ContractError(f"{location} forbids Python module execution; use an authoritative adapter path")
        if argv[1].startswith("-"):
            raise ContractError(f"{location} forbids Python interpreter flags before the authoritative adapter")
        script = _contained_path(project_root, _argv_project_path(cwd, argv[1]), f"{location}[1]")
        if script.suffix != ".py":
            raise ContractError(f"{location}[1] must be a project-local .py script")
    if lowered in {"node", "ruby", "perl"} and any(argument in {"-e", "--eval"} for argument in argv[1:]):
        raise ContractError(f"{location} forbids inline code")


def _validate_dag(graph: Mapping[str, tuple[str, ...]], label: str) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ContractError(f"{label} dependency cycle includes {node}")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph.get(node, ()):
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def _require_dependency_closed(objective_ids: Iterable[str], bundle: BundleDefinition, location: str) -> None:
    selected = set(objective_ids)
    missing = {
        dependency
        for objective_id in selected
        for dependency in bundle.objective(objective_id).depends_on
        if dependency not in selected
    }
    if missing:
        raise ContractError(f"{location} is not dependency-closed: {sorted(missing)}")


def _references(values: Iterable[str], known: set[str], location: str) -> None:
    missing = set(values) - known
    if missing:
        raise ContractError(f"{location} references unknown ids: {sorted(missing)}")


def _keys(raw: Mapping[str, Any], *, required: set[str], location: str, optional: set[str] | None = None) -> None:
    allowed = required | (optional or set())
    missing = required - set(raw)
    unknown = set(raw) - allowed
    if missing:
        raise ContractError(f"{location} is missing keys: {sorted(missing)}")
    if unknown:
        raise ContractError(f"{location} has unknown keys: {sorted(unknown)}")


def _object(raw: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        raise ContractError(f"{location} must be an object")
    return raw


def _nonempty_list(raw: Any, location: str) -> list[Any]:
    if not isinstance(raw, list) or not raw:
        raise ContractError(f"{location} must be a non-empty list")
    return raw


def _list(raw: Any, location: str) -> list[Any]:
    if not isinstance(raw, list):
        raise ContractError(f"{location} must be a list")
    return raw


def _strings(raw: Any, location: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw or any(not isinstance(value, str) or not value for value in raw):
        raise ContractError(f"{location} must be a non-empty string list")
    if len(raw) != len(set(raw)):
        raise ContractError(f"{location} values must be unique")
    return tuple(raw)


def _ids(raw: Any, location: str, *, nonempty: bool) -> tuple[str, ...]:
    if not isinstance(raw, list) or (nonempty and not raw):
        qualifier = "non-empty " if nonempty else ""
        raise ContractError(f"{location} must be a {qualifier}list")
    values = tuple(_id(value, f"{location}[{index}]") for index, value in enumerate(raw))
    if len(values) != len(set(values)):
        raise ContractError(f"{location} values must be unique")
    return values


def _paths(raw: Any, location: str, project_root: Path, *, nonempty: bool) -> tuple[str, ...]:
    if not isinstance(raw, list) or (nonempty and not raw):
        qualifier = "non-empty " if nonempty else ""
        raise ContractError(f"{location} must be a {qualifier}path list")
    values = []
    for index, value in enumerate(raw):
        if not isinstance(value, str):
            raise ContractError(f"{location}[{index}] must be a string path")
        _contained_path(project_root, value, f"{location}[{index}]")
        values.append(value)
    if len(values) != len(set(values)):
        raise ContractError(f"{location} paths must be unique")
    return tuple(values)


def _cwd(raw: Any, location: str, project_root: Path) -> str:
    if raw == ".":
        return raw
    if not isinstance(raw, str):
        raise ContractError(f"{location} must be a relative path")
    path = _contained_path(project_root, raw, location)
    if path.exists() and not path.is_dir():
        raise ContractError(f"{location} must identify a directory")
    return raw


def _argv_project_path(cwd: str, raw: str) -> str:
    if cwd == ".":
        return raw
    return (PurePosixPath(cwd) / PurePosixPath(raw)).as_posix()


def _contained_path(project_root: Path, raw: str, location: str) -> Path:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise ContractError(f"{location} must be a non-empty relative POSIX path")
    pure = PurePosixPath(raw)
    if (
        pure.is_absolute()
        or SAFE_PATH_PATTERN.fullmatch(raw) is None
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ContractError(f"{location} escapes project root")
    candidate = project_root.joinpath(*pure.parts)
    current = project_root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ContractError(f"{location} traverses symlink {current}")
    try:
        candidate.relative_to(project_root)
    except ValueError as exc:  # pragma: no cover - lexical checks above are primary
        raise ContractError(f"{location} escapes project root") from exc
    return candidate


def _relative_from_root(project_root: Path, path: Path) -> str:
    absolute = Path(path).absolute()
    try:
        return absolute.relative_to(project_root).as_posix()
    except ValueError as exc:
        raise ContractError(f"path is outside project root: {path}") from exc


def _covered(path: str, roots: Iterable[str]) -> bool:
    child = PurePosixPath(path).parts
    return any(_parts_contain(PurePosixPath(root).parts, child) for root in roots)


def _overlaps(left: Iterable[str], right: Iterable[str]) -> str | None:
    for left_path in left:
        for right_path in right:
            if _path_overlap(left_path, right_path):
                return f"{left_path!r} and {right_path!r}"
    return None


def _path_overlap(left: str, right: str) -> bool:
    left_parts = PurePosixPath(left).parts
    right_parts = PurePosixPath(right).parts
    return _parts_contain(left_parts, right_parts) or _parts_contain(right_parts, left_parts)


def _paths_intersect(left: Iterable[str], right: Iterable[str]) -> bool:
    return any(_path_overlap(left_path, right_path) for left_path in left for right_path in right)


def _parts_contain(parent: tuple[str, ...], child: tuple[str, ...]) -> bool:
    return len(parent) <= len(child) and child[: len(parent)] == parent


def _id(raw: Any, location: str) -> str:
    if not isinstance(raw, str) or ID_PATTERN.fullmatch(raw) is None:
        raise ContractError(f"{location} must be a strict ASCII identifier")
    return raw


def _text(raw: Any, location: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ContractError(f"{location} must be a non-empty string")
    return raw


def _boolean(raw: Any, location: str) -> bool:
    if not isinstance(raw, bool):
        raise ContractError(f"{location} must be a boolean")
    return raw


def _positive_int(raw: Any, location: str) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
        raise ContractError(f"{location} must be a positive integer")
    return raw


def _nonnegative_int(raw: Any, location: str) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ContractError(f"{location} must be a non-negative integer")
    return raw
