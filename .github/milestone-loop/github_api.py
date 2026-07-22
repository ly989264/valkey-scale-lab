from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from contracts import ContractError


MAX_ISSUE_COMMENTS = 50


class GitHubError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubClient:
    repo: str
    gh: str = "gh"

    @classmethod
    def from_environment(cls) -> "GitHubClient":
        repo = os.environ.get("GITHUB_REPOSITORY") or os.environ.get("GH_REPO")
        if not repo or repo.count("/") != 1:
            raise GitHubError("GITHUB_REPOSITORY or GH_REPO must name owner/repository")
        return cls(repo)

    def api(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        fields: Mapping[str, str] | None = None,
        input_value: Any | None = None,
    ) -> Any:
        suffix = endpoint.lstrip("/")
        target = f"repos/{self.repo}" + (f"/{suffix}" if suffix else "")
        argv = [self.gh, "api", target, "--method", method]
        if fields:
            for key, value in fields.items():
                argv.extend(["-f", f"{key}={value}"])
        encoded: bytes | None = None
        if input_value is not None:
            argv.extend(["--input", "-"])
            encoded = (json.dumps(input_value, separators=(",", ":")) + "\n").encode()
        process = subprocess.run(argv, input=encoded, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if process.returncode != 0:
            detail = process.stderr.decode("utf-8", errors="replace")[-2000:].strip()
            raise GitHubError(f"gh api {method} {endpoint} failed: {detail}")
        if not process.stdout.strip():
            return None
        try:
            return json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubError(f"gh api returned invalid JSON for {endpoint}: {exc}") from exc

    def repository(self) -> dict[str, Any]:
        value = self.api("")
        if not isinstance(value, dict):
            raise GitHubError("repository response is not an object")
        return value

    def ensure_label(self, name: str, color: str, description: str) -> None:
        encoded = quote(name, safe="")
        try:
            self.api(f"labels/{encoded}")
        except GitHubError:
            self.api(
                "labels",
                method="POST",
                input_value={"name": name, "color": color, "description": description},
            )

    def create_issue(self, *, title: str, body: str, labels: Sequence[str], milestone_number: int) -> int:
        value = self.api(
            "issues",
            method="POST",
            input_value={
                "title": title,
                "body": body,
                "labels": list(labels),
                "milestone": milestone_number,
            },
        )
        if not isinstance(value, dict) or not isinstance(value.get("number"), int):
            raise GitHubError("create Issue response did not contain a number")
        return value["number"]

    def update_issue(
        self,
        number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        labels: Sequence[str] | None = None,
        state: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if labels is not None:
            payload["labels"] = list(labels)
        if state is not None:
            payload["state"] = state
        self.api(f"issues/{number}", method="PATCH", input_value=payload)

    def comment(self, number: int, body: str) -> None:
        self.api(f"issues/{number}/comments", method="POST", input_value={"body": body})

    def create_pull_request(self, *, title: str, body: str, head: str, base: str) -> int:
        value = self.api(
            "pulls",
            method="POST",
            input_value={"title": title, "body": body, "head": head, "base": base},
        )
        if not isinstance(value, dict) or not isinstance(value.get("number"), int):
            raise GitHubError("create PR response did not contain a number")
        return value["number"]

    def update_pull_request(self, number: int, *, body: str | None = None, state: str | None = None) -> None:
        payload: dict[str, Any] = {}
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state
        self.api(f"pulls/{number}", method="PATCH", input_value=payload)

    def disable_auto_merge(self, number: int) -> None:
        process = subprocess.run(
            [self.gh, "pr", "merge", str(number), "--repo", self.repo, "--disable-auto"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        combined = (process.stdout + process.stderr).decode("utf-8", errors="replace").lower()
        if process.returncode != 0 and "not enabled" not in combined and "no auto-merge" not in combined:
            raise GitHubError(f"cannot disable auto-merge for PR #{number}: {combined[-1000:].strip()}")

    def merge_pull_request(self, number: int, *, expected_head_sha: str) -> str:
        value = self.api(
            f"pulls/{number}/merge",
            method="PUT",
            input_value={"sha": expected_head_sha, "merge_method": "squash"},
        )
        merge_sha = value.get("sha") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or value.get("merged") is not True
            or not isinstance(merge_sha, str)
            or len(merge_sha) != 40
            or any(character not in "0123456789abcdef" for character in merge_sha.lower())
        ):
            raise GitHubError(f"cannot synchronously merge PR #{number}")
        return merge_sha

    def dispatch(self, milestone: str) -> None:
        process = subprocess.run(
            [
                self.gh,
                "workflow",
                "run",
                "milestone-loop.yml",
                "--repo",
                self.repo,
                "--ref",
                self.default_branch(),
                "-f",
                "action=start",
                "-f",
                f"milestone={milestone}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.returncode != 0:
            detail = process.stderr.decode("utf-8", errors="replace")[-1000:].strip()
            raise GitHubError(f"cannot self-dispatch next loop round: {detail}")

    def create_check_run(
        self,
        *,
        name: str,
        head_sha: str,
        conclusion: str,
        title: str,
        summary: str,
        external_id: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "name": name,
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": conclusion,
            "output": {"title": title, "summary": summary[:65000]},
        }
        if external_id is not None:
            payload["external_id"] = external_id
        self.api(
            "check-runs",
            method="POST",
            input_value=payload,
        )

    def default_branch(self) -> str:
        value = self.repository().get("default_branch")
        if not isinstance(value, str) or not value:
            raise GitHubError("repository default_branch is invalid")
        return value


def _labels(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(
        item["name"] for item in value if isinstance(item, dict) and isinstance(item.get("name"), str)
    )


def _bounded_list(value: Any, *, location: str, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        raise GitHubError(f"{location} response is not an array")
    if len(value) > maximum:
        raise ContractError(f"{location} exceeds the authoritative-state limit of {maximum}")
    return value


def collect_snapshot(client: GitHubClient, milestone: str) -> dict[str, Any]:
    repo = client.repository()
    default_branch = repo.get("default_branch")
    if not isinstance(default_branch, str):
        raise GitHubError("repository default branch is missing")
    branch = client.api(f"branches/{quote(default_branch, safe='')}")
    if not isinstance(branch, dict):
        raise GitHubError("default branch response is invalid")
    commit = branch.get("commit")
    if not isinstance(commit, dict) or not isinstance(commit.get("sha"), str):
        raise GitHubError("default branch SHA is missing")
    milestones = _bounded_list(
        client.api("milestones?state=open&per_page=100"), location="Milestones", maximum=99
    )
    matches = [
        item
        for item in milestones
        if isinstance(item, dict) and str(item.get("title", "")).lower() == milestone
    ]
    if len(matches) != 1:
        raise ContractError(f"GitHub must contain exactly one open Milestone titled {milestone}")
    milestone_number = matches[0].get("number")
    if not isinstance(milestone_number, int):
        raise GitHubError("GitHub Milestone number is invalid")
    raw_issues = _bounded_list(
        client.api(f"issues?state=all&milestone={milestone_number}&per_page=100"),
        location="Milestone Issues and PRs",
        maximum=99,
    )
    issues: list[dict[str, Any]] = []
    prs: list[dict[str, Any]] = []
    for raw in raw_issues:
        if not isinstance(raw, dict):
            raise GitHubError("Issue response entry is invalid")
        if "pull_request" in raw:
            number = raw.get("number")
            if not isinstance(number, int):
                raise GitHubError("PR number is invalid")
            detail = client.api(f"pulls/{number}")
            if not isinstance(detail, dict):
                raise GitHubError("PR detail is invalid")
            head = detail.get("head") if isinstance(detail.get("head"), dict) else {}
            base = detail.get("base") if isinstance(detail.get("base"), dict) else {}
            head_sha = head.get("sha")
            checks: list[dict[str, Any]] = []
            if isinstance(head_sha, str):
                head_commit = client.api(f"git/commits/{head_sha}")
                head_tree = head_commit.get("tree") if isinstance(head_commit, dict) else None
                head_tree_sha = head_tree.get("sha") if isinstance(head_tree, dict) else None
                check_doc = client.api(f"commits/{head_sha}/check-runs?per_page=100")
                raw_checks = check_doc.get("check_runs") if isinstance(check_doc, dict) else None
                for check in _bounded_list(raw_checks, location=f"PR #{number} Checks", maximum=99):
                    if isinstance(check, dict):
                        checks.append(
                            {
                                "id": check.get("id"),
                                "name": check.get("name"),
                                "status": check.get("status"),
                                "conclusion": check.get("conclusion"),
                                "details_url": check.get("details_url"),
                                "app": (check.get("app") or {}).get("slug")
                                if isinstance(check.get("app"), dict)
                                else None,
                                "summary": (check.get("output") or {}).get("summary", "")[:4000]
                                if isinstance(check.get("output"), dict)
                                and isinstance((check.get("output") or {}).get("summary"), str)
                                else "",
                            }
                        )
            merge_commit_sha = detail.get("merge_commit_sha")
            merge_tree_sha = None
            if detail.get("merged_at") and isinstance(merge_commit_sha, str):
                merge_commit = client.api(f"git/commits/{merge_commit_sha}")
                merge_tree = merge_commit.get("tree") if isinstance(merge_commit, dict) else None
                merge_tree_sha = merge_tree.get("sha") if isinstance(merge_tree, dict) else None
            comments = _bounded_list(
                client.api(f"issues/{number}/comments?per_page={MAX_ISSUE_COMMENTS + 1}"),
                location=f"PR #{number} comments",
                maximum=MAX_ISSUE_COMMENTS,
            )
            prs.append(
                {
                    "number": number,
                    "title": detail.get("title"),
                    "body": detail.get("body") or "",
                    "state": detail.get("state"),
                    "merged_at": detail.get("merged_at"),
                    "merge_commit_sha": merge_commit_sha,
                    "merge_tree_sha": merge_tree_sha,
                    "labels": _labels(detail.get("labels")),
                    "head_ref": head.get("ref"),
                    "head_sha": head_sha,
                    "head_tree_sha": head_tree_sha if isinstance(head_sha, str) else None,
                    "base_ref": base.get("ref"),
                    "base_sha": base.get("sha"),
                    "mergeable_state": detail.get("mergeable_state"),
                    "auto_merge": detail.get("auto_merge") is not None,
                    "checks": checks,
                    "comments": [
                        {
                            "author": (comment.get("user") or {}).get("login")
                            if isinstance(comment, dict) and isinstance(comment.get("user"), dict)
                            else None,
                            "body": comment.get("body") if isinstance(comment, dict) else None,
                            "created_at": comment.get("created_at") if isinstance(comment, dict) else None,
                        }
                        for comment in comments
                    ],
                }
            )
            continue
        number = raw.get("number")
        if not isinstance(number, int):
            raise GitHubError("Issue number is invalid")
        comments = _bounded_list(
            client.api(f"issues/{number}/comments?per_page={MAX_ISSUE_COMMENTS + 1}"),
            location=f"Issue #{number} comments",
            maximum=MAX_ISSUE_COMMENTS,
        )
        issues.append(
            {
                "number": number,
                "title": raw.get("title"),
                "body": raw.get("body") or "",
                "state": raw.get("state"),
                "labels": _labels(raw.get("labels")),
                "comments": [
                    {
                        "author": (comment.get("user") or {}).get("login")
                        if isinstance(comment, dict) and isinstance(comment.get("user"), dict)
                        else None,
                        "body": comment.get("body") if isinstance(comment, dict) else None,
                        "created_at": comment.get("created_at") if isinstance(comment, dict) else None,
                    }
                    for comment in comments
                ],
            }
        )
    if len(issues) > 40 or len(prs) > 20:
        raise ContractError("authoritative Work Item or PR state exceeds the context limits")
    return {
        "repository": client.repo,
        "default_branch": default_branch,
        "default_sha": commit["sha"],
        "milestone": milestone,
        "milestone_number": milestone_number,
        "issues": sorted(issues, key=lambda item: item["number"]),
        "pull_requests": sorted(prs, key=lambda item: item["number"]),
    }
