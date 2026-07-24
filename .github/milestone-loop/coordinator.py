from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from agent import AgentError, invoke_with_one_repair
from context_builder import WORK_ITEM_LABEL, build_context, work_items, write_context
from contracts import (
    STATUS_LABELS,
    ContractError,
    PlannerOperation,
    PlannerOutput,
    WorkItemContract,
    fixed_milestone_path,
    github_conclusion,
    milestone_criteria,
    parse_planner_output,
    parse_work_item,
    parse_worker_output,
    pr_contract_change,
    render_work_item,
    require_candidate_check,
    resolve_check,
    status_from_labels,
    validate_acyclic,
    validate_transition,
    verified_tree,
)
from github_api import MAX_ISSUE_COMMENTS, GitHubClient, GitHubError, collect_snapshot


CONTROL_LABEL = "milestone-loop:control"
CONTRACT_CHANGE_LABEL = "contract-change"
DISCOVERY_REPAIR_LABEL = "milestone-loop:m2-discovery-repair"
M2_DISCOVERY_REPAIR_CHECK = "repository.all"
M2_DISCOVERY_CHECK_NAME = "milestone-loop / m2-discovery"
CONTROL_TITLE_PREFIX = "[milestone-loop]"
WORK_ITEM_MARKER_RE = re.compile(r"<!-- milestone-loop-key: ([0-9a-f]{64}) -->")
PR_WORK_ITEM_RE = re.compile(r"(?m)^Work-Item: #([1-9][0-9]*)$")
PR_MILESTONE_RE = re.compile(r"(?m)^Milestone: (m[1-4])$")
CONTROL_RE = re.compile(
    r"\AAuthorization Lease: (`[^\r\n]+`)\r?\nNo-progress count: ([0-9]+)\Z"
)
VERIFICATION_RE = re.compile(r"<!-- milestone-loop-verification: (\{[^\r\n]+\}) -->")
FAILURE_RE = re.compile(r"<!-- milestone-loop-failure: (\{[^\r\n]+\}) -->")
DIAGNOSIS_REQUEST_RE = re.compile(r"<!-- milestone-loop-diagnosis-request: ([0-9a-f]{64}) -->")
DIAGNOSIS_COMPLETE_RE = re.compile(r"<!-- milestone-loop-diagnosis-complete: ([0-9a-f]{64}) -->")
WORKER_RETRY_REQUEST_RE = re.compile(r"<!-- milestone-loop-worker-retry-request: ([0-9a-f]{64}) -->")
WORKER_RETRY_COMPLETE_RE = re.compile(r"<!-- milestone-loop-worker-retry-complete: ([0-9a-f]{64}) -->")
M2_DISCOVERY_RECORD_RE = re.compile(r"<!-- milestone-loop-m2-discovery: (\{[^\r\n]+\}) -->")
M2_DISCOVERY_DIAGNOSIS_COMPLETE_RE = re.compile(
    r"<!-- milestone-loop-m2-discovery-diagnosis-complete: ([0-9a-f]{64}) -->"
)
M2_DISCOVERY_DISPATCH_RE = re.compile(
    r"<!-- milestone-loop-m2-discovery-dispatch: ([0-9a-f]{64}) -->"
)
M2_DISCOVERY_WORK_ITEM_RE = re.compile(r"(?m)^M2-Discovery-Fingerprint: ([0-9a-f]{64})$")
M2_DISCOVERY_METADATA_RE = re.compile(
    r"(?m)^M2-Discovery-(?:Fingerprint|Run|Tested-SHA|Failure-Code|Summary): [^\r\n]+$"
)
HUMAN_ACTION_RE = re.compile(r"<!-- milestone-loop-human-action: (\{[^\r\n]+\}) -->")
LEASE_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"
)
PROTECTED_PREFIXES = (
    ".github/CODEOWNERS",
    ".github/milestone-loop/",
    ".github/workflows/",
    "project/milestones/",
    "project/verification/",
    "project/catalog.json",
    "project/gate",
    "project/scripts/m2_candidate_discovery.py",
    "project/scripts/m2_performance_capture.py",
    "project/scripts/m2_performance_gate.py",
    "project/src/valkey_scale_lab/cli.py",
    "project/src/valkey_scale_lab/gates/",
    "project/src/valkey_scale_lab/runtime/docker_runtime.py",
    "project/src/valkey_scale_lab/scenarios/definitions/",
    "project/templates/configs/scale_50.yaml",
    "project/templates/configs/scale_200.yaml",
)
M2_DISCOVERY_REPAIR_PROTECTED_PREFIXES = (
    "project/scripts/m2_candidate_discovery.py",
    "project/scripts/m2_performance_capture.py",
    "project/src/valkey_scale_lab/runtime/docker_runtime.py",
)
M2_DISCOVERY_REPAIR_ALLOWED_PREFIXES = (
    "project/scripts/m2_candidate_discovery.py",
    "project/scripts/m2_performance_capture.py",
    "project/src/",
    "project/tests/",
)
M2_DISCOVERY_CRITERIA = {
    "formation": "performance.cluster-formation-experiment",
    "failover": "performance.automatic-failover-experiment",
}
M2_RELATIVE_CANDIDATE_PARAMETERS = (
    (
        "performance.cluster-formation-experiment",
        "real.local.m2-cluster-formation",
        "selected_strategy",
        ("manual_tree_meet_parallel_slots", "tree_meet_addslotsrange"),
    ),
    (
        "performance.automatic-failover-experiment",
        "real.local.m2-automatic-failover",
        "selected_timeout_ms",
        ("5000", "10000", "15000"),
    ),
    (
        "performance.stability-and-resource-safety",
        "real.local.m2-stability-resource",
        "selected_strategy",
        ("manual_tree_meet_parallel_slots", "tree_meet_addslotsrange"),
    ),
    (
        "performance.stability-and-resource-safety",
        "real.local.m2-stability-resource",
        "selected_timeout_ms",
        ("5000", "10000", "15000"),
    ),
)


class LoopBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class PlannedWrite:
    operation: PlannerOperation
    number: int | None
    title: str
    body: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class PlannerTransaction:
    writes: tuple[PlannedWrite, ...]
    ready_issue: int | None


@dataclass(frozen=True)
class ControlState:
    issue_number: int
    lease: Mapping[str, Any]
    no_progress_count: int


LABEL_SPECS = {
    WORK_ITEM_LABEL: ("1f6feb", "Managed Milestone Work Item"),
    CONTROL_LABEL: ("5319e7", "Milestone loop control Issue"),
    CONTRACT_CHANGE_LABEL: ("b60205", "Protected contract change requiring human review"),
    DISCOVERY_REPAIR_LABEL: ("7a3e9d", "Human-reviewed repair for trusted M2 discovery"),
    **{
        f"milestone-loop:{status}": (
            {
                "ready": "0e8a16",
                "in-progress": "fbca04",
                "blocked": "d93f0b",
                "review": "1d76db",
                "completed": "6f42c1",
                "superseded": "c5def5",
            }[status],
            f"Milestone Work Item status: {status}",
        )
        for status in ("ready", "in-progress", "blocked", "review", "completed", "superseded")
    },
}


def snapshot_fingerprint(snapshot: Mapping[str, Any]) -> str:
    selected = {
        "default_sha": snapshot.get("default_sha"),
        "milestone_number": snapshot.get("milestone_number"),
        "issues": snapshot.get("issues"),
        "pull_requests": snapshot.get("pull_requests"),
    }
    encoded = json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _trusted_comment_payloads(
    issue: Mapping[str, Any], pattern: re.Pattern[str]
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for comment in issue.get("comments", []):
        body = comment.get("body") if isinstance(comment, dict) else None
        if not isinstance(body, str) or comment.get("author") != "github-actions[bot]":
            continue
        match = pattern.search(body)
        if match is None:
            continue
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            payloads.append(value)
    return payloads


def _require_control_comment_capacity(
    control_issue: Mapping[str, Any], additions: int
) -> None:
    comments = control_issue.get("comments")
    if not isinstance(comments, list) or additions < 0:
        raise ContractError("Control Issue comment state is invalid")
    if len(comments) + additions > MAX_ISSUE_COMMENTS:
        raise LoopBlocked("Control Issue comment capacity is exhausted")


def _human_action_value(
    *, snapshot: Mapping[str, Any], state: str, target: str, sha: str
) -> dict[str, Any]:
    if state not in {
        "PR_REVIEW_REQUIRED",
        "REAL_AUTHORIZATION_REQUIRED",
        "HARD_BLOCKED",
        "M2_COMPLETE",
    }:
        raise ContractError("human-action state is invalid")
    value = {
        "version": 1,
        "milestone": str(snapshot.get("milestone")),
        "state": state,
        "target": target,
        "sha": sha,
    }
    value["key"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return value


def record_human_action_state(
    *,
    client: GitHubClient,
    snapshot: Mapping[str, Any],
    control: ControlState,
    state: str,
    target: str,
    sha: str,
    action: str,
    link: str,
    action_label: str = "open target",
) -> bool:
    milestone = snapshot.get("milestone")
    repository = snapshot.get("repository")
    if (
        state
        not in {
            "PR_REVIEW_REQUIRED",
            "REAL_AUTHORIZATION_REQUIRED",
            "HARD_BLOCKED",
            "M2_COMPLETE",
        }
        or not isinstance(milestone, str)
        or re.fullmatch(r"m[1-4]", milestone) is None
        or not isinstance(repository, str)
        or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,159}", target) is None
        or re.fullmatch(r"[0-9a-f]{40}", sha) is None
        or not isinstance(action, str)
        or not action
        or len(action) > 2000
        or not action.isprintable()
        or not isinstance(action_label, str)
        or not action_label
        or len(action_label) > 80
        or not action_label.isprintable()
        or not isinstance(link, str)
        or len(link) > 2000
        or not link.startswith(f"https://github.com/{repository}/")
        or not link.isprintable()
        or any(character.isspace() for character in link)
    ):
        raise ContractError("human-action record is invalid")
    value = _human_action_value(
        snapshot=snapshot, state=state, target=target, sha=sha
    )
    raw_control = client.api(f"issues/{control.issue_number}")
    if not isinstance(raw_control, dict) or raw_control.get("number") != control.issue_number:
        raise LoopBlocked("live Control Issue is missing before human-action recording")
    live_control = parse_control(raw_control, milestone)
    if (
        dict(live_control.lease) != dict(control.lease)
        or live_control.no_progress_count != control.no_progress_count
    ):
        raise LoopBlocked("Control Issue changed before human-action recording")
    raw_comments = client.api(
        f"issues/{control.issue_number}/comments?per_page={MAX_ISSUE_COMMENTS + 1}"
    )
    if not isinstance(raw_comments, list):
        raise GitHubError("cannot read Control Issue before human-action recording")
    if len(raw_comments) > MAX_ISSUE_COMMENTS:
        raise LoopBlocked("Control Issue comment history exceeds its authoritative bound")
    live = {
        "comments": [
            {
                "author": (comment.get("user") or {}).get("login")
                if isinstance(comment, dict) and isinstance(comment.get("user"), dict)
                else None,
                "body": comment.get("body") if isinstance(comment, dict) else None,
            }
            for comment in raw_comments
        ]
    }
    if any(
        payload.get("key") == value["key"]
        for payload in _trusted_comment_payloads(live, HUMAN_ACTION_RE)
    ):
        return False
    if len(raw_comments) >= MAX_ISSUE_COMMENTS:
        raise LoopBlocked("Control Issue comment capacity is exhausted")
    client.comment(
        control.issue_number,
        f"Human action required: **{state}**\n\n{action}\n\n"
        f"One action: [{action_label}]({link}).\n\n"
        "<!-- milestone-loop-human-action: "
        + json.dumps(value, sort_keys=True, separators=(",", ":"))
        + " -->",
    )
    return True


def _record_m2_discovery_hard_block(
    *,
    client: GitHubClient,
    snapshot: Mapping[str, Any],
    control: ControlState,
    record: Mapping[str, Any],
    action: str,
) -> None:
    repository = str(snapshot.get("repository", ""))
    run_id = str(record["run_id"])
    run_attempt = str(record["run_attempt"])
    record_human_action_state(
        client=client,
        snapshot=snapshot,
        control=control,
        state="HARD_BLOCKED",
        target=f"run:{run_id}:attempt:{run_attempt}",
        sha=str(record["tested_sha"]),
        action=action,
        link=f"https://github.com/{repository}/actions/runs/{run_id}/attempts/{run_attempt}",
    )


def _is_real_authorization_comment(comment: Mapping[str, Any]) -> bool:
    if not isinstance(comment, Mapping):
        return False
    if comment.get("author") != "github-actions[bot]":
        return False
    body = comment.get("body")
    if not isinstance(body, str):
        return False
    for match in HUMAN_ACTION_RE.finditer(body):
        try:
            record = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if (
            isinstance(record, dict)
            and record.get("version") == 1
            and record.get("state") == "REAL_AUTHORIZATION_REQUIRED"
        ):
            return True
    return False


def real_readiness_fingerprint(snapshot: Mapping[str, Any]) -> str:
    issues: list[dict[str, Any]] = []
    for raw in snapshot.get("issues", []):
        issue = dict(raw)
        if CONTROL_LABEL in issue.get("labels", []):
            issue["comments"] = [
                comment
                for comment in issue.get("comments", [])
                if not _is_real_authorization_comment(comment)
            ]
        issues.append(issue)
    selected = {
        "default_sha": snapshot.get("default_sha"),
        "milestone_number": snapshot.get("milestone_number"),
        "issues": issues,
        "pull_requests": snapshot.get("pull_requests"),
    }
    encoded = json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _record_human_action(
    client: GitHubClient,
    snapshot: Mapping[str, Any],
    control: ControlState,
    *,
    state: str,
    target: str,
    message: str,
    action_label: str,
    action_url: str,
) -> None:
    milestone = snapshot.get("milestone")
    default_sha = snapshot.get("default_sha")
    repository = snapshot.get("repository")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    server_url = os.environ.get("GITHUB_SERVER_URL", "")
    if (
        state not in {"REAL_AUTHORIZATION_REQUIRED", "HARD_BLOCKED"}
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,159}", target) is None
        or not isinstance(milestone, str)
        or re.fullmatch(r"m[1-4]", milestone) is None
        or not isinstance(default_sha, str)
        or re.fullmatch(r"[0-9a-f]{40}", default_sha) is None
        or not isinstance(repository, str)
        or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None
        or re.fullmatch(r"[1-9][0-9]{0,19}", run_id) is None
        or re.fullmatch(r"[1-9][0-9]{0,9}", run_attempt) is None
        or server_url != "https://github.com"
    ):
        raise LoopBlocked("workflow run identity is invalid for real authorization")
    record_human_action_state(
        client=client,
        snapshot=snapshot,
        control=control,
        state=state,
        target=target,
        sha=default_sha,
        action=message,
        action_label=action_label,
        link=action_url,
    )


