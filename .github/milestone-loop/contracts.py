from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


STATUSES = ("ready", "in-progress", "blocked", "review", "completed", "superseded")
PLANNER_STATUSES = ("ready", "blocked", "superseded")
STATUS_LABELS = {f"milestone-loop:{status}" for status in STATUSES}
ID_RE = re.compile(r"^[a-z][a-z0-9_.-]*$", re.ASCII)
ISSUE_RE = re.compile(r"^#([1-9][0-9]*)$")
CONTRACT_RE = re.compile(
    r"(?m)^Criterion: ([^\r\n]+)\r?\nDepends on: ([^\r\n]+)\r?\nCheck: ([^\r\n]+)$"
)
PR_CONTRACT_CHANGE_RE = re.compile(r"(?m)^Contract-Change: (true|false)$")


class ContractError(ValueError):
    pass


def strict_json_loads(raw: str, *, max_bytes: int) -> Any:
    if len(raw.encode("utf-8")) > max_bytes:
        raise ContractError(f"JSON exceeds {max_bytes} bytes")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ContractError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=reject_duplicate)
    except ContractError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON: {exc}") from exc


def require_fields(
    value: Mapping[str, Any], *, required: set[str], optional: set[str] = set(), location: str
) -> None:
    actual = set(value)
    missing = sorted(required - actual)
    extra = sorted(actual - required - optional)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unexpected {extra}")
        raise ContractError(f"{location}: {', '.join(details)}")


