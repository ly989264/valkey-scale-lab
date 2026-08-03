#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

CONTROL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = CONTROL_ROOT.parents[1]
sys.path.insert(0, str(CONTROL_ROOT))

from contracts import (
    ContractError,
    fixed_milestone_path,
    github_conclusion,
    parse_work_item,
    pr_contract_change,
    require_candidate_check,
    status_from_labels,
    verification_metadata_path,
)
from coordinator import (
    LoopBlocked,
    coordinate,
    milestone_from_pr_body,
    record_m2_discovery_result,
    record_milestone_result,
    trusted_m2_discovery_repair_pr,
)
from github_api import GitHubClient, GitHubError, collect_snapshot
from milestone_runner import (
    LeaseConfirmationBlocked,
    authorize_real_invocation,
    bind_real_result,
    blocked_milestone_result,
    human_required_m2_discovery_result,
    load_milestone_result,
    load_m2_discovery_result,
    run_gate,
    run_m2_discovery,
    seal_milestone_result,
    seal_m2_discovery_result,
)
from recovery import recover


def _write_output(values: dict[str, Any]) -> None:
    print(json.dumps(values, sort_keys=True))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            for key, value in values.items():
                if isinstance(value, bool):
                    rendered = str(value).lower()
                elif isinstance(value, (dict, list)):
                    rendered = json.dumps(value, separators=(",", ":"))
                else:
                    rendered = str(value)
                if "\n" in rendered or "\r" in rendered:
                    raise ContractError(f"GitHub output {key} contains a newline")
                handle.write(f"{key}={rendered}\n")