def record_real_authorization_required(
    client: GitHubClient,
    snapshot: Mapping[str, Any],
    control: ControlState,
) -> None:
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    repository = snapshot.get("repository")
    server_url = os.environ.get("GITHUB_SERVER_URL", "")
    _record_human_action(
        client,
        snapshot,
        control,
        state="REAL_AUTHORIZATION_REQUIRED",
        target=f"run:{run_id}:attempt:{run_attempt}",
        message=(
            f"Real authorization is required for `{snapshot.get('milestone')}` at "
            f"`{snapshot.get('default_sha')}`."
        ),
        action_label="approve and deploy `valkey-real`",
        action_url=f"{server_url}/{repository}/actions/runs/{run_id}",
    )


def record_hard_blocked_lease(
    client: GitHubClient,
    snapshot: Mapping[str, Any],
    control: ControlState,
) -> None:
    repository = snapshot.get("repository")
    server_url = os.environ.get("GITHUB_SERVER_URL", "")
    status = str(control.lease.get("status"))
    _record_human_action(
        client,
        snapshot,
        control,
        state="HARD_BLOCKED",
        target=f"control:{control.issue_number}:{status}",
        message=(
            "Real authorization is blocked before Environment review because the "
            f"existing Authorization Lease is `{status}`."
        ),
        action_label="inspect the Control Issue",
        action_url=f"{server_url}/{repository}/issues/{control.issue_number}",
    )


def prepare_real_authorization(
    *,
    client: GitHubClient,
    repo_root: Path,
    milestone: str,
    entrypoint: str,
    control: ControlState,
) -> dict[str, Any]:
    if entrypoint not in {"milestone", "discovery"}:
        raise ContractError("real authorization entrypoint is invalid")
    snapshot = collect_snapshot(client, milestone)
    if _run(["git", "rev-parse", "HEAD"], cwd=repo_root) != snapshot.get("default_sha"):
        raise LoopBlocked("coordination checkout changed before real authorization preparation")
    control_issues = [
        issue
        for issue in snapshot.get("issues", [])
        if issue.get("number") == control.issue_number
        and CONTROL_LABEL in issue.get("labels", [])
    ]
    if len(control_issues) != 1:
        raise LoopBlocked("live Control Issue is missing before real authorization preparation")
    live_control = parse_control(control_issues[0], milestone)
    if live_control.lease.get("status") not in {"empty", "exhausted"}:
        record_hard_blocked_lease(client, snapshot, live_control)
        return {
            "status": "BLOCKED",
            "milestone": milestone,
            "reason": "authorization-lease",
        }
    readiness_sha256 = real_readiness_fingerprint(snapshot)
    record_real_authorization_required(client, snapshot, live_control)
    live = collect_snapshot(client, milestone)
    if (
        live.get("default_sha") != snapshot.get("default_sha")
        or real_readiness_fingerprint(live) != readiness_sha256
    ):
        raise LoopBlocked("live state changed while recording real authorization state")
    if _run(["git", "rev-parse", "HEAD"], cwd=repo_root) != live.get("default_sha"):
        raise LoopBlocked("coordination checkout is stale before real authorization")
    return {
        "status": "MILESTONE",
        "milestone": milestone,
        "default_sha": live["default_sha"],
        "entrypoint": entrypoint,
        "readiness_sha256": readiness_sha256,
    }
