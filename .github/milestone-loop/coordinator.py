from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

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
    render_work_item,
    require_candidate_check,
    resolve_check,
    status_from_labels,
    validate_acyclic,
    validate_transition,
    verified_tree,
)
from github_api import GitHubClient, GitHubError, collect_snapshot


CONTROL_LABEL = "milestone-loop:control"
CONTRACT_CHANGE_LABEL = "contract-change"
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
PROTECTED_PREFIXES = (
    ".github/CODEOWNERS",
    ".github/milestone-loop/",
    ".github/workflows/",
    "project/milestones/",
    "project/verification/",
    "project/catalog.json",
    "project/gate",
    "project/src/valkey_scale_lab/cli.py",
    "project/src/valkey_scale_lab/gates/",
    "project/src/valkey_scale_lab/runtime/docker_runtime.py",
    "project/src/valkey_scale_lab/scenarios/definitions/",
    "project/templates/configs/scale_50.yaml",
    "project/templates/configs/scale_200.yaml",
)
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
        "version": 1,
        "milestone": milestone,
        "status": "empty",
        "nonce": "",
        "expires_at": "",
        "remaining": 0,
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
    required = {"version", "milestone", "status", "nonce", "expires_at", "remaining"}
    if not isinstance(lease, dict) or set(lease) != required:
        raise ContractError("Authorization Lease has invalid fields")
    if lease["version"] != 1 or lease["milestone"] != milestone:
        raise ContractError("Authorization Lease version or milestone is invalid")
    if lease["status"] not in {"empty", "active", "exhausted", "revoked"}:
        raise ContractError("Authorization Lease status is invalid")
    if not isinstance(lease["nonce"], str) or len(lease["nonce"]) > 128:
        raise ContractError("Authorization Lease nonce is invalid")
    if not isinstance(lease["expires_at"], str) or len(lease["expires_at"]) > 64:
        raise ContractError("Authorization Lease expires_at is invalid")
    if isinstance(lease["remaining"], bool) or not isinstance(lease["remaining"], int) or not 0 <= lease["remaining"] <= 10:
        raise ContractError("Authorization Lease remaining must be between 0 and 10")
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