def _bounded_text(value: Any, *, location: str, limit: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{location} must be text")
    if not allow_empty and not value.strip():
        raise ContractError(f"{location} must not be empty")
    if len(value.encode("utf-8")) > limit:
        raise ContractError(f"{location} exceeds {limit} bytes")
    return value


@dataclass(frozen=True)
class WorkItemContract:
    criterion: str
    depends_on: tuple[int, ...]
    check: str


def parse_work_item(body: str) -> WorkItemContract:
    if not isinstance(body, str) or len(body.encode("utf-8")) > 32_768:
        raise ContractError("work item body must be text no larger than 32768 bytes")
    matches = list(CONTRACT_RE.finditer(body))
    contract_lines = re.findall(r"(?m)^(?:Criterion|Depends on|Check):", body)
    if len(matches) != 1 or len(contract_lines) != 3:
        raise ContractError(
            "work item must contain exactly one contiguous Criterion/Depends on/Check block"
        )
    criterion, raw_dependencies, check = (part.strip() for part in matches[0].groups())
    if ID_RE.fullmatch(criterion) is None:
        raise ContractError("Criterion must be one lowercase identifier")
    if ID_RE.fullmatch(check) is None:
        raise ContractError("Check must be one lowercase identifier without arguments")
    if raw_dependencies == "none":
        dependencies: tuple[int, ...] = ()
    else:
        parts = [part.strip() for part in raw_dependencies.split(",")]
        if not parts or len(parts) > 8:
            raise ContractError("Depends on must contain one to eight Issue references")
        parsed: list[int] = []
        for part in parts:
            match = ISSUE_RE.fullmatch(part)
            if match is None:
                raise ContractError("Depends on must be 'none' or comma-separated #<number> values")
            number = int(match.group(1))
            if number in parsed:
                raise ContractError("Depends on contains a duplicate Issue reference")
            parsed.append(number)
        dependencies = tuple(parsed)
    return WorkItemContract(criterion, dependencies, check)


def render_work_item(description: str, contract: WorkItemContract) -> str:
    description = _bounded_text(description.strip(), location="description", limit=12_000)
    dependencies = "none" if not contract.depends_on else ", ".join(
        f"#{number}" for number in contract.depends_on
    )
    return (
        f"{description}\n\n"
        f"Criterion: {contract.criterion}\n"
        f"Depends on: {dependencies}\n"
        f"Check: {contract.check}"
    )


def catalog_ids(document: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    if document.get("schema_version") != "verification-catalog-v2":
        raise ContractError("trusted catalog has an unsupported schema_version")
    tests = document.get("tests")
    suites = document.get("suites")
    if not isinstance(tests, list) or not isinstance(suites, list):
        raise ContractError("trusted catalog tests and suites must be arrays")
    test_ids = {
        item.get("test_id")
        for item in tests
        if isinstance(item, dict) and isinstance(item.get("test_id"), str)
    }
    suite_ids = {
        item.get("suite_id")
        for item in suites
        if isinstance(item, dict) and isinstance(item.get("suite_id"), str)
    }
    if len(test_ids) != len(tests) or len(suite_ids) != len(suites) or test_ids & suite_ids:
        raise ContractError("trusted catalog contains malformed or duplicate IDs")
    return test_ids, suite_ids


def resolve_check(document: Mapping[str, Any], check_id: str) -> tuple[str, ...]:
    if ID_RE.fullmatch(check_id) is None:
        raise ContractError("Check must be one Catalog ID without a path, arguments, or command")
    tests, suites = catalog_ids(document)
    if check_id in tests:
        return ("./gate", "test", check_id)
    if check_id in suites:
        return ("./gate", "suite", check_id)
    raise ContractError(f"Check {check_id!r} is absent from the trusted base Catalog")


def require_candidate_check(document: Mapping[str, Any], check_id: str) -> tuple[str, ...]:
    command = resolve_check(document, check_id)
    tests = {
        item["test_id"]: item
        for item in document["tests"]
        if isinstance(item, dict) and isinstance(item.get("test_id"), str)
    }
    suites = {
        item["suite_id"]: item
        for item in document["suites"]
        if isinstance(item, dict) and isinstance(item.get("suite_id"), str)
    }
    selected = [check_id] if check_id in tests else list(suites[check_id].get("test_ids", []))
    if not selected or any(test_id not in tests for test_id in selected):
        raise ContractError(f"Catalog Suite {check_id!r} has invalid Test references")
    parameterized = [
        test_id
        for test_id in selected
        if isinstance(tests[test_id].get("parameters"), dict) and tests[test_id]["parameters"]
    ]
    if parameterized:
        raise ContractError(
            f"Work Item Check cannot require parameters or real-environment selection: {parameterized}"
        )
    return command


def milestone_criteria(document: Mapping[str, Any], milestone: str) -> dict[str, tuple[str, ...]]:
    if document.get("id") != milestone:
        raise ContractError("Milestone document id does not match the fixed dispatch milestone")
    raw = document.get("criteria")
    if not isinstance(raw, list) or not raw:
        raise ContractError("Milestone criteria must be a non-empty array")
    result: dict[str, tuple[str, ...]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) - {"id", "statement", "check"}:
            raise ContractError(f"criterion[{index}] has invalid fields")
        criterion_id = item.get("id")
        if not isinstance(criterion_id, str) or ID_RE.fullmatch(criterion_id) is None:
            raise ContractError(f"criterion[{index}].id is invalid")
        if criterion_id in result:
            raise ContractError(f"duplicate Criterion {criterion_id}")
        checks = item.get("check")
        if checks is None:
            result[criterion_id] = ()
            continue
        if not isinstance(checks, list) or not checks:
            raise ContractError(f"criterion[{index}].check must be a non-empty array")
        ids: list[str] = []
        for check_index, check in enumerate(checks):
            if not isinstance(check, dict) or set(check) - {"id", "parameters"}:
                raise ContractError(f"criterion[{index}].check[{check_index}] is invalid")
            check_id = check.get("id")
            if not isinstance(check_id, str) or ID_RE.fullmatch(check_id) is None:
                raise ContractError(f"criterion[{index}].check[{check_index}].id is invalid")
            ids.append(check_id)
        result[criterion_id] = tuple(ids)
    return result


@dataclass(frozen=True)
class PlannerOperation:
    kind: str
    issue: int | None
    title: str | None
    description: str | None
    criterion: str
    depends_on: tuple[int, ...]
    check: str
    status: str


@dataclass(frozen=True)
class PlannerOutput:
    operations: tuple[PlannerOperation, ...]
    ready_issue: int | None
    summary: str


def parse_planner_output(raw: str) -> PlannerOutput:
    value = strict_json_loads(raw, max_bytes=32_768)
    if not isinstance(value, dict):
        raise ContractError("planner output must be an object")
    require_fields(value, required={"operations", "ready_issue", "summary"}, location="planner")
    operations = value["operations"]
    if not isinstance(operations, list) or len(operations) > 12:
        raise ContractError("planner.operations must contain at most 12 entries")
    parsed: list[PlannerOperation] = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ContractError(f"planner.operations[{index}] must be an object")
        require_fields(
            operation,
            required={"kind", "issue", "title", "description", "criterion", "depends_on", "check", "status"},
            location=f"planner.operations[{index}]",
        )
        kind = operation["kind"]
        if kind not in {"create", "update"}:
            raise ContractError(f"planner.operations[{index}].kind is invalid")
        issue = operation["issue"]
        if kind == "create" and issue is not None:
            raise ContractError("create operation issue must be null")
        if kind == "update" and (isinstance(issue, bool) or not isinstance(issue, int) or issue <= 0):
            raise ContractError("update operation issue must be a positive integer")
        title = operation["title"]
        description = operation["description"]
        if title is not None:
            title = _bounded_text(title, location="operation.title", limit=240)
        if description is not None:
            description = _bounded_text(description, location="operation.description", limit=12_000)
        if kind == "create" and (title is None or description is None):
            raise ContractError("create operation requires title and description")
        criterion = operation["criterion"]
        check = operation["check"]
        if not isinstance(criterion, str) or ID_RE.fullmatch(criterion) is None:
            raise ContractError("operation.criterion is invalid")
        if not isinstance(check, str) or ID_RE.fullmatch(check) is None:
            raise ContractError("operation.check is invalid")
        dependencies = operation["depends_on"]
        if not isinstance(dependencies, list) or len(dependencies) > 8 or any(
            isinstance(number, bool) or not isinstance(number, int) or number <= 0
            for number in dependencies
        ):
            raise ContractError("operation.depends_on must contain at most 8 positive Issue numbers")
        if len(set(dependencies)) != len(dependencies):
            raise ContractError("operation.depends_on contains duplicates")
        status = operation["status"]
        if status not in PLANNER_STATUSES:
            raise ContractError("operation.status is invalid")
        parsed.append(
            PlannerOperation(kind, issue, title, description, criterion, tuple(dependencies), check, status)
        )
    ready_issue = value["ready_issue"]
    if ready_issue is not None and (
        isinstance(ready_issue, bool) or not isinstance(ready_issue, int) or ready_issue <= 0
    ):
        raise ContractError("planner.ready_issue must be null or a positive integer")
    summary = _bounded_text(value["summary"], location="planner.summary", limit=2_000, allow_empty=True)
    return PlannerOutput(tuple(parsed), ready_issue, summary)


@dataclass(frozen=True)
class WorkerOutput:
    ready: bool
    summary: str
    failure_kind: str | None


def parse_worker_output(raw: str) -> WorkerOutput:
    value = strict_json_loads(raw, max_bytes=8_192)
    if not isinstance(value, dict):
        raise ContractError("worker output must be an object")
    require_fields(value, required={"ready", "summary", "failure_kind"}, location="worker")
    ready = value["ready"]
    if not isinstance(ready, bool):
        raise ContractError("worker.ready must be boolean")
    summary = _bounded_text(value["summary"], location="worker.summary", limit=4_000, allow_empty=True)
    failure_kind = value["failure_kind"]
    if failure_kind not in {None, "code", "blocked", "infrastructure"}:
        raise ContractError("worker.failure_kind is invalid")
    if ready and failure_kind is not None:
        raise ContractError("ready worker output cannot declare a failure_kind")
    if not ready and failure_kind is None:
        raise ContractError("non-ready worker output requires failure_kind")
    return WorkerOutput(ready, summary, failure_kind)


def status_from_labels(labels: Iterable[str]) -> str:
    selected = sorted(STATUS_LABELS & set(labels))
    if len(selected) != 1:
        raise ContractError("Work Item must have exactly one milestone-loop status Label")
    return selected[0].split(":", 1)[1]


def pr_contract_change(body: str, labels: Iterable[str]) -> bool:
    if not isinstance(body, str) or len(body.encode("utf-8")) > 32_768:
        raise ContractError("pull request body must be bounded text")
    matches = PR_CONTRACT_CHANGE_RE.findall(body)
    prefixed = re.findall(r"(?m)^Contract-Change:[^\r\n]*$", body)
    if len(matches) != 1 or len(prefixed) != 1:
        raise ContractError("pull request must contain exactly one Contract-Change metadata line")
    return "contract-change" in set(labels) or matches[0] == "true"


def verification_metadata_path() -> Path:
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    runner_temp = os.environ.get("RUNNER_TEMP", "")
    if (
        not runner_temp
        or re.fullmatch(r"[1-9][0-9]{0,19}", run_id) is None
        or re.fullmatch(r"[1-9][0-9]{0,9}", run_attempt) is None
    ):
        raise ContractError("candidate verification metadata identity is unavailable")
    return Path(runner_temp) / f"milestone-loop-pr-metadata-{run_id}-{run_attempt}.json"


ALLOWED_TRANSITIONS = {
    "ready": {"ready", "in-progress", "blocked", "superseded"},
    "in-progress": {"in-progress", "review", "blocked", "superseded"},
    "review": {"review", "in-progress", "completed", "blocked", "superseded"},
    "blocked": {"blocked", "ready", "superseded"},
    "completed": {"completed"},
    "superseded": {"superseded"},
}


def validate_transition(old: str, new: str) -> None:
    if new not in ALLOWED_TRANSITIONS.get(old, set()):
        raise ContractError(f"invalid status transition: {old} -> {new}")


def validate_acyclic(graph: Mapping[int, Sequence[int]]) -> None:
    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(node: int) -> None:
        if node in visiting:
            raise ContractError("Work Item dependencies contain a cycle")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph.get(node, ()):
            if dependency not in graph:
                raise ContractError(f"Work Item dependency #{dependency} does not exist")
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def verified_tree(base_sha: str, head_sha: str, tree_sha: str) -> str:
    for name, value in (("base_sha", base_sha), ("head_sha", head_sha), ("tree_sha", tree_sha)):
        if re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ContractError(f"{name} must be a full lowercase Git SHA")
    return hashlib.sha256(f"{base_sha}\0{head_sha}\0{tree_sha}".encode()).hexdigest()


def fixed_milestone_path(repo_root: Path, milestone: str) -> Path:
    if milestone not in {"m1", "m2", "m3", "m4"}:
        raise ContractError("milestone must be m1, m2, m3, or m4")
    return repo_root / "project" / "milestones" / milestone / "milestone.json"


def github_conclusion(status: str) -> str:
    try:
        return {"PASS": "success", "FAIL": "failure", "BLOCKED": "action_required"}[status]
    except KeyError as exc:
        raise ContractError("Gate status must be PASS, FAIL, or BLOCKED") from exc
