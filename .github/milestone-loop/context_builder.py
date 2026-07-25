from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from contracts import ContractError, parse_work_item


MAX_CONTEXT_BYTES = 192_000
WORK_ITEM_LABEL = "milestone-loop:work-item"


def work_items(snapshot: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for issue in snapshot.get("issues", []):
        if not isinstance(issue, dict) or WORK_ITEM_LABEL not in issue.get("labels", []):
            continue
        number = issue.get("number")
        if not isinstance(number, int):
            raise ContractError("Work Item number is invalid")
        contract = parse_work_item(issue.get("body", ""))
        item = dict(issue)
        item["contract"] = {
            "criterion": contract.criterion,
            "depends_on": list(contract.depends_on),
            "check": contract.check,
        }
        result[number] = item
    return result


def _relevant_prs(snapshot: Mapping[str, Any], issue_number: int | None) -> list[dict[str, Any]]:
    if issue_number is None:
        return [
            dict(pr)
            for pr in snapshot.get("pull_requests", [])
            if pr.get("state") == "open"
        ]
    marker = f"Work-Item: #{issue_number}"
    return [
        dict(pr)
        for pr in snapshot.get("pull_requests", [])
        if marker in pr.get("body", "").splitlines()
    ]


def build_context(
    *,
    repo_root: Path,
    snapshot: Mapping[str, Any],
    milestone_document: Mapping[str, Any],
    issue_number: int | None = None,
) -> dict[str, Any]:
    items = work_items(snapshot)
    if issue_number is not None and issue_number not in items:
        raise ContractError(f"selected Work Item #{issue_number} does not exist")
    selected = items.get(issue_number) if issue_number is not None else None
    direct_dependencies = []
    if selected is not None:
        direct_dependencies = [
            items[number]
            for number in selected["contract"]["depends_on"]
            if number in items
        ]
        if len(direct_dependencies) != len(selected["contract"]["depends_on"]):
            raise ContractError("selected Work Item has a missing direct dependency")
    manifest = [
        "repository.default_branch",
        "repository.default_sha",
        "milestone.document",
        "github.work_items",
        "github.pull_requests_and_checks",
        "github.human_comments",
    ]
    payload = {
        "schema_version": "milestone-loop-context-v1",
        "context_truncated": False,
        "content_manifest": manifest,
        "repository": {
            "name": snapshot.get("repository"),
            "default_branch": snapshot.get("default_branch"),
            "default_sha": snapshot.get("default_sha"),
            "constraints": (repo_root / "AGENTS.md").read_text(encoding="utf-8"),
        },
        "milestone": milestone_document,
        "work_items": list(items.values()) if issue_number is None else [selected],
        "direct_dependencies": direct_dependencies,
        "pull_requests": _relevant_prs(snapshot, issue_number),
        "milestone_comments": [
            {
                "issue": issue.get("number"),
                "title": issue.get("title"),
                "comments": issue.get("comments", []),
            }
            for issue in snapshot.get("issues", [])
            if issue.get("comments")
            and (issue_number is None or issue.get("number") == issue_number)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_CONTEXT_BYTES:
        raise ContractError(
            f"authoritative context is {len(encoded)} bytes, above {MAX_CONTEXT_BYTES}; BLOCKED"
        )
    payload["context_sha256"] = hashlib.sha256(encoded).hexdigest()
    return payload


def write_context(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if len(encoded.encode("utf-8")) > MAX_CONTEXT_BYTES + 16_000:
        raise ContractError("rendered context exceeds its bounded output allowance")
    path.write_text(encoded, encoding="utf-8")