def consume_lease(client: GitHubClient, snapshot: Mapping[str, Any]) -> ControlState:
    state = ensure_control(client, snapshot)
    lease = dict(state.lease)
    if lease["status"] != "active" or lease["remaining"] <= 0:
        raise LoopBlocked("Authorization Lease is not active or has no remaining execution")
    try:
        expires = datetime.fromisoformat(lease["expires_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise LoopBlocked("Authorization Lease expiration is invalid") from exc
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise LoopBlocked("Authorization Lease is expired")
    lease["remaining"] -= 1
    if lease["remaining"] == 0:
        lease["status"] = "exhausted"
    live_issue = client.api(f"issues/{state.issue_number}")
    if not isinstance(live_issue, dict):
        raise GitHubError("cannot re-read Control Issue before lease consumption")
    live_state = parse_control(live_issue, str(snapshot["milestone"]))
    if dict(live_state.lease) != dict(state.lease) or live_state.no_progress_count != state.no_progress_count:
        raise LoopBlocked("Authorization Lease changed before consumption")
    client.update_issue(
        state.issue_number,
        body=render_control(lease, state.no_progress_count),
    )
    return ControlState(state.issue_number, lease, state.no_progress_count)


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


def run_planner(
    *,
    repo_root: Path,
    runtime_root: Path,
    snapshot: Mapping[str, Any],
    milestone_document: Mapping[str, Any],
    global_audit: bool = False,
    diagnosis_issue: int | None = None,
) -> PlannerOutput:
    runtime_root.mkdir(parents=True, exist_ok=True)
    context_path = runtime_root / "planner-context.json"
    output_path = runtime_root / "planner-output.json"
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
                f"This is the one bounded failure diagnosis for Work Item #{diagnosis_issue}. "
                "Only split that item, create a necessary prerequisite, adjust its dependencies, "
                "or leave it blocked/superseded. Do not update any other existing Work Item."
                if diagnosis_issue is not None
                else (
                    "This is the single global no-progress audit at the first threshold. "
                    "Reassess whether the current Work Items are necessary, correctly split, "
                    "and dependency-complete without weakening any Criterion or Check."
                    if global_audit
                    else ""
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


def validate_failure_diagnosis(
    transaction: PlannerTransaction,
    *,
    issue_number: int,
    snapshot: Mapping[str, Any],
) -> None:
    target = _find_item(snapshot, issue_number)
    target_contract = parse_work_item(target["body"])
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
        if protected:
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
            "Contract-Change: false\n"
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
            labels=(WORK_ITEM_LABEL,),
        )
        client.api(
            f"issues/{pr_number}",
            method="PATCH",
            input_value={"milestone": int(snapshot["milestone_number"])},
        )
        _set_issue_status(client, live_issue, "review")
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
            if isinstance(record, dict) and set(record) == {
                "version",
                "base_sha",
                "head_sha",
                "tree_sha",
                "verified_tree",
                "baseline",
                "work_item_check",
                "status",
            }:
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
                or record.get("status") != "PASS"
                or record.get("head_sha") != pr.get("head_sha")
                or record.get("tree_sha") != pr.get("merge_tree_sha")
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
            "status",
        }
        if set(record) != required or record.get("status") != "PASS":
            raise LoopBlocked("candidate verification record has invalid fields or status")
        expected_tree = verified_tree(
            str(record["base_sha"]), str(record["head_sha"]), str(record["tree_sha"])
        )
        contract = parse_work_item(issue["body"])
        if (
            record.get("base_sha") != snapshot.get("default_sha")
            or record.get("head_sha") != pr.get("head_sha")
            or record.get("tree_sha") != pr.get("head_tree_sha")
            or record.get("verified_tree") != expected_tree
            or record.get("baseline") != "repository.all"
            or record.get("work_item_check") != contract.check
        ):
            client.disable_auto_merge(int(pr["number"]))
            _set_issue_status(client, issue, "ready")
            return "RETRY", control
        if CONTRACT_CHANGE_LABEL in pr.get("labels", []) or "Contract-Change: true" in pr.get("body", ""):
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
        client.enable_auto_merge(int(pr["number"]))
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
    control = ensure_control(client, snapshot)
    snapshot = collect_snapshot(client, milestone)
    review_action, control = reconcile_review(client, snapshot, control)
    if review_action in {"WAIT_PR", "WAIT_MERGE", "HUMAN_REVIEW", "BLOCKED"}:
        return {"status": review_action, "milestone": milestone}
    snapshot = collect_snapshot(client, milestone)
    diagnosis = pending_failure_diagnosis(snapshot)
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
            global_audit=control.no_progress_count == 5,
            diagnosis_issue=diagnosis[0] if diagnosis is not None else None,
        )
    except AgentError as exc:
        client.comment(control.issue_number, f"Planner protocol or timeout BLOCKED: {str(exc)[:2000]}")
        return {"status": "BLOCKED", "milestone": milestone, "reason": "planner"}
    transaction = prepare_planner_transaction(
        snapshot=snapshot,
        output=planner_output,
        milestone_document=milestone_document,
        catalog_document=catalog_document,
    )
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
    return {"status": "MILESTONE", "milestone": milestone}


def milestone_from_pr_body(body: str) -> str:
    match = PR_MILESTONE_RE.search(body)
    if match is None:
        raise ContractError("PR body does not contain exactly one fixed Milestone line")
    if len(PR_MILESTONE_RE.findall(body)) != 1:
        raise ContractError("PR body contains multiple Milestone lines")
    return match.group(1)


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
            "Milestone; issue a new lease and resume to rerun it.",
        )
        return "STALE"
    if status == "PASS":
        set_no_progress(client, control, 0)
        return "HUMAN_CLOSE"
    if status == "FAIL":
        return "DIAGNOSE"
    return "BLOCKED"