def _version(argv: list[str]) -> str:
    process = subprocess.run(
        argv,
        cwd=CONTROL_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if process.returncode != 0:
        raise LoopBlocked(f"cannot execute environment fingerprint command: {' '.join(argv)}")
    lines = [
        line.strip()
        for line in process.stdout.splitlines()
        if line.strip() and not line.lstrip().startswith("WARNING:")
    ]
    if not lines:
        raise LoopBlocked(f"environment fingerprint command produced no version: {' '.join(argv)}")
    return lines[0]


def validate_environment(role: str) -> dict[str, Any]:
    expected = json.loads((CONTROL_ROOT / "environment.json").read_text(encoding="utf-8"))
    actual = {
        "schema_version": "milestone-loop-environment-v1",
        "platform": platform.system(),
        "architecture": platform.machine(),
        "python": _version(["python3", "--version"]),
        "gh": _version(["gh", "--version"]),
        "git": _version(["git", "--version"]),
        "codex": _version(["codex", "--version"]) if role == "codex" else expected["codex"],
        "docker": _version(["docker", "--version"]) if role in {"verify", "real"} else expected["docker"],
        "pytest": _version(["python3", "-I", "-c", "import pytest; print(pytest.__version__)"]),
        "actions_runner": os.environ.get(
            "ACTIONS_RUNNER_VERSION",
            expected["actions_runner"] if os.environ.get("GITHUB_ACTIONS") != "true" else "",
        ),
    }
    if actual != expected:
        raise LoopBlocked(
            "runner environment differs from the human-approved fingerprint: "
            + json.dumps({"expected": expected, "actual": actual}, sort_keys=True)
        )
    return actual


def _event(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read GitHub event: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("GitHub event must be an object")
    return value


def _live_pull_request(
    client: GitHubClient,
    *,
    event_action: str,
    event_pr: dict[str, Any],
    repository: dict[str, Any],
) -> dict[str, Any]:
    number = event_pr.get("number")
    if not isinstance(number, int):
        raise ContractError("pull request number is invalid")
    live = client.api(f"pulls/{number}")
    if not isinstance(live, dict) or live.get("number") != number:
        raise ContractError("live pull request is unavailable or mismatched")
    if event_action == "closed":
        if (
            live.get("state") != "closed"
            or live.get("merged") is not True
            or event_pr.get("merged") is not True
        ):
            raise LoopBlocked("closed pull request event is not a live merged PR")
    elif live.get("state") != "open" or live.get("merged") is True:
        raise LoopBlocked("live pull request is no longer open")
    event_head = event_pr.get("head")
    event_base = event_pr.get("base")
    live_head = live.get("head")
    live_base = live.get("base")
    if not all(isinstance(value, dict) for value in (event_head, event_base, live_head, live_base)):
        raise ContractError("pull request head or base is missing")
    full_name = repository.get("full_name")
    event_head_repo = event_head.get("repo")
    live_head_repo = live_head.get("repo")
    if (
        not isinstance(full_name, str)
        or not isinstance(event_head_repo, dict)
        or not isinstance(live_head_repo, dict)
        or event_head_repo.get("full_name") != full_name
        or live_head_repo.get("full_name") != full_name
    ):
        raise LoopBlocked("fork pull requests cannot execute on the local Mac")
    if (
        live_head.get("sha") != event_head.get("sha")
        or live_base.get("sha") != event_base.get("sha")
    ):
        raise LoopBlocked("live pull request head or base changed after this workflow event")
    if live.get("author_association") not in {"OWNER", "MEMBER", "COLLABORATOR"}:
        raise LoopBlocked("pull request author is not trusted for self-hosted execution")
    return live


def pr_metadata(client: GitHubClient, event_path: Path) -> dict[str, Any]:
    event = _event(event_path)
    event_pr = event.get("pull_request")
    repository = event.get("repository")
    if not isinstance(event_pr, dict) or not isinstance(repository, dict):
        raise ContractError("event is not a pull_request event")
    action = event.get("action")
    if not isinstance(action, str):
        raise ContractError("pull request action is invalid")
    pr = _live_pull_request(
        client,
        event_action=action,
        event_pr=event_pr,
        repository=repository,
    )
    head = pr["head"]
    base = pr["base"]
    body = pr.get("body") or ""
    if not isinstance(body, str):
        raise ContractError("pull request body is invalid")
    milestone = milestone_from_pr_body(body)
    fixed_milestone_path(REPO_ROOT, milestone)
    github_milestone = pr.get("milestone")
    github_milestone_title = (
        github_milestone.get("title") if isinstance(github_milestone, dict) else None
    )
    if not isinstance(github_milestone_title, str) or not github_milestone_title:
        raise ContractError(f"GitHub PR Milestone must be set to {milestone}")
    if github_milestone_title != milestone:
        raise ContractError(
            f"PR body Milestone {milestone} does not match GitHub PR Milestone {github_milestone_title}"
        )
    labels = {
        item.get("name")
        for item in pr.get("labels", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    contract_change = pr_contract_change(body, labels)
    matches = re.findall(r"(?m)^Work-Item: #([1-9][0-9]*)$", body)
    if len(matches) != 1:
        raise ContractError("pull request must reference exactly one Work-Item")
    issue_number = int(matches[0])
    snapshot = collect_snapshot(client, milestone)
    issue = next(
        (item for item in snapshot["issues"] if item.get("number") == issue_number),
        None,
    )
    issue_labels = set(issue.get("labels", [])) if isinstance(issue, dict) else set()
    merged_event = action == "closed" and bool(pr.get("merged"))
    reviewed_open_item = (
        isinstance(issue, dict)
        and issue.get("state") == "open"
        and status_from_labels(issue_labels) == "review"
    )
    completed_merged_item = (
        merged_event
        and isinstance(issue, dict)
        and issue.get("state") == "closed"
        and status_from_labels(issue_labels) == "review"
    )
    if (
        issue is None
        or "milestone-loop:work-item" not in issue_labels
        or not (reviewed_open_item or completed_merged_item)
    ):
        raise ContractError("referenced Work Item is not the active reviewed Milestone item")
    work_item = parse_work_item(issue.get("body", ""))
    if contract_change:
        check = "repository.all"
    else:
        check = work_item.check
    catalog = json.loads((REPO_ROOT / "project" / "catalog.json").read_text(encoding="utf-8"))
    require_candidate_check(catalog, work_item.check)
    if check != work_item.check:
        require_candidate_check(catalog, check)
    return {
        "pr": pr["number"],
        "work_item": issue_number,
        "milestone": milestone,
        "base_sha": base.get("sha"),
        "head_sha": head.get("sha"),
        "check": check,
        "contract_change": contract_change,
        "merged": bool(pr.get("merged")),
        "action": event.get("action"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="milestone-loop")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-dispatch")
    validate.add_argument("--action", required=True)
    validate.add_argument("--milestone", required=True)
    fingerprint = commands.add_parser("fingerprint")
    fingerprint.add_argument("--role", choices=("codex", "verify", "real"), required=True)
    recover_parser = commands.add_parser("recover")
    recover_parser.add_argument("--role", choices=("codex", "verify", "real"), required=True)
    recover_parser.add_argument("--runtime-root", type=Path, required=True)
    coordinate_parser = commands.add_parser("coordinate")
    coordinate_parser.add_argument("--action", required=True)
    coordinate_parser.add_argument("--milestone", required=True)
    coordinate_parser.add_argument("--runtime-root", type=Path, required=True)
    metadata = commands.add_parser("pr-metadata")
    metadata.add_argument("--event", type=Path, required=True)
    auth = commands.add_parser("authorize-real-invocation")
    auth.add_argument("--milestone", required=True)
    auth.add_argument("--entrypoint", required=True)
    auth.add_argument("--expected-sha", required=True)
    auth.add_argument("--expected-readiness-sha256", required=True)
    auth.add_argument("--run-id", required=True)
    auth.add_argument("--run-attempt", required=True)
    run = commands.add_parser("run-milestone")
    run.add_argument("--milestone", required=True)
    run.add_argument("--expected-sha", required=True)
    run.add_argument("--expected-lease-sha256", required=True)
    seal_milestone = commands.add_parser("seal-milestone-result")
    seal_milestone.add_argument("--milestone", required=True)
    seal_milestone.add_argument("--expected-sha", required=True)
    seal_milestone.add_argument("--expected-lease-sha256", required=True)
    seal_milestone.add_argument("--run-id", required=True)
    seal_milestone.add_argument("--run-attempt", required=True)
    seal_milestone.add_argument("--gate-outcome", required=True)
    seal_milestone.add_argument("--pre-cleanup-outcome", required=True)
    seal_milestone.add_argument("--cleanup-outcome", required=True)
    seal_milestone.add_argument("--evidence-outcome", required=True)
    seal_milestone.add_argument("--raw-result", type=Path, required=True)
    seal_milestone.add_argument("--output", type=Path, required=True)
    discovery = commands.add_parser("run-m2-discovery")
    discovery.add_argument("--expected-sha", required=True)
    discovery.add_argument("--expected-lease-sha256", required=True)
    seal_discovery = commands.add_parser("seal-m2-discovery")
    seal_discovery.add_argument("--expected-sha", required=True)
    seal_discovery.add_argument("--expected-lease-sha256", required=True)
    seal_discovery.add_argument("--run-id", required=True)
    seal_discovery.add_argument("--run-attempt", required=True)
    seal_discovery.add_argument("--run-outcome", required=True)
    seal_discovery.add_argument("--cleanup-outcome", required=True)
    seal_discovery.add_argument("--raw-result", type=Path, required=True)
    seal_discovery.add_argument("--evidence", type=Path, required=True)
    seal_discovery.add_argument("--output", type=Path, required=True)
    record_discovery = commands.add_parser("record-m2-discovery")
    record_discovery.add_argument("--expected-sha", required=True)
    record_discovery.add_argument("--expected-lease-sha256", required=True)
    record_discovery.add_argument("--run-id", required=True)
    record_discovery.add_argument("--run-attempt", required=True)
    record_discovery.add_argument("--result", type=Path, required=True)
    record_discovery.add_argument("--evidence", type=Path, required=True)
    record = commands.add_parser("record-milestone")
    record.add_argument("--milestone", required=True)
    record.add_argument("--expected-sha", required=True)
    record.add_argument("--expected-lease-sha256", required=True)
    record.add_argument(
        "--environment-started",
        choices=("", "success", "failure", "cancelled", "skipped"),
        required=True,
    )
    record.add_argument("--run-id", required=True)
    record.add_argument("--run-attempt", required=True)
    record.add_argument("--result", type=Path, required=True)
    after = commands.add_parser("after-pr")
    after.add_argument("--event", type=Path, required=True)
    publish = commands.add_parser("publish-verification")
    publish.add_argument("--pr", type=int, required=True)
    publish.add_argument("--head-sha", required=True)
    publish.add_argument("--milestone", required=True)
    publish.add_argument("--contract-change", choices=("true", "false"), required=True)
    publish.add_argument("--result", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate-dispatch":
            if args.action not in {"start", "resume"}:
                raise ContractError("action must be start or resume")
            fixed_milestone_path(REPO_ROOT, args.milestone)
            _write_output({"action": args.action, "milestone": args.milestone})
            return 0
        if args.command == "fingerprint":
            _write_output(validate_environment(args.role))
            return 0
        if args.command == "recover":
            recover(
                REPO_ROOT,
                args.runtime_root,
                require_docker=args.role in {"verify", "real"},
            )
            _write_output({"status": "PASS", "role": args.role})
            return 0
        if args.command == "seal-m2-discovery":
            result = seal_m2_discovery_result(
                raw_result_path=args.raw_result,
                evidence_root=args.evidence,
                output_path=args.output,
                expected_sha=args.expected_sha,
                expected_lease_sha256=args.expected_lease_sha256,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
                run_outcome=args.run_outcome,
                cleanup_outcome=args.cleanup_outcome,
            )
            _write_output(result)
            return 0
        if args.command == "seal-milestone-result":
            result = seal_milestone_result(
                raw_result_path=args.raw_result,
                output_path=args.output,
                milestone=args.milestone,
                expected_sha=args.expected_sha,
                expected_lease_sha256=args.expected_lease_sha256,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
                gate_outcome=args.gate_outcome,
                pre_cleanup_outcome=args.pre_cleanup_outcome,
                cleanup_outcome=args.cleanup_outcome,
                evidence_outcome=args.evidence_outcome,
            )
            _write_output(result)
            return 0
        client = GitHubClient.from_environment()
        if args.command == "coordinate":
            _write_output(
                coordinate(
                    client=client,
                    repo_root=REPO_ROOT,
                    runtime_root=args.runtime_root,
                    action=args.action,
                    milestone=args.milestone,
                )
            )
            return 0
        if args.command == "pr-metadata":
            metadata = pr_metadata(client, args.event)
            path = verification_metadata_path()
            with path.open("x", encoding="utf-8") as handle:
                json.dump(metadata, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
            _write_output(metadata)
            return 0
        if args.command == "authorize-real-invocation":
            validate_environment("real")
            try:
                result = authorize_real_invocation(
                    client,
                    REPO_ROOT,
                    milestone=args.milestone,
                    entrypoint=args.entrypoint,
                    expected_sha=args.expected_sha,
                    expected_readiness_sha256=args.expected_readiness_sha256,
                    run_id=args.run_id,
                    run_attempt=args.run_attempt,
                )
            except LeaseConfirmationBlocked as exc:
                _write_output(exc.receipt)
                raise
            _write_output(result)
            return 0
        if args.command == "run-milestone":
            result = run_gate(
                client=client,
                repo_root=REPO_ROOT,
                milestone=args.milestone,
                expected_sha=args.expected_sha,
                expected_lease_sha256=args.expected_lease_sha256,
            )
            result = bind_real_result(
                result,
                milestone=args.milestone,
                entrypoint="milestone",
                expected_sha=args.expected_sha,
                expected_lease_sha256=args.expected_lease_sha256,
            )
            result_path = (
                Path(os.environ.get("RUNNER_TEMP", "/tmp"))
                / "milestone-raw-result.json"
            )
            result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            _write_output({**result, "result": str(result_path)})
            return 0
        if args.command == "run-m2-discovery":
            result = run_m2_discovery(
                client=client,
                repo_root=REPO_ROOT,
                expected_sha=args.expected_sha,
                expected_lease_sha256=args.expected_lease_sha256,
            )
            result = bind_real_result(
                result,
                milestone="m2",
                entrypoint="discovery",
                expected_sha=args.expected_sha,
                expected_lease_sha256=args.expected_lease_sha256,
            )
            result_path = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "m2-discovery-raw-result.json"
            result_path.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            _write_output({**result, "result": str(result_path)})
            return 0
        if args.command == "record-m2-discovery":
            try:
                result = load_m2_discovery_result(
                    result_path=args.result,
                    evidence_root=args.evidence,
                    expected_sha=args.expected_sha,
                    expected_lease_sha256=args.expected_lease_sha256,
                    run_id=args.run_id,
                    run_attempt=args.run_attempt,
                )
            except (ContractError, OSError, json.JSONDecodeError) as exc:
                result = human_required_m2_discovery_result(
                    expected_sha=args.expected_sha,
                    expected_lease_sha256=args.expected_lease_sha256,
                    run_id=args.run_id,
                    run_attempt=args.run_attempt,
                    summary=f"M2 discovery artifact validation failed: {exc}",
                )
            action = record_m2_discovery_result(client=client, result=result)
            _write_output(
                {
                    "status": action,
                    "discovery_status": result["status"],
                    "milestone": "m2",
                }
            )
            return 0
        if args.command == "record-milestone":
            if args.expected_lease_sha256 == "":
                fixed_milestone_path(REPO_ROOT, args.milestone)
                if (
                    args.environment_started == ""
                    or re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is None
                    or re.fullmatch(r"[1-9][0-9]{0,19}", args.run_id) is None
                    or re.fullmatch(r"[1-9][0-9]{0,9}", args.run_attempt) is None
                    or args.run_id != os.environ.get("GITHUB_RUN_ID")
                    or args.run_attempt != os.environ.get("GITHUB_RUN_ATTEMPT")
                ):
                    raise ContractError("real authorization preflight identity is invalid")
                result = {
                    "status": "BLOCKED",
                    "summary": (
                        "Protected valkey-real job started, but authorization preflight did "
                        "not produce a confirmed consumed "
                        f"Lease (checkout={args.environment_started}; run={args.run_id}; "
                        f"attempt={args.run_attempt})"
                    ),
                }
            else:
                try:
                    result = load_milestone_result(
                        result_path=args.result,
                        milestone=args.milestone,
                        expected_sha=args.expected_sha,
                        expected_lease_sha256=args.expected_lease_sha256,
                        run_id=args.run_id,
                        run_attempt=args.run_attempt,
                    )
                except (ContractError, OSError, json.JSONDecodeError) as exc:
                    result = blocked_milestone_result(
                        milestone=args.milestone,
                        expected_sha=args.expected_sha,
                        expected_lease_sha256=args.expected_lease_sha256,
                        run_id=args.run_id,
                        run_attempt=args.run_attempt,
                        summary=f"Milestone result artifact validation failed: {exc}",
                    )
            action = record_milestone_result(
                client=client,
                milestone=args.milestone,
                expected_sha=args.expected_sha,
                status=result["status"],
                summary=result.get("summary", ""),
            )
            if action == "DIAGNOSE":
                client.dispatch(args.milestone)
            _write_output({"status": action, "milestone": args.milestone})
            return 0
        if args.command == "after-pr":
            metadata = pr_metadata(client, args.event)
            if metadata["action"] == "closed" and metadata["merged"]:
                client.dispatch(metadata["milestone"])
                _write_output({"status": "DISPATCHED", "milestone": metadata["milestone"]})
            else:
                _write_output({"status": "NOOP", "milestone": metadata["milestone"]})
            return 0
        if args.command == "publish-verification":
            result = json.loads(args.result.read_text(encoding="utf-8"))
            record = result.get("record") if isinstance(result, dict) else None
            status = record.get("status") if isinstance(record, dict) else "BLOCKED"
            if status not in {"PASS", "FAIL", "BLOCKED"}:
                status = "BLOCKED"
            event_path = os.environ.get("GITHUB_EVENT_PATH")
            if not event_path:
                raise ContractError("verification publication lacks its pull request event")
            metadata = pr_metadata(client, Path(event_path))
            metadata_changed = (
                metadata["pr"] != args.pr
                or metadata["head_sha"] != args.head_sha
                or metadata["milestone"] != args.milestone
                or metadata["contract_change"] != (args.contract_change == "true")
            )
            record_matches = (
                isinstance(record, dict)
                and record.get("base_sha") == metadata["base_sha"]
                and record.get("head_sha") == metadata["head_sha"]
                and record.get("work_item_check") == metadata["check"]
                and record.get("work_item") == metadata["work_item"]
                and record.get("contract_change") is metadata["contract_change"]
            )
            if metadata_changed or (status != "BLOCKED" and not record_matches):
                raise LoopBlocked(
                    "live pull request metadata changed during fixed-head verification"
                )
            if status == "PASS":
                marker = "<!-- milestone-loop-verification: " + json.dumps(
                    record, sort_keys=True, separators=(",", ":")
                ) + " -->"
                client.comment(
                    args.pr,
                    "Trusted candidate verification PASS.\n\n" + marker,
                )
            summary = result.get("error", "") if isinstance(result, dict) else "invalid result"
            if not summary:
                summary = "; ".join(
                    f"{' '.join(item.get('command', []))}: exit {item.get('exit_code')}"
                    for item in result.get("commands", [])
                    if isinstance(item, dict)
                )
            client.create_check_run(
                name="milestone-loop / candidate",
                head_sha=args.head_sha,
                conclusion=github_conclusion(status),
                title=f"Candidate verification {status}",
                summary=summary or status,
            )
            if (
                status != "BLOCKED"
                and args.contract_change == "false"
            ):
                client.dispatch(args.milestone)
            elif status == "FAIL" and args.contract_change == "true":
                snapshot = collect_snapshot(client, args.milestone)
                if trusted_m2_discovery_repair_pr(
                    snapshot,
                    pr_number=args.pr,
                    head_sha=args.head_sha,
                ):
                    client.dispatch(args.milestone)
            _write_output({"status": status, "milestone": args.milestone})
            return 0
    except (ContractError, GitHubError, LoopBlocked, OSError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 78
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