def _operation_key(milestone: str, operation: PlannerOperation) -> str:
    value = {
        "milestone": milestone,
        "title": operation.title,
        "criterion": operation.criterion,
        "depends_on": operation.depends_on,
        "check": operation.check,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _labels_with_status(labels: Sequence[str], status: str) -> tuple[str, ...]:
    preserved = [label for label in labels if label not in STATUS_LABELS]
    return tuple(sorted({*preserved, WORK_ITEM_LABEL, f"milestone-loop:{status}"}))


def prepare_planner_transaction(
    *,
    snapshot: Mapping[str, Any],
    output: PlannerOutput,
    milestone_document: Mapping[str, Any],
    catalog_document: Mapping[str, Any],
) -> PlannerTransaction:
    milestone = snapshot.get("milestone")
    if not isinstance(milestone, str):
        raise ContractError("snapshot milestone is invalid")
    criteria = milestone_criteria(milestone_document, milestone)
    items = work_items(snapshot)
    hypothetical: dict[int, dict[str, Any]] = {number: dict(item) for number, item in items.items()}
    create_keys = {
        match.group(1): item["number"]
        for item in items.values()
        for match in [WORK_ITEM_MARKER_RE.search(item.get("body", ""))]
        if match is not None
    }
    writes: list[PlannedWrite] = []
    used_updates: set[int] = set()
    virtual_number = -1
    for operation in output.operations:
        if operation.criterion not in criteria:
            raise ContractError(f"Planner references unknown Criterion {operation.criterion}")
        require_candidate_check(catalog_document, operation.check)
        if operation.status in {"in-progress", "review", "completed"}:
            raise ContractError(
                f"Planner cannot manufacture deterministic progress status {operation.status}"
            )
        contract = WorkItemContract(operation.criterion, operation.depends_on, operation.check)
        if operation.kind == "create":
            key = _operation_key(milestone, operation)
            existing_number = create_keys.get(key)
            if existing_number is not None:
                existing = items[existing_number]
                writes.append(
                    PlannedWrite(
                        operation,
                        existing_number,
                        operation.title or existing.get("title", ""),
                        existing.get("body", ""),
                        tuple(existing.get("labels", [])),
                    )
                )
                continue
            assert operation.title is not None and operation.description is not None
            body = render_work_item(operation.description, contract)
            body += f"\n\n<!-- milestone-loop-key: {key} -->"
            labels = _labels_with_status((), operation.status)
            writes.append(PlannedWrite(operation, None, operation.title, body, labels))
            hypothetical[virtual_number] = {
                "number": virtual_number,
                "title": operation.title,
                "body": body,
                "labels": list(labels),
                "state": "open",
                "contract": {
                    "criterion": contract.criterion,
                    "depends_on": list(contract.depends_on),
                    "check": contract.check,
                },
            }
            virtual_number -= 1
            continue
        assert operation.issue is not None
        if operation.issue in used_updates:
            raise ContractError(f"Planner updates Issue #{operation.issue} more than once")
        used_updates.add(operation.issue)
        if operation.issue not in items:
            raise ContractError(f"Planner update references unknown Work Item #{operation.issue}")
        current = items[operation.issue]
        old_status = status_from_labels(current.get("labels", []))
        validate_transition(old_status, operation.status)
        title = operation.title if operation.title is not None else current.get("title", "")
        if not isinstance(title, str) or not title:
            raise ContractError("updated Work Item title is invalid")
        if operation.description is None:
            old_contract = parse_work_item(current.get("body", ""))
            old_block = render_work_item("placeholder", old_contract).split("\n\n", 1)[1]
            description = current.get("body", "").split(f"\n\n{old_block}", 1)[0]
        else:
            description = operation.description
        body = render_work_item(description, contract)
        marker = WORK_ITEM_MARKER_RE.search(current.get("body", ""))
        if marker:
            body += f"\n\n{marker.group(0)}"
        if DISCOVERY_REPAIR_LABEL in current.get("labels", []):
            metadata = M2_DISCOVERY_METADATA_RE.findall(current.get("body", ""))
            if len(metadata) != 5:
                raise ContractError("M2 discovery repair metadata is incomplete")
            body += "\n\n" + "\n".join(metadata)
        labels = _labels_with_status(current.get("labels", []), operation.status)
        writes.append(PlannedWrite(operation, operation.issue, title, body, labels))
        hypothetical[operation.issue] = {
            **current,
            "title": title,
            "body": body,
            "labels": list(labels),
            "contract": {
                "criterion": contract.criterion,
                "depends_on": list(contract.depends_on),
                "check": contract.check,
            },
        }

    real_numbers = {number for number in hypothetical if number > 0}
    graph: dict[int, tuple[int, ...]] = {}
    for number, item in hypothetical.items():
        dependencies = tuple(item["contract"]["depends_on"])
        if any(dependency not in real_numbers for dependency in dependencies):
            raise ContractError(f"Work Item #{number} references a missing dependency")
        graph[number] = dependencies
    validate_acyclic(graph)
    ready = [
        number
        for number, item in hypothetical.items()
        if status_from_labels(item["labels"]) == "ready"
    ]
    if len(ready) > 1:
        raise ContractError(f"Planner transaction would leave multiple ready Work Items: {ready}")
    for ready_number in ready:
        incomplete = [
            dependency
            for dependency in graph[ready_number]
            if status_from_labels(hypothetical[dependency]["labels"]) != "completed"
        ]
        if incomplete:
            raise ContractError(f"ready Work Item has incomplete dependencies: {incomplete}")
    if output.ready_issue is not None:
        if output.ready_issue not in hypothetical or output.ready_issue <= 0:
            raise ContractError("planner.ready_issue must reference an existing Work Item")
        if ready != [output.ready_issue]:
            raise ContractError("planner.ready_issue must be the transaction's single ready Work Item")
    elif ready:
        if ready[0] > 0:
            raise ContractError("planner must select the single existing ready Work Item")
    return PlannerTransaction(tuple(writes), output.ready_issue)


def apply_planner_transaction(
    *,
    client: GitHubClient,
    original_snapshot: Mapping[str, Any],
    transaction: PlannerTransaction,
) -> None:
    live = collect_snapshot(client, str(original_snapshot["milestone"]))
    if snapshot_fingerprint(live) != snapshot_fingerprint(original_snapshot):
        raise LoopBlocked("live GitHub state changed before Planner writes; transaction rejected")
    for write in transaction.writes:
        if write.number is None:
            client.create_issue(
                title=write.title,
                body=write.body,
                labels=write.labels,
                milestone_number=int(original_snapshot["milestone_number"]),
            )
            continue
        current = next(
            (item for item in original_snapshot["issues"] if item.get("number") == write.number),
            None,
        )
        if current is None:
            raise LoopBlocked(f"Work Item #{write.number} vanished before write")
        desired_status = write.operation.status
        if desired_status in {"blocked", "superseded"}:
            for pr in original_snapshot.get("pull_requests", []):
                if (
                    PR_WORK_ITEM_RE.findall(pr.get("body", "")) == [str(write.number)]
                    and pr.get("state") == "open"
                ):
                    client.disable_auto_merge(pr["number"])
                    client.update_pull_request(
                        pr["number"],
                        body=pr.get("body", "") + f"\n\nLoop-State: {desired_status}\n",
                    )
                    if desired_status == "superseded":
                        client.update_pull_request(pr["number"], state="closed")
        client.update_issue(
            write.number,
            title=write.title,
            body=write.body,
            labels=write.labels,
        )


def empty_lease(milestone: str) -> dict[str, Any]:
    return {
        "version": 2,
        "milestone": milestone,
        "status": "empty",
        "nonce": "",
        "expires_at": "",
        "remaining": 0,
        "entrypoint": "",
        "default_sha": "",
        "run_id": "",
        "run_attempt": "",
    }


def render_control(lease: Mapping[str, Any], no_progress_count: int) -> str:
    return (
        "Authorization Lease: `"
        + json.dumps(dict(lease), sort_keys=True, separators=(",", ":"))
        + f"`\nNo-progress count: {no_progress_count}"
    )


def parse_control(issue: Mapping[str, Any], milestone: str) -> ControlState:
    body = issue.get("body")
    if not isinstance(body, str):
        raise ContractError("Control Issue body is invalid")
    match = CONTROL_RE.fullmatch(body)
    if match is None:
        raise ContractError("Control Issue may contain only Authorization Lease and no-progress count")
    raw_lease = match.group(1)[1:-1]
    try:
        lease = json.loads(raw_lease)
    except json.JSONDecodeError as exc:
        raise ContractError(f"Control Issue Authorization Lease is invalid JSON: {exc}") from exc
    legacy_fields = {"version", "milestone", "status", "nonce", "expires_at", "remaining"}
    invocation_fields = legacy_fields | {"entrypoint", "default_sha", "run_id", "run_attempt"}
    if not isinstance(lease, dict) or (
        (lease.get("version") == 1 and set(lease) != legacy_fields)
        or (lease.get("version") == 2 and set(lease) != invocation_fields)
        or lease.get("version") not in {1, 2}
    ):
        raise ContractError("Authorization Lease has invalid fields")
    if lease["milestone"] != milestone:
        raise ContractError("Authorization Lease version or milestone is invalid")
    if lease["status"] not in {"empty", "active", "exhausted", "revoked"}:
        raise ContractError("Authorization Lease status is invalid")
    if not isinstance(lease["nonce"], str) or len(lease["nonce"]) > 128:
        raise ContractError("Authorization Lease nonce is invalid")
    if not isinstance(lease["expires_at"], str) or len(lease["expires_at"]) > 64:
        raise ContractError("Authorization Lease expires_at is invalid")
    if isinstance(lease["remaining"], bool) or not isinstance(lease["remaining"], int) or not 0 <= lease["remaining"] <= 10:
        raise ContractError("Authorization Lease remaining must be between 0 and 10")
    status = lease["status"]
    if status == "empty":
        if lease["nonce"] or lease["expires_at"] or lease["remaining"] != 0:
            raise ContractError("empty Authorization Lease has state")
    else:
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", lease["nonce"])
            is None
            or LEASE_TIMESTAMP_RE.fullmatch(lease["expires_at"]) is None
        ):
            raise ContractError("Authorization Lease nonce or expiration is invalid")
        try:
            datetime.fromisoformat(lease["expires_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractError("Authorization Lease expiration is invalid") from exc
        if (status == "active" and lease["remaining"] < 1) or (
            status in {"exhausted", "revoked"} and lease["remaining"] != 0
        ):
            raise ContractError("Authorization Lease status and remaining count disagree")
    if lease["version"] == 2:
        if not all(isinstance(lease[field], str) for field in invocation_fields - legacy_fields):
            raise ContractError("Authorization Lease invocation fields are invalid")
        if lease["status"] == "empty":
            if (
                any(lease[field] for field in invocation_fields - legacy_fields)
                or lease["remaining"] != 0
            ):
                raise ContractError("empty Authorization Lease has invocation bindings")
        elif (
            lease["entrypoint"] not in {"milestone", "discovery"}
            or (lease["entrypoint"] == "discovery" and milestone != "m2")
            or re.fullmatch(r"[0-9a-f]{40}", lease["default_sha"]) is None
            or re.fullmatch(r"[1-9][0-9]{0,19}", lease["run_id"]) is None
            or re.fullmatch(r"[1-9][0-9]{0,9}", lease["run_attempt"]) is None
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", lease["nonce"]) is None
            or (lease["status"] == "active" and lease["remaining"] != 1)
            or (lease["status"] in {"exhausted", "revoked"} and lease["remaining"] != 0)
        ):
            raise ContractError("Authorization Lease invocation binding is invalid")
    number = issue.get("number")
    if not isinstance(number, int):
        raise ContractError("Control Issue number is invalid")
    return ControlState(number, lease, int(match.group(2)))


def ensure_control(client: GitHubClient, snapshot: Mapping[str, Any]) -> ControlState:
    for name, (color, description) in LABEL_SPECS.items():
        client.ensure_label(name, color, description)
    controls = [
        issue
        for issue in snapshot.get("issues", [])
        if CONTROL_LABEL in issue.get("labels", [])
    ]
    if not controls:
        number = client.create_issue(
            title=f"{CONTROL_TITLE_PREFIX} {snapshot['milestone']} control",
            body=render_control(empty_lease(str(snapshot["milestone"])), 0),
            labels=(CONTROL_LABEL,),
            milestone_number=int(snapshot["milestone_number"]),
        )
        live = client.api(f"issues/{number}")
        if not isinstance(live, dict):
            raise GitHubError("new Control Issue cannot be read")
        return parse_control(live, str(snapshot["milestone"]))
    if len(controls) != 1:
        raise ContractError("Milestone must have exactly one Control Issue")
    return parse_control(controls[0], str(snapshot["milestone"]))


def set_no_progress(client: GitHubClient, state: ControlState, count: int) -> None:
    if count < 0:
        raise ContractError("no-progress count cannot be negative")
    live_issue = client.api(f"issues/{state.issue_number}")
    if not isinstance(live_issue, dict):
        raise GitHubError("cannot re-read Control Issue before no-progress update")
    live_state = parse_control(live_issue, str(state.lease["milestone"]))
    if (
        dict(live_state.lease) != dict(state.lease)
        or live_state.no_progress_count != state.no_progress_count
    ):
        raise LoopBlocked("Control Issue changed before no-progress update")
    client.update_issue(state.issue_number, body=render_control(state.lease, count))


def load_trusted_documents(repo_root: Path, milestone: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = fixed_milestone_path(repo_root, milestone)
    try:
        milestone_document = json.loads(path.read_text(encoding="utf-8"))
        catalog_document = json.loads((repo_root / "project" / "catalog.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load trusted Milestone or Catalog: {exc}") from exc
    if not isinstance(milestone_document, dict) or not isinstance(catalog_document, dict):
        raise ContractError("trusted Milestone and Catalog must be JSON objects")
    return milestone_document, catalog_document


def m2_candidate_blockers(
    milestone_document: Mapping[str, Any], milestone: str
) -> tuple[str, ...]:
    if milestone != "m2":
        return ()
    expected = {
        (criterion_id, check_id, parameter): candidates
        for criterion_id, check_id, parameter, candidates in M2_RELATIVE_CANDIDATE_PARAMETERS
    }
    expected_parameter_names: dict[str, set[str]] = {}
    for _criterion_id, check_id, parameter in expected:
        expected_parameter_names.setdefault(check_id, set()).add(parameter)
    blockers: set[str] = set()
    occurrences: list[tuple[Any, Mapping[str, Any]]] = []
    criteria = milestone_document.get("criteria")
    if isinstance(criteria, list):
        for criterion in criteria:
            if not isinstance(criterion, Mapping):
                continue
            checks = criterion.get("check")
            if not isinstance(checks, list):
                continue
            for check in checks:
                if not isinstance(check, Mapping):
                    continue
                occurrences.append((criterion.get("id"), check))
    selected: dict[tuple[str, str], str] = {}
    for (criterion_id, check_id, parameter), candidates in expected.items():
        key = f"{check_id}.{parameter}"
        matching = [
            (bound_criterion, check)
            for bound_criterion, check in occurrences
            if check.get("id") == check_id
        ]
        if len(matching) != 1 or matching[0][0] != criterion_id:
            blockers.add(key)
            continue
        parameters = matching[0][1].get("parameters")
        value = parameters.get(parameter) if isinstance(parameters, Mapping) else None
        if (
            not isinstance(parameters, Mapping)
            or set(parameters) != expected_parameter_names[check_id]
            or not isinstance(value, str)
            or value not in candidates
        ):
            blockers.add(key)
            continue
        selected[(check_id, parameter)] = value
    consistency_pairs = (
        (
            ("real.local.m2-cluster-formation", "selected_strategy"),
            ("real.local.m2-stability-resource", "selected_strategy"),
        ),
        (
            ("real.local.m2-automatic-failover", "selected_timeout_ms"),
            ("real.local.m2-stability-resource", "selected_timeout_ms"),
        ),
    )
    for experiment, stability in consistency_pairs:
        if experiment in selected and stability in selected:
            if selected[experiment] != selected[stability]:
                blockers.add(f"{stability[0]}.{stability[1]}")
    return tuple(sorted(blockers))


def m2_discovery_eligible(
    milestone_document: Mapping[str, Any], milestone: str
) -> bool:
    """Recognize only the reviewed, unresolved M2 candidate binding."""
    if milestone != "m2":
        return False
    expected: dict[tuple[str, str], dict[str, str]] = {}
    for criterion_id, check_id, parameter, _candidates in M2_RELATIVE_CANDIDATE_PARAMETERS:
        expected.setdefault((criterion_id, check_id), {})[parameter] = "current-default"

    observed: dict[tuple[str, str], Mapping[str, Any]] = {}
    target_check_ids = {check_id for _criterion_id, check_id in expected}
    criteria = milestone_document.get("criteria")
    if not isinstance(criteria, list):
        return False
    for criterion in criteria:
        if not isinstance(criterion, Mapping):
            continue
        criterion_id = criterion.get("id")
        checks = criterion.get("check")
        if not isinstance(checks, list):
            continue
        for check in checks:
            if not isinstance(check, Mapping) or check.get("id") not in target_check_ids:
                continue
            key = (criterion_id, check.get("id"))
            parameters = check.get("parameters")
            if key not in expected or key in observed or not isinstance(parameters, Mapping):
                return False
            observed[key] = parameters
    return set(observed) == set(expected) and all(
        dict(observed[key]) == parameters for key, parameters in expected.items()
    )


def run_planner(
    *,
    repo_root: Path,
    runtime_root: Path,
    snapshot: Mapping[str, Any],
    milestone_document: Mapping[str, Any],
    global_audit: bool = False,
    diagnosis_issue: int | None = None,
    discovery_record: Mapping[str, Any] | None = None,
) -> PlannerOutput:
    runtime_root.mkdir(parents=True, exist_ok=True)
    context_path = runtime_root / "planner-context.json"
    output_path = runtime_root / "planner-output.json"
    diagnosis_item = (
        work_items(snapshot).get(diagnosis_issue) if diagnosis_issue is not None else None
    )
    discovery_retry = bool(
        diagnosis_item is not None
        and DISCOVERY_REPAIR_LABEL in diagnosis_item.get("labels", [])
    )
    write_context(
        context_path,
        build_context(
            repo_root=repo_root,
            snapshot=snapshot,
            milestone_document=milestone_document,
        ),
    )
    try:
        return invoke_with_one_repair(
            role="planner",
            cwd=repo_root,
            context_path=context_path,
            output_path=output_path,
            parser=parse_planner_output,
            wall_timeout=1800,
            silence_timeout=180,
            initial_instruction=(
                (
                    "This trusted M2 discovery result identifies one machine-repairable "
                    f"{discovery_record['failure_scope']} implementation/collection failure "
                    f"({discovery_record['failure_code']}). Create exactly one small ready "
                    f"product Work Item for Criterion {M2_DISCOVERY_CRITERIA[str(discovery_record['failure_scope'])]}. "
                    f"Use the fixed Check {M2_DISCOVERY_REPAIR_CHECK}. "
                    "Do not update existing Work Items, select candidates, change thresholds, "
                    "reinterpret safety/performance results, or modify Milestone acceptance."
                )
                if discovery_record is not None
                else (
                    (
                        f"This is a bounded retry diagnosis for M2 discovery repair Work Item "
                        f"#{diagnosis_issue}. Update only that same Work Item back to ready with "
                        "the same Criterion and Check. Do not create prerequisites or broaden its "
                        "scope, and do not change thresholds, candidates, safety rules, or acceptance."
                        if discovery_retry
                        else (
                            f"This is the one bounded failure diagnosis for Work Item #{diagnosis_issue}. "
                            "Only split that item, create a necessary prerequisite, adjust its dependencies, "
                            "or leave it blocked/superseded. Do not update any other existing Work Item."
                        )
                    )
                    if diagnosis_issue is not None
                    else (
                        "This is the single global no-progress audit at the first threshold. "
                        "Reassess whether the current Work Items are necessary, correctly split, "
                        "and dependency-complete without weakening any Criterion or Check."
                        if global_audit
                        else ""
                    )
                )
            ),
        )
    finally:
        context_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)


def _run(argv: Sequence[str], *, cwd: Path, env: Mapping[str, str] | None = None) -> str:
    process = subprocess.run(
        list(argv),
        cwd=cwd,
        env=None if env is None else dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        detail = (process.stdout + "\n" + process.stderr)[-4000:].strip()
        raise LoopBlocked(f"command failed ({' '.join(argv)}): {detail}")
    return process.stdout.strip()


def changed_paths(worktree: Path, base_sha: str) -> tuple[str, ...]:
    tracked = _run(["git", "diff", "--name-only", "-z", base_sha], cwd=worktree).split("\0")
    untracked = _run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=worktree
    ).split("\0")
    return tuple(sorted({path for path in [*tracked, *untracked] if path}))


def protected_changes(paths: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        path
        for path in paths
        if any(
            path.startswith(prefix) if prefix.endswith("/") else path == prefix
            for prefix in PROTECTED_PREFIXES
        )
    )


def _worktree(runtime_root: Path, repo_root: Path, sha: str) -> Path:
    path = runtime_root / "worker-worktree"
    if path.exists():
        _run(["git", "worktree", "remove", "--force", str(path)], cwd=repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "worktree", "add", "--force", "--detach", str(path), sha], cwd=repo_root)
    if not (path / ".git").exists():
        raise LoopBlocked("isolated worktree was not created")
    return path


def _cleanup_worktree(repo_root: Path, path: Path) -> None:
    if path.exists():
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(path)],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _restore_candidate_branch(
    worktree: Path,
    *,
    branch: str,
    pushed_sha: str,
    previous_sha: str,
) -> None:
    ref = f"refs/heads/{branch}"
    source = previous_sha if previous_sha else ""
    _run(
        [
            "git",
            "push",
            f"--force-with-lease={ref}:{pushed_sha}",
            "origin",
            f"{source}:{ref}",
        ],
        cwd=worktree,
        env=dict(os.environ),
    )


def _set_issue_status(client: GitHubClient, issue: Mapping[str, Any], status: str) -> None:
    labels = _labels_with_status(issue.get("labels", []), status)
    client.update_issue(int(issue["number"]), labels=labels)


def _find_item(snapshot: Mapping[str, Any], number: int) -> dict[str, Any]:
    items = work_items(snapshot)
    try:
        return items[number]
    except KeyError as exc:
        raise LoopBlocked(f"Work Item #{number} is absent") from exc


def _find_pr(snapshot: Mapping[str, Any], issue_number: int) -> dict[str, Any] | None:
    matches = [
        pr
        for pr in snapshot.get("pull_requests", [])
        if PR_WORK_ITEM_RE.findall(pr.get("body", "")) == [str(issue_number)]
    ]
    open_matches = [pr for pr in matches if pr.get("state") == "open"]
    if len(open_matches) > 1:
        raise LoopBlocked(f"Work Item #{issue_number} has multiple open PRs")
    if open_matches:
        return open_matches[0]
    merged = [pr for pr in matches if pr.get("merged_at")]
    return sorted(merged, key=lambda pr: pr["number"])[-1] if merged else None


def _failure_payload(kind: str, signature: str) -> str:
    value = {
        "version": 1,
        "kind": kind,
        "signature": signature,
        "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    return "<!-- milestone-loop-failure: " + json.dumps(value, sort_keys=True, separators=(",", ":")) + " -->"


def _failure_history(issue: Mapping[str, Any], kind: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for comment in issue.get("comments", []):
        body = comment.get("body") if isinstance(comment, dict) else None
        if not isinstance(body, str) or comment.get("author") != "github-actions[bot]":
            continue
        match = FAILURE_RE.search(body)
        if match is None:
            continue
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("kind") == kind:
            result.append(value)
    return result


def record_failure(
    client: GitHubClient,
    issue: Mapping[str, Any],
    *,
    kind: str,
    signature: str,
    detail: str,
) -> bool:
    history = _failure_history(issue, kind)
    client.comment(
        int(issue["number"]),
        f"Milestone loop recorded a bounded {kind} failure.\n\n{detail[:2000]}\n\n"
        + _failure_payload(kind, signature),
    )
    consecutive = 1
    for value in reversed(history):
        if value.get("signature") != signature:
            break
        consecutive += 1
    if kind == "code":
        return consecutive >= 2 or len(history) + 1 >= 3
    return consecutive >= 2


def request_failure_diagnosis(client: GitHubClient, issue_number: int, signature: str) -> None:
    client.comment(
        issue_number,
        f"Bounded failure diagnosis requested.\n\n<!-- milestone-loop-diagnosis-request: {signature} -->",
    )


def request_worker_retry(client: GitHubClient, issue_number: int, signature: str) -> None:
    token = hashlib.sha256(
        f"{signature}\0{datetime.now(timezone.utc).isoformat()}".encode("utf-8")
    ).hexdigest()
    client.comment(
        issue_number,
        f"One direct Worker retry requested.\n\n<!-- milestone-loop-worker-retry-request: {token} -->",
    )


def pending_worker_retry(snapshot: Mapping[str, Any]) -> tuple[int, str] | None:
    pending: list[tuple[int, str]] = []
    for number, item in work_items(snapshot).items():
        if status_from_labels(item.get("labels", [])) != "ready":
            continue
        requested: list[str] = []
        completed: set[str] = set()
        for comment in item.get("comments", []):
            body = comment.get("body") if isinstance(comment, dict) else None
            if not isinstance(body, str) or comment.get("author") != "github-actions[bot]":
                continue
            requested.extend(WORKER_RETRY_REQUEST_RE.findall(body))
            completed.update(WORKER_RETRY_COMPLETE_RE.findall(body))
        outstanding = [token for token in requested if token not in completed]
        if outstanding:
            pending.append((number, outstanding[-1]))
    if len(pending) > 1:
        raise LoopBlocked("multiple Work Items request a direct Worker retry")
    return pending[0] if pending else None


def pending_failure_diagnosis(snapshot: Mapping[str, Any]) -> tuple[int, str] | None:
    pending: list[tuple[int, str]] = []
    for number, item in work_items(snapshot).items():
        requested: list[str] = []
        completed: set[str] = set()
        for comment in item.get("comments", []):
            body = comment.get("body") if isinstance(comment, dict) else None
            if not isinstance(body, str) or comment.get("author") != "github-actions[bot]":
                continue
            requested.extend(DIAGNOSIS_REQUEST_RE.findall(body))
            completed.update(DIAGNOSIS_COMPLETE_RE.findall(body))
        outstanding = [signature for signature in requested if signature not in completed]
        if outstanding:
            pending.append((number, outstanding[-1]))
    if len(pending) > 1:
        raise LoopBlocked("multiple Work Items request failure diagnosis")
    return pending[0] if pending else None


def pending_m2_discovery_diagnosis(snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
    controls = [
        issue
        for issue in snapshot.get("issues", [])
        if CONTROL_LABEL in issue.get("labels", [])
    ]
    if len(controls) != 1:
        raise LoopBlocked("Milestone must have exactly one Control Issue")
    control = controls[0]
    completed: set[str] = set()
    for comment in control.get("comments", []):
        body = comment.get("body") if isinstance(comment, dict) else None
        if not isinstance(body, str) or comment.get("author") != "github-actions[bot]":
            continue
        completed.update(M2_DISCOVERY_DIAGNOSIS_COMPLETE_RE.findall(body))
    marked_items: dict[str, int] = {}
    for number, item in work_items(snapshot).items():
        if DISCOVERY_REPAIR_LABEL not in item.get("labels", []):
            continue
        for fingerprint in M2_DISCOVERY_WORK_ITEM_RE.findall(item.get("body", "")):
            if fingerprint in marked_items:
                raise LoopBlocked("multiple Work Items claim one M2 discovery failure")
            marked_items[fingerprint] = number
    pending: list[dict[str, Any]] = []
    for value in _trusted_comment_payloads(control, M2_DISCOVERY_RECORD_RE):
        if (
            value.get("version") != 1
            or value.get("milestone") != "m2"
            or value.get("disposition") != "REPAIRABLE_IMPLEMENTATION"
            or value.get("failure_scope") not in M2_DISCOVERY_CRITERIA
            or re.fullmatch(r"[0-9a-f]{64}", str(value.get("failure_fingerprint", ""))) is None
            or re.fullmatch(r"[0-9a-f]{40}", str(value.get("tested_sha", ""))) is None
        ):
            continue
        if value["failure_fingerprint"] not in completed:
            pending_value = dict(value)
            if value["failure_fingerprint"] in marked_items:
                pending_value["existing_issue"] = marked_items[value["failure_fingerprint"]]
            pending.append(pending_value)
    if len(pending) > 1:
        raise LoopBlocked("multiple M2 discovery failures request diagnosis")
    return pending[0] if pending else None


def validate_m2_discovery_diagnosis(
    transaction: PlannerTransaction, *, record: Mapping[str, Any]
) -> PlannerTransaction:
    if len(transaction.writes) != 1:
        raise ContractError("M2 discovery diagnosis must create exactly one Work Item")
    write = transaction.writes[0]
    expected_criterion = M2_DISCOVERY_CRITERIA.get(str(record.get("failure_scope")))
    if (
        write.operation.kind != "create"
        or write.number is not None
        or write.operation.status != "ready"
        or write.operation.criterion != expected_criterion
        or write.operation.check != M2_DISCOVERY_REPAIR_CHECK
        or write.operation.depends_on
        or transaction.ready_issue is not None
    ):
        raise ContractError(
            "M2 discovery diagnosis must create one ready Work Item for the affected Criterion"
        )
    fingerprint = str(record["failure_fingerprint"])
    diagnostic = (
        f"\n\nM2-Discovery-Fingerprint: {fingerprint}\n"
        f"M2-Discovery-Run: {record['run_id']} attempt {record['run_attempt']}\n"
        f"M2-Discovery-Tested-SHA: {record['tested_sha']}\n"
        f"M2-Discovery-Failure-Code: {record['failure_code']}\n"
        f"M2-Discovery-Summary: {str(record.get('summary', ''))[:1000]}"
    )
    marked = replace(
        write,
        body=write.body + diagnostic,
        labels=tuple(sorted({*write.labels, DISCOVERY_REPAIR_LABEL})),
    )
    return PlannerTransaction((marked,), None)


def _validated_m2_discovery_repair(
    issue: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> dict[str, Any] | None:
    if DISCOVERY_REPAIR_LABEL not in issue.get("labels", []):
        return None
    matches = M2_DISCOVERY_WORK_ITEM_RE.findall(issue.get("body", ""))
    if len(matches) != 1 or snapshot.get("milestone") != "m2":
        raise LoopBlocked("M2 discovery repair Work Item marker is invalid")
    fingerprint = matches[0]
    controls = [
        item
        for item in snapshot.get("issues", [])
        if CONTROL_LABEL in item.get("labels", [])
    ]
    if len(controls) != 1:
        raise LoopBlocked("Milestone must have exactly one Control Issue")
    records = [
        value
        for value in _trusted_comment_payloads(controls[0], M2_DISCOVERY_RECORD_RE)
        if value.get("failure_fingerprint") == fingerprint
        and value.get("disposition") == "REPAIRABLE_IMPLEMENTATION"
    ]
    completed = {
        marker
        for comment in controls[0].get("comments", [])
        if isinstance(comment, dict)
        and comment.get("author") == "github-actions[bot]"
        and isinstance(comment.get("body"), str)
        for marker in M2_DISCOVERY_DIAGNOSIS_COMPLETE_RE.findall(comment["body"])
    }
    if (
        len(records) != 1
        or records[0].get("tested_sha") != snapshot.get("default_sha")
        or fingerprint not in completed
    ):
        raise LoopBlocked("M2 discovery repair is not bound to a current trusted diagnosis")
    record = records[0]
    contract = parse_work_item(issue.get("body", ""))
    expected_metadata = [
        f"M2-Discovery-Fingerprint: {record['failure_fingerprint']}",
        f"M2-Discovery-Run: {record['run_id']} attempt {record['run_attempt']}",
        f"M2-Discovery-Tested-SHA: {record['tested_sha']}",
        f"M2-Discovery-Failure-Code: {record['failure_code']}",
        f"M2-Discovery-Summary: {str(record.get('summary', ''))[:1000]}",
    ]
    if (
        contract.criterion != M2_DISCOVERY_CRITERIA.get(str(record.get("failure_scope")))
        or contract.check != M2_DISCOVERY_REPAIR_CHECK
        or contract.depends_on
        or M2_DISCOVERY_METADATA_RE.findall(issue.get("body", "")) != expected_metadata
    ):
        raise LoopBlocked("M2 discovery repair Work Item no longer matches its trusted record")
    return record


def trusted_m2_discovery_repair_pr(
    snapshot: Mapping[str, Any], *, pr_number: int, head_sha: str
) -> bool:
    matches = [
        pr
        for pr in snapshot.get("pull_requests", [])
        if pr.get("number") == pr_number
        and pr.get("state") == "open"
        and pr.get("head_sha") == head_sha
    ]
    if len(matches) != 1 or snapshot.get("milestone") != "m2":
        return False
    pr = matches[0]
    if (
        CONTRACT_CHANGE_LABEL not in pr.get("labels", [])
        or not pr_contract_change(pr.get("body", ""), pr.get("labels", []))
    ):
        return False
    item_numbers = PR_WORK_ITEM_RE.findall(pr.get("body", ""))
    fingerprints = M2_DISCOVERY_WORK_ITEM_RE.findall(pr.get("body", ""))
    if len(item_numbers) != 1 or len(fingerprints) != 1:
        return False
    issue = _find_item(snapshot, int(item_numbers[0]))
    record = _validated_m2_discovery_repair(issue, snapshot)
    return (
        record is not None
        and record.get("failure_fingerprint") == fingerprints[0]
        and status_from_labels(issue.get("labels", [])) == "review"
    )


def validate_failure_diagnosis(
    transaction: PlannerTransaction,
    *,
    issue_number: int,
    snapshot: Mapping[str, Any],
) -> None:
    target = _find_item(snapshot, issue_number)
    target_contract = parse_work_item(target["body"])
    discovery_retry = DISCOVERY_REPAIR_LABEL in target.get("labels", [])
    if discovery_retry and (
        len(transaction.writes) != 1
        or transaction.writes[0].number != issue_number
        or transaction.writes[0].operation.kind != "update"
        or transaction.writes[0].operation.status != "ready"
        or transaction.writes[0].operation.check != M2_DISCOVERY_REPAIR_CHECK
        or transaction.writes[0].operation.depends_on
        or DISCOVERY_REPAIR_LABEL not in transaction.writes[0].labels
        or len(M2_DISCOVERY_WORK_ITEM_RE.findall(transaction.writes[0].body)) != 1
    ):
        raise ContractError(
            "M2 discovery retry diagnosis must return the same marked Work Item to ready"
        )
    for write in transaction.writes:
        if write.number is not None and write.number != issue_number:
            raise ContractError("failure diagnosis cannot update another existing Work Item")
        if write.operation.criterion != target_contract.criterion:
            raise ContractError("failure diagnosis cannot move work to another Criterion")
        if write.number == issue_number and write.operation.check != target_contract.check:
            raise ContractError("failure diagnosis cannot replace the failed Work Item Check")


def run_worker(
    *,
    client: GitHubClient,
    repo_root: Path,
    runtime_root: Path,
    snapshot: Mapping[str, Any],
    milestone_document: Mapping[str, Any],
    issue_number: int,
) -> str:
    issue = _find_item(snapshot, issue_number)
    discovery_record = _validated_m2_discovery_repair(issue, snapshot)
    if status_from_labels(issue.get("labels", [])) != "ready":
        raise LoopBlocked(f"Work Item #{issue_number} is no longer ready")
    base_sha = str(snapshot["default_sha"])
    live = collect_snapshot(client, str(snapshot["milestone"]))
    live_issue = _find_item(live, issue_number)
    if live.get("default_sha") != base_sha or status_from_labels(live_issue.get("labels", [])) != "ready":
        raise LoopBlocked("live state changed before Worker start")
    _set_issue_status(client, live_issue, "in-progress")
    refreshed = collect_snapshot(client, str(snapshot["milestone"]))
    issue = _find_item(refreshed, issue_number)
    discovery_record = _validated_m2_discovery_repair(issue, refreshed)
    worktree = _worktree(runtime_root, repo_root, base_sha)
    context_path = runtime_root / "worker-context.json"
    output_path = runtime_root / "worker-output.json"
    try:
        write_context(
            context_path,
            build_context(
                repo_root=repo_root,
                snapshot=refreshed,
                milestone_document=milestone_document,
                issue_number=issue_number,
            ),
        )
        try:
            output = invoke_with_one_repair(
                role="worker",
                cwd=worktree,
                context_path=context_path,
                output_path=output_path,
                parser=parse_worker_output,
                wall_timeout=3600,
                silence_timeout=300,
                initial_instruction=(
                    "This is a trusted M2 discovery repair that will become a human-reviewed "
                    "Contract Change. You may change only the smallest necessary files under "
                    "project/scripts, project/src, and project/tests. The only protected files "
                    "you may touch are m2_candidate_discovery.py, m2_performance_capture.py, "
                    "and runtime/docker_runtime.py. Do not change m2_performance_gate.py, "
                    "Milestone criteria, candidates, thresholds, Gate/Catalog/verification, "
                    "workflow/control-plane code, or reinterpret a genuine performance or "
                    "safety failure as an implementation defect."
                    if discovery_record is not None
                    else ""
                ),
            )
        except AgentError as exc:
            client.comment(issue_number, f"Worker protocol or timeout BLOCKED: {str(exc)[:2000]}")
            _set_issue_status(client, issue, "blocked")
            return "BLOCKED"
        if not output.ready:
            if output.failure_kind == "blocked":
                client.comment(issue_number, f"Worker reported BLOCKED: {output.summary[:2000]}")
                _set_issue_status(client, issue, "blocked")
                return "BLOCKED"
            signature_source = (
                f"code\0{output.summary}"
                if output.failure_kind == "code"
                else "infrastructure"
            )
            signature = hashlib.sha256(signature_source.encode()).hexdigest()
            stop = record_failure(
                client,
                issue,
                kind="code" if output.failure_kind == "code" else "infrastructure",
                signature=signature,
                detail=output.summary,
            )
            _set_issue_status(client, issue, "blocked" if stop else "ready")
            if stop:
                if output.failure_kind == "code":
                    request_failure_diagnosis(client, issue_number, signature)
                    return "DIAGNOSE"
                return "BLOCKED"
            request_worker_retry(client, issue_number, signature)
            return "RETRY"
        current_head = _run(["git", "rev-parse", "HEAD"], cwd=worktree)
        if current_head != base_sha:
            raise LoopBlocked("Worker changed Git history; candidate rejected")
        paths = changed_paths(worktree, base_sha)
        if not paths:
            stop = record_failure(
                client,
                issue,
                kind="code",
                signature=hashlib.sha256(b"worker-ready-without-change").hexdigest(),
                detail="Worker declared ready without a candidate change.",
            )
            _set_issue_status(client, issue, "blocked" if stop else "ready")
            return "DIAGNOSE" if stop else "RETRY"
        protected = protected_changes(paths)
        if discovery_record is not None:
            if any(
                not any(
                    path.startswith(prefix) if prefix.endswith("/") else path == prefix
                    for prefix in M2_DISCOVERY_REPAIR_ALLOWED_PREFIXES
                )
                for path in paths
            ):
                client.comment(issue_number, "M2 discovery repair changed a path outside product code/tests; BLOCKED.")
                _set_issue_status(client, issue, "blocked")
                return "BLOCKED"
            forbidden_protected = tuple(
                path
                for path in protected
                if not any(
                    path.startswith(prefix) if prefix.endswith("/") else path == prefix
                    for prefix in M2_DISCOVERY_REPAIR_PROTECTED_PREFIXES
                )
            )
            if forbidden_protected:
                client.comment(
                    issue_number,
                    f"M2 discovery repair touched forbidden protected contracts: {list(forbidden_protected)}",
                )
                _set_issue_status(client, issue, "blocked")
                return "BLOCKED"
        elif protected:
            client.comment(issue_number, f"Worker candidate touched protected contracts: {list(protected)}")
            _set_issue_status(client, issue, "blocked")
            return "BLOCKED"
        live = collect_snapshot(client, str(snapshot["milestone"]))
        live_issue = _find_item(live, issue_number)
        if live.get("default_sha") != base_sha or status_from_labels(live_issue.get("labels", [])) != "in-progress":
            raise LoopBlocked("live state changed before candidate commit")
        branch = f"codex/milestone-loop-{snapshot['milestone']}-issue-{issue_number}"
        existing_before_push = _find_pr(live, issue_number)
        previous_remote_sha = ""
        if existing_before_push is not None and existing_before_push.get("state") == "open":
            candidate_sha = existing_before_push.get("head_sha")
            if not isinstance(candidate_sha, str) or re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is None:
                raise LoopBlocked("existing candidate PR head SHA is invalid")
            previous_remote_sha = candidate_sha
        _run(["git", "add", "-A"], cwd=worktree)
        _run(
            [
                "git",
                "-c",
                "user.name=milestone-loop",
                "-c",
                "user.email=milestone-loop@users.noreply.github.com",
                "commit",
                "-m",
                f"work-item: #{issue_number} {issue.get('title', '')}"[:240],
            ],
            cwd=worktree,
        )
        head_sha = _run(["git", "rev-parse", "HEAD"], cwd=worktree)
        push_env = dict(os.environ)
        _run(
            [
                "git",
                "push",
                f"--force-with-lease=refs/heads/{branch}:{previous_remote_sha}",
                "origin",
                f"HEAD:refs/heads/{branch}",
            ],
            cwd=worktree,
            env=push_env,
        )
        live = collect_snapshot(client, str(snapshot["milestone"]))
        live_issue = _find_item(live, issue_number)
        if live.get("default_sha") != base_sha or status_from_labels(live_issue.get("labels", [])) != "in-progress":
            _restore_candidate_branch(
                worktree,
                branch=branch,
                pushed_sha=head_sha,
                previous_sha=previous_remote_sha,
            )
            raise LoopBlocked("live state changed before PR creation")
        contract = parse_work_item(live_issue["body"])
        body = (
            f"Work-Item: #{issue_number}\n"
            f"Milestone: {snapshot['milestone']}\n"
            f"Base-SHA: {base_sha}\n"
            f"Head-SHA: {head_sha}\n"
            f"Check: {contract.check}\n"
            f"Contract-Change: {'true' if discovery_record is not None else 'false'}\n"
            + (
                f"M2-Discovery-Fingerprint: {discovery_record['failure_fingerprint']}\n"
                f"M2-Discovery-Run: {discovery_record['run_id']} attempt {discovery_record['run_attempt']}\n"
                if discovery_record is not None
                else ""
            )
        )
        existing = _find_pr(live, issue_number)
        if existing is not None and existing.get("state") == "open":
            client.update_pull_request(int(existing["number"]), body=body)
            pr_number = int(existing["number"])
        else:
            pr_number = client.create_pull_request(
                title=f"[{snapshot['milestone']}] #{issue_number} {live_issue.get('title', '')}"[:240],
                body=body,
                head=branch,
                base=str(snapshot["default_branch"]),
            )
        client.update_issue(
            pr_number,
            labels=(
                (WORK_ITEM_LABEL, CONTRACT_CHANGE_LABEL)
                if discovery_record is not None
                else (WORK_ITEM_LABEL,)
            ),
        )
        client.api(
            f"issues/{pr_number}",
            method="PATCH",
            input_value={"milestone": int(snapshot["milestone_number"])},
        )
        _set_issue_status(client, live_issue, "review")
        if discovery_record is not None:
            control = ensure_control(client, live)
            repository = str(live.get("repository", ""))
            record_human_action_state(
                client=client,
                snapshot=live,
                control=control,
                state="PR_REVIEW_REQUIRED",
                target=f"pr:{pr_number}:{head_sha}",
                sha=head_sha,
                action="Review and merge this M2 discovery repair Contract Change.",
                link=f"https://github.com/{repository}/pull/{pr_number}",
            )
        return "WAIT_PR"
    finally:
        context_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        _cleanup_worktree(repo_root, worktree)


def verification_record(pr: Mapping[str, Any]) -> Mapping[str, Any] | None:
    records: list[Mapping[str, Any]] = []
    for comment in pr.get("comments", []):
        body = comment.get("body") if isinstance(comment, dict) else None
        if not isinstance(body, str) or comment.get("author") != "github-actions[bot]":
            continue
        match = VERIFICATION_RE.search(body)
        if match is None:
            continue
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records[-1] if records else None


def reconcile_review(
    client: GitHubClient,
    snapshot: Mapping[str, Any],
    control: ControlState,
) -> tuple[str, ControlState]:
    items = work_items(snapshot)
    progressed = False
    for number, issue in items.items():
        if status_from_labels(issue.get("labels", [])) != "review":
            continue
        pr = _find_pr(snapshot, number)
        if pr is None:
            raise LoopBlocked(f"review Work Item #{number} has no PR")
        if pr.get("merged_at"):
            record = verification_record(pr)
            expected = None
            contract = parse_work_item(issue["body"])
            contract_change = pr_contract_change(
                pr.get("body", ""),
                pr.get("labels", []),
            )
            common_fields = {
                "version",
                "base_sha",
                "head_sha",
                "tree_sha",
                "verified_tree",
                "baseline",
                "work_item_check",
                "status",
            }
            modern_record = (
                isinstance(record, dict)
                and set(record) == common_fields | {"work_item", "contract_change"}
                and record.get("work_item") == number
                and record.get("contract_change") is contract_change
            )
            legacy_record = isinstance(record, dict) and set(record) == common_fields
            if (
                (modern_record or legacy_record)
                and record.get("version") == 1
                and record.get("status") == "PASS"
                and record.get("base_sha") == pr.get("base_sha")
                and record.get("head_sha") == pr.get("head_sha")
                and record.get("tree_sha") == pr.get("merge_tree_sha")
                and record.get("baseline") == "repository.all"
                and record.get("work_item_check")
                == ("repository.all" if contract_change else contract.check)
            ):
                try:
                    expected = verified_tree(
                        str(record["base_sha"]),
                        str(record["head_sha"]),
                        str(record["tree_sha"]),
                    )
                except ContractError:
                    expected = None
            if (
                record is None
                or record.get("verified_tree") != expected
            ):
                _set_issue_status(client, issue, "blocked")
                client.comment(number, f"Merged PR #{pr['number']} did not preserve its verified tree; BLOCKED.")
                return "BLOCKED", control
            _set_issue_status(client, issue, "completed")
            client.comment(number, f"Accepted implementation progress merged in PR #{pr['number']}.")
            progressed = True
            continue
        if pr.get("state") != "open":
            _set_issue_status(client, issue, "ready")
            continue
        matching_checks = [
            item
            for item in pr.get("checks", [])
            if item.get("name") == "milestone-loop / candidate"
            and item.get("app") == "github-actions"
            and isinstance(item.get("id"), int)
        ]
        check = max(matching_checks, key=lambda item: item["id"], default=None)
        if check is None or check.get("status") != "completed":
            return "WAIT_PR", control
        conclusion = check.get("conclusion")
        if conclusion == "action_required":
            client.disable_auto_merge(int(pr["number"]))
            _set_issue_status(client, issue, "blocked")
            return "BLOCKED", control
        if conclusion != "success":
            signature = hashlib.sha256(
                json.dumps(
                    {
                        "name": check.get("name"),
                        "conclusion": conclusion,
                        "summary": check.get("summary"),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            stop = record_failure(
                client,
                issue,
                kind="code",
                signature=signature,
                detail=f"Candidate Check concluded {conclusion}",
            )
            _set_issue_status(client, issue, "blocked" if stop else "ready")
            if stop:
                request_failure_diagnosis(client, number, signature)
            return ("DIAGNOSE" if stop else "RETRY"), control
        record = verification_record(pr)
        if record is None:
            raise LoopBlocked("successful candidate Check has no trusted verification record")
        required = {
            "version",
            "base_sha",
            "head_sha",
            "tree_sha",
            "verified_tree",
            "baseline",
            "work_item_check",
            "work_item",
            "contract_change",
            "status",
        }
        if (
            set(record) != required
            or record.get("status") != "PASS"
        ):
            raise LoopBlocked("candidate verification record has invalid fields or status")
        expected_tree = verified_tree(
            str(record["base_sha"]), str(record["head_sha"]), str(record["tree_sha"])
        )
        contract = parse_work_item(issue["body"])
        contract_change = pr_contract_change(
            pr.get("body", ""),
            pr.get("labels", []),
        )
        expected_work_item_check = "repository.all" if contract_change else contract.check
        if (
            record.get("base_sha") != snapshot.get("default_sha")
            or record.get("head_sha") != pr.get("head_sha")
            or record.get("tree_sha") != pr.get("head_tree_sha")
            or record.get("verified_tree") != expected_tree
            or record.get("baseline") != "repository.all"
            or record.get("work_item_check") != expected_work_item_check
            or record.get("work_item") != number
            or record.get("contract_change") is not contract_change
        ):
            client.disable_auto_merge(int(pr["number"]))
            _set_issue_status(client, issue, "ready")
            return "RETRY", control
        if contract_change:
            repository = str(snapshot.get("repository", ""))
            record_human_action_state(
                client=client,
                snapshot=snapshot,
                control=control,
                state="PR_REVIEW_REQUIRED",
                target=f"pr:{pr['number']}:{pr.get('head_sha', '')}",
                sha=str(pr.get("head_sha", "")),
                action="Review and merge this protected Contract Change.",
                link=f"https://github.com/{repository}/pull/{pr['number']}",
            )
            return "HUMAN_REVIEW", control
        if os.environ.get("MILESTONE_LOOP_AUTO_MERGE", "false").lower() != "true":
            return "HUMAN_REVIEW", control
        live = collect_snapshot(client, str(snapshot["milestone"]))
        live_pr = _find_pr(live, number)
        live_issue = _find_item(live, number)
        if (
            live.get("default_sha") != snapshot.get("default_sha")
            or live_pr is None
            or live_pr.get("head_sha") != record["head_sha"]
            or live_pr.get("head_tree_sha") != record["tree_sha"]
            or status_from_labels(live_issue.get("labels", [])) != "review"
        ):
            raise LoopBlocked("live state changed before auto-merge enablement")
        client.merge_pull_request(
            int(pr["number"]),
            expected_head_sha=str(record["head_sha"]),
        )
        # GITHUB_TOKEN merges do not emit another workflow run; dispatch the
        # fresh-default reconciliation explicitly after the merge succeeds.
        client.dispatch(str(snapshot["milestone"]))
        return "WAIT_MERGE", control
    if progressed:
        set_no_progress(client, control, 0)
        return "PROGRESS", ControlState(control.issue_number, control.lease, 0)
    return "NONE", control


def coordinate(
    *,
    client: GitHubClient,
    repo_root: Path,
    runtime_root: Path,
    action: str,
    milestone: str,
) -> dict[str, Any]:
    if action not in {"start", "resume"}:
        raise ContractError("action must be start or resume")
    fixed_milestone_path(repo_root, milestone)
    milestone_document, catalog_document = load_trusted_documents(repo_root, milestone)
    snapshot = collect_snapshot(client, milestone)
    if _run(["git", "rev-parse", "HEAD"], cwd=repo_root) != snapshot.get(
        "default_sha"
    ):
        raise LoopBlocked("queued coordination checkout is not the live default SHA")
    control = ensure_control(client, snapshot)
    snapshot = collect_snapshot(client, milestone)
    review_action, control = reconcile_review(client, snapshot, control)
    if review_action in {"WAIT_PR", "WAIT_MERGE", "HUMAN_REVIEW", "BLOCKED"}:
        return {"status": review_action, "milestone": milestone}
    snapshot = collect_snapshot(client, milestone)
    diagnosis = pending_failure_diagnosis(snapshot)
    discovery_diagnosis = pending_m2_discovery_diagnosis(snapshot)
    if diagnosis is not None and discovery_diagnosis is not None:
        raise LoopBlocked("ordinary and M2 discovery diagnoses cannot run in the same round")
    if (
        discovery_diagnosis is not None
        and discovery_diagnosis.get("tested_sha") != snapshot.get("default_sha")
    ):
        _record_m2_discovery_hard_block(
            client=client,
            snapshot=snapshot,
            control=control,
            record=discovery_diagnosis,
            action="Review the stale M2 discovery diagnosis; it cannot run on the new default SHA.",
        )
        return {
            "status": "BLOCKED",
            "milestone": milestone,
            "reason": "stale-discovery-diagnosis",
        }
    if discovery_diagnosis is not None and isinstance(
        discovery_diagnosis.get("existing_issue"), int
    ):
        issue_number = int(discovery_diagnosis["existing_issue"])
        existing = _find_item(snapshot, issue_number)
        if (
            discovery_diagnosis.get("tested_sha") != snapshot.get("default_sha")
            or status_from_labels(existing.get("labels", [])) != "ready"
            or DISCOVERY_REPAIR_LABEL not in existing.get("labels", [])
        ):
            raise LoopBlocked("partial M2 discovery diagnosis cannot be resumed safely")
        client.comment(
            control.issue_number,
            "Recovered the bounded M2 discovery diagnosis Work Item.\n\n"
            "<!-- milestone-loop-m2-discovery-diagnosis-complete: "
            f"{discovery_diagnosis['failure_fingerprint']} -->",
        )
        snapshot = collect_snapshot(client, milestone)
        result = run_worker(
            client=client,
            repo_root=repo_root,
            runtime_root=runtime_root,
            snapshot=snapshot,
            milestone_document=milestone_document,
            issue_number=issue_number,
        )
        if result in {"WAIT_PR", "RETRY", "DIAGNOSE"}:
            next_count = control.no_progress_count + 1
            set_no_progress(client, control, next_count)
            if next_count >= 10:
                return {"status": "BLOCKED", "milestone": milestone, "reason": "no-progress"}
        return {"status": result, "milestone": milestone, "issue": issue_number}
    if review_action == "RETRY":
        ready = [
            number
            for number, item in work_items(snapshot).items()
            if status_from_labels(item.get("labels", [])) == "ready"
        ]
        if len(ready) != 1:
            raise LoopBlocked("retry reconciliation did not leave exactly one ready Work Item")
        result = run_worker(
            client=client,
            repo_root=repo_root,
            runtime_root=runtime_root,
            snapshot=snapshot,
            milestone_document=milestone_document,
            issue_number=ready[0],
        )
        if result in {"WAIT_PR", "RETRY", "DIAGNOSE"}:
            next_count = control.no_progress_count + 1
            set_no_progress(client, control, next_count)
            if next_count >= 10:
                return {"status": "BLOCKED", "milestone": milestone, "reason": "no-progress"}
        return {"status": result, "milestone": milestone, "issue": ready[0]}

    worker_retry = pending_worker_retry(snapshot)
    if worker_retry is not None:
        client.comment(
            worker_retry[0],
            "Direct Worker retry consumed.\n\n"
            f"<!-- milestone-loop-worker-retry-complete: {worker_retry[1]} -->",
        )
        result = run_worker(
            client=client,
            repo_root=repo_root,
            runtime_root=runtime_root,
            snapshot=snapshot,
            milestone_document=milestone_document,
            issue_number=worker_retry[0],
        )
        if result in {"WAIT_PR", "RETRY", "DIAGNOSE"}:
            next_count = control.no_progress_count + 1
            set_no_progress(client, control, next_count)
            if next_count >= 10:
                return {"status": "BLOCKED", "milestone": milestone, "reason": "no-progress"}
        return {"status": result, "milestone": milestone, "issue": worker_retry[0]}

    if control.no_progress_count >= 10:
        return {"status": "BLOCKED", "milestone": milestone, "reason": "no-progress"}
    try:
        planner_output = run_planner(
            repo_root=repo_root,
            runtime_root=runtime_root,
            snapshot=snapshot,
            milestone_document=milestone_document,
            global_audit=control.no_progress_count == 5 and discovery_diagnosis is None,
            diagnosis_issue=(
                diagnosis[0]
                if diagnosis is not None and discovery_diagnosis is None
                else None
            ),
            discovery_record=discovery_diagnosis,
        )
    except AgentError as exc:
        client.comment(control.issue_number, f"Planner protocol or timeout BLOCKED: {str(exc)[:2000]}")
        if discovery_diagnosis is not None:
            _record_m2_discovery_hard_block(
                client=client,
                snapshot=snapshot,
                control=control,
                record=discovery_diagnosis,
                action="Review the bounded Planner failure for this discovery diagnosis.",
            )
        return {"status": "BLOCKED", "milestone": milestone, "reason": "planner"}
    try:
        transaction = prepare_planner_transaction(
            snapshot=snapshot,
            output=planner_output,
            milestone_document=milestone_document,
            catalog_document=catalog_document,
        )
        if discovery_diagnosis is not None:
            transaction = validate_m2_discovery_diagnosis(
                transaction, record=discovery_diagnosis
            )
    except ContractError as exc:
        if discovery_diagnosis is None:
            raise
        client.comment(
            control.issue_number,
            f"M2 discovery diagnosis BLOCKED by deterministic validation: {str(exc)[:2000]}",
        )
        _record_m2_discovery_hard_block(
            client=client,
            snapshot=snapshot,
            control=control,
            record=discovery_diagnosis,
            action="Review the rejected M2 discovery diagnosis; it cannot be repaired safely.",
        )
        return {"status": "BLOCKED", "milestone": milestone, "reason": "discovery-diagnosis"}
    if diagnosis is not None:
        validate_failure_diagnosis(
            transaction,
            issue_number=diagnosis[0],
            snapshot=snapshot,
        )
    apply_planner_transaction(client=client, original_snapshot=snapshot, transaction=transaction)
    if diagnosis is not None:
        client.comment(
            diagnosis[0],
            "Bounded failure diagnosis applied.\n\n"
            f"<!-- milestone-loop-diagnosis-complete: {diagnosis[1]} -->",
        )
    snapshot = collect_snapshot(client, milestone)
    live_ready = [
        number
        for number, item in work_items(snapshot).items()
        if status_from_labels(item.get("labels", [])) == "ready"
    ]
    if len(live_ready) > 1:
        raise LoopBlocked("Planner writes left multiple live ready Work Items")
    if discovery_diagnosis is not None and len(live_ready) != 1:
        _record_m2_discovery_hard_block(
            client=client,
            snapshot=snapshot,
            control=control,
            record=discovery_diagnosis,
            action="Review the incomplete M2 discovery diagnosis transaction.",
        )
        return {
            "status": "BLOCKED",
            "milestone": milestone,
            "reason": "discovery-diagnosis-live-state",
        }
    if discovery_diagnosis is not None:
        client.comment(
            control.issue_number,
            "Bounded M2 discovery diagnosis created one repair Work Item.\n\n"
            "<!-- milestone-loop-m2-discovery-diagnosis-complete: "
            f"{discovery_diagnosis['failure_fingerprint']} -->",
        )
        snapshot = collect_snapshot(client, milestone)
        live_ready = [
            number
            for number, item in work_items(snapshot).items()
            if status_from_labels(item.get("labels", [])) == "ready"
        ]
        if len(live_ready) != 1:
            raise LoopBlocked("M2 discovery repair changed before Worker start")
    selected = transaction.ready_issue
    if selected is None and live_ready:
        selected = live_ready[0]
    if selected is not None and live_ready != [selected]:
        raise LoopBlocked("Planner selection differs from the live ready Work Item")
    if selected is not None:
        result = run_worker(
            client=client,
            repo_root=repo_root,
            runtime_root=runtime_root,
            snapshot=snapshot,
            milestone_document=milestone_document,
            issue_number=selected,
        )
        if result in {"WAIT_PR", "RETRY", "DIAGNOSE"}:
            next_count = control.no_progress_count + 1
            set_no_progress(client, control, next_count)
            if next_count >= 10:
                return {"status": "BLOCKED", "milestone": milestone, "reason": "no-progress"}
        return {"status": result, "milestone": milestone, "issue": selected}

    # Work Item labels are planning state; the fixed Milestone Gate remains authoritative.
    criteria = milestone_criteria(milestone_document, milestone)
    unbound = sorted(criterion for criterion, checks in criteria.items() if not checks)
    if unbound:
        client.comment(
            control.issue_number,
            "Milestone BLOCKED because Criteria lack bound Checks: " + ", ".join(unbound),
        )
        return {
            "status": "BLOCKED",
            "milestone": milestone,
            "reason": "unbound-criteria",
            "criteria": unbound,
        }
    for checks in criteria.values():
        for check_id in checks:
            resolve_check(catalog_document, check_id)
    candidate_blockers = m2_candidate_blockers(milestone_document, milestone)
    if candidate_blockers:
        if m2_discovery_eligible(milestone_document, milestone):
            return prepare_real_authorization(
                client=client,
                repo_root=repo_root,
                milestone=milestone,
                entrypoint="discovery",
                control=control,
            )
        client.comment(
            control.issue_number,
            "M2 Milestone BLOCKED before real authorization because relative-performance "
            "candidate parameters are missing, invalid, inconsistent, or resolve to the "
            "current baseline: "
            + ", ".join(candidate_blockers)
            + ". Select candidates only in a human-reviewed Contract Change after fresh, "
            "authorized discovery; the Planner cannot select them.",
        )
        return {
            "status": "BLOCKED",
            "milestone": milestone,
            "reason": "candidate-not-ready",
            "parameters": list(candidate_blockers),
        }
    return prepare_real_authorization(
        client=client,
        repo_root=repo_root,
        milestone=milestone,
        entrypoint="milestone",
        control=control,
    )


def milestone_from_pr_body(body: str) -> str:
    match = PR_MILESTONE_RE.search(body)
    if match is None:
        raise ContractError("PR body does not contain exactly one fixed Milestone line")
    if len(PR_MILESTONE_RE.findall(body)) != 1:
        raise ContractError("PR body contains multiple Milestone lines")
    return match.group(1)


def _ensure_m2_discovery_check(
    *,
    client: GitHubClient,
    tested_sha: str,
    dedup_key: str,
    status: str,
    summary: str,
) -> None:
    external_id = f"m2-discovery:{dedup_key}"
    check_name = quote(M2_DISCOVERY_CHECK_NAME, safe="")
    value = client.api(
        f"commits/{tested_sha}/check-runs?check_name={check_name}&filter=all&per_page=100"
    )
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("check_runs"), list)
        or not isinstance(value.get("total_count"), int)
        or isinstance(value.get("total_count"), bool)
        or value["total_count"] < 0
    ):
        raise GitHubError("cannot read M2 discovery Checks before recording")
    if value["total_count"] != len(value["check_runs"]):
        raise LoopBlocked("M2 discovery Check history exceeds its authoritative page")
    if any(
        not isinstance(check, dict)
        or check.get("name") != M2_DISCOVERY_CHECK_NAME
        for check in value["check_runs"]
    ):
        raise GitHubError("M2 discovery Check history is malformed")
    matches = [
        check
        for check in value["check_runs"]
        if check.get("external_id") == external_id
    ]
    if len(matches) > 1:
        raise LoopBlocked("M2 discovery Check identity is duplicated")
    if matches:
        match = matches[0]
        app = match.get("app")
        if (
            not isinstance(app, dict)
            or app.get("slug") != "github-actions"
            or match.get("head_sha") != tested_sha
            or match.get("status") != "completed"
            or match.get("conclusion") != github_conclusion(status)
        ):
            raise LoopBlocked("M2 discovery Check identity is untrusted or inconsistent")
        return
    if value["total_count"] >= 100:
        raise LoopBlocked("M2 discovery Check history capacity is exhausted")
    client.create_check_run(
        name=M2_DISCOVERY_CHECK_NAME,
        head_sha=tested_sha,
        conclusion=github_conclusion(status),
        title=f"M2 candidate-selection-only discovery {status}",
        summary=(
            f"{summary}\n\nCandidate selection only; never M2 admission evidence."
        )[:65000],
        external_id=external_id,
    )


def _m2_discovery_diagnosis_completed(
    control_issue: Mapping[str, Any], fingerprint: str
) -> bool:
    return any(
        fingerprint in M2_DISCOVERY_DIAGNOSIS_COMPLETE_RE.findall(comment.get("body", ""))
        for comment in control_issue.get("comments", [])
        if isinstance(comment, dict)
        and comment.get("author") == "github-actions[bot]"
        and isinstance(comment.get("body"), str)
    )


def _publish_m2_discovery_result_comment(
    client: GitHubClient, issue_number: int, body: str, marker: str
) -> None:
    endpoint = f"issues/{issue_number}/comments?per_page={MAX_ISSUE_COMMENTS + 1}"
    eof: GitHubError | None = None
    for attempt in range(3):
        comments = client.api(endpoint)
        if not isinstance(comments, list):
            raise GitHubError("cannot read Control Issue after M2 discovery comment EOF")
        if len(comments) > MAX_ISSUE_COMMENTS:
            raise LoopBlocked("Control Issue comment history exceeds its authoritative bound")
        if any(
            isinstance(comment, dict)
            and isinstance(comment.get("user"), dict)
            and comment["user"].get("login") == "github-actions[bot]"
            and isinstance(comment.get("body"), str)
            and marker in comment["body"]
            for comment in comments
        ):
            return
        if attempt == 2:
            if eof is None:
                raise GitHubError("M2 discovery comment retry state is invalid")
            raise eof
        try:
            client.comment(issue_number, body)
            return
        except GitHubError as exc:
            if "unexpected EOF" not in str(exc):
                raise
            eof = exc


def record_m2_discovery_result(
    *, client: GitHubClient, result: Mapping[str, Any]
) -> str:
    required = {
        "schema_version",
        "milestone",
        "status",
        "disposition",
        "failure_scope",
        "failure_code",
        "failure_fingerprint",
        "tested_sha",
        "lease_sha256",
        "run_id",
        "run_attempt",
        "invocation_id",
        "run_outcome",
        "cleanup_outcome",
        "report_digest",
        "evidence_digest",
        "summary",
        "result_digest",
    }
    if (
        set(result) != required
        or result.get("schema_version") != "m2-discovery-result-v1"
        or result.get("milestone") != "m2"
        or result.get("status") not in {"PASS", "FAIL", "BLOCKED"}
        or result.get("disposition")
        not in {"CANDIDATE_SELECTION_ONLY", "REPAIRABLE_IMPLEMENTATION", "HUMAN_REQUIRED"}
        or re.fullmatch(r"[0-9a-f]{40}", str(result.get("tested_sha", ""))) is None
        or (
            result.get("lease_sha256") != ""
            and re.fullmatch(r"[0-9a-f]{64}", str(result.get("lease_sha256", ""))) is None
        )
        or re.fullmatch(r"[0-9a-f]{64}", str(result.get("result_digest", ""))) is None
        or re.fullmatch(r"[0-9a-f]{64}", str(result.get("failure_fingerprint", ""))) is None
    ):
        raise ContractError("sealed M2 discovery record is invalid")
    snapshot = collect_snapshot(client, "m2")
    control = ensure_control(client, snapshot)
    snapshot = collect_snapshot(client, "m2")
    controls = [
        issue
        for issue in snapshot.get("issues", [])
        if issue.get("number") == control.issue_number
    ]
    if len(controls) != 1:
        raise LoopBlocked("M2 Control Issue disappeared before discovery recording")
    control_issue = controls[0]
    effective_status = str(result["status"])
    effective_disposition = str(result["disposition"])
    stale = snapshot.get("default_sha") != result["tested_sha"]
    if stale:
        effective_status = "BLOCKED"
        effective_disposition = "HUMAN_REQUIRED"
    dedup_key = hashlib.sha256(
        json.dumps(
            {
                "milestone": "m2",
                "tested_sha": result["tested_sha"],
                "failure_fingerprint": result["failure_fingerprint"],
                "status": effective_status,
                "disposition": effective_disposition,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    record_identity = {
        "version": 1,
        "milestone": "m2",
        "run_id": str(result["run_id"]),
        "run_attempt": int(result["run_attempt"]),
        "tested_sha": str(result["tested_sha"]),
        "lease_sha256": str(result["lease_sha256"]),
        "result_digest": str(result["result_digest"]),
        "report_digest": str(result["report_digest"]),
        "evidence_digest": str(result["evidence_digest"]),
        "cleanup_outcome": str(result["cleanup_outcome"]),
    }
    records = _trusted_comment_payloads(control_issue, M2_DISCOVERY_RECORD_RE)
    existing = [value for value in records if value.get("dedup_key") == dedup_key]
    if len(existing) > 1:
        raise LoopBlocked("M2 discovery durable record identity is duplicated")
    repairable = (
        effective_disposition == "REPAIRABLE_IMPLEMENTATION"
        and effective_status == "FAIL"
    )
    diagnosis_completed = repairable and _m2_discovery_diagnosis_completed(
        control_issue, str(result["failure_fingerprint"])
    )
    dispatched = repairable and any(
        dedup_key in M2_DISCOVERY_DISPATCH_RE.findall(comment.get("body", ""))
        for comment in control_issue.get("comments", [])
        if isinstance(comment, dict)
        and comment.get("author") == "github-actions[bot]"
        and isinstance(comment.get("body"), str)
    )
    ambiguous_dispatch = (
        repairable and bool(existing) and not diagnosis_completed and not dispatched
    )
    hard_block_record = existing[0] if ambiguous_dispatch else result
    human_action_value: dict[str, Any] | None = None
    if ambiguous_dispatch or (not repairable and effective_status != "PASS"):
        human_action_value = _human_action_value(
            snapshot=snapshot,
            state="HARD_BLOCKED",
            target=(
                f"run:{hard_block_record['run_id']}:"
                f"attempt:{hard_block_record['run_attempt']}"
            ),
            sha=str(hard_block_record["tested_sha"]),
        )
    human_action_exists = human_action_value is not None and any(
        payload.get("key") == human_action_value["key"]
        for payload in _trusted_comment_payloads(control_issue, HUMAN_ACTION_RE)
    )
    _require_control_comment_capacity(
        control_issue,
        (0 if existing else 1)
        + (
            1
            if repairable
            and not existing
            and not diagnosis_completed
            and not dispatched
            else 0
        )
        + (1 if human_action_value is not None and not human_action_exists else 0),
    )
    summary = str(result["summary"])[:4000]
    if not existing:
        _ensure_m2_discovery_check(
            client=client,
            tested_sha=str(result["tested_sha"]),
            dedup_key=dedup_key,
            status=effective_status,
            summary=summary,
        )
    marker = {
        **record_identity,
        "dedup_key": dedup_key,
        "status": effective_status,
        "disposition": effective_disposition,
        "failure_scope": str(result["failure_scope"]),
        "failure_code": str(result["failure_code"]),
        "failure_fingerprint": str(result["failure_fingerprint"]),
        "summary": str(result["summary"])[:2000],
    }
    qualifier = " (stale default SHA)" if stale else ""
    if not existing:
        comment_marker = (
            "<!-- milestone-loop-m2-discovery: "
            + json.dumps(marker, sort_keys=True, separators=(",", ":"))
            + " -->"
        )
        _publish_m2_discovery_result_comment(
            client,
            control.issue_number,
            f"Trusted M2 candidate-selection-only discovery result: **{effective_status}**{qualifier}\n\n"
            f"{summary}\n\n"
            "This result is not M2 admission evidence and cannot close M2.\n\n"
            + comment_marker,
            comment_marker,
        )
    if repairable:
        if diagnosis_completed:
            return "NOOP"
        if dispatched:
            return "NOOP"
        if ambiguous_dispatch:
            _record_m2_discovery_hard_block(
                client=client,
                snapshot=snapshot,
                control=control,
                record=hard_block_record,
                action=(
                    "Review the M2 discovery run because its prior diagnosis dispatch "
                    "has no trusted completion marker."
                ),
            )
            return "HUMAN_REQUIRED"
        client.dispatch("m2")
        client.comment(
            control.issue_number,
            "M2 discovery diagnosis dispatched.\n\n"
            f"<!-- milestone-loop-m2-discovery-dispatch: {dedup_key} -->",
        )
        return "DIAGNOSE"
    if effective_status == "PASS":
        return "NOOP" if existing else "RECORDED"
    repository = str(snapshot.get("repository", ""))
    run_id = str(result["run_id"])
    run_attempt = str(result["run_attempt"])
    record_human_action_state(
        client=client,
        snapshot=snapshot,
        control=control,
        state="HARD_BLOCKED",
        target=f"run:{run_id}:attempt:{run_attempt}",
        sha=str(result["tested_sha"]),
        action="Review the trusted M2 discovery Check and its current-invocation evidence.",
        link=f"https://github.com/{repository}/actions/runs/{run_id}/attempts/{run_attempt}",
    )
    return "HUMAN_REQUIRED"


def record_milestone_result(
    *,
    client: GitHubClient,
    milestone: str,
    expected_sha: str,
    status: str,
    summary: str,
) -> str:
    if status not in {"PASS", "FAIL", "BLOCKED"}:
        raise ContractError("Milestone result must be PASS, FAIL, or BLOCKED")
    if re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None:
        raise ContractError("Milestone result expected SHA is invalid")
    snapshot = collect_snapshot(client, milestone)
    control = ensure_control(client, snapshot)
    client.comment(
        control.issue_number,
        f"Authoritative `./gate milestone {milestone}` result: **{status}**\n\n{summary[:4000]}",
    )
    client.create_check_run(
        name=f"milestone-loop / {milestone}",
        head_sha=expected_sha,
        conclusion=github_conclusion(status),
        title=f"Authoritative {milestone} Gate {status}",
        summary=summary or status,
    )
    if snapshot["default_sha"] != expected_sha:
        client.comment(
            control.issue_number,
            "Milestone result is bound to an older default-branch SHA and cannot close the "
            "Milestone; start a fresh loop invocation and approve its new `valkey-real` "
            "deployment to rerun it.",
        )
        return "STALE"
    if status == "PASS":
        set_no_progress(client, control, 0)
        control = ControlState(control.issue_number, control.lease, 0)
        if milestone == "m2":
            repository = str(snapshot.get("repository", ""))
            record_human_action_state(
                client=client,
                snapshot=snapshot,
                control=control,
                state="M2_COMPLETE",
                target=f"milestone:{milestone}",
                sha=expected_sha,
                action="Review the authoritative M2 Gate result and close the Milestone.",
                link=f"https://github.com/{repository}/issues/{control.issue_number}",
            )
        return "HUMAN_CLOSE"
    if status == "FAIL":
        return "DIAGNOSE"
    return "BLOCKED"
