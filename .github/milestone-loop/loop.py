#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
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
    require_candidate_check,
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
    authorize_real_invocation,
    bind_real_result,
    human_required_m2_discovery_result,
    load_m2_discovery_result,
    run_gate,
    run_m2_discovery,
    seal_m2_discovery_result,
    validate_real_result_binding,
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


def pr_metadata(client: GitHubClient, event_path: Path) -> dict[str, Any]:
    event = _event(event_path)
    pr = event.get("pull_request")
    repository = event.get("repository")
    if not isinstance(pr, dict) or not isinstance(repository, dict):
        raise ContractError("event is not a pull_request event")
    head = pr.get("head")
    base = pr.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise ContractError("pull_request head or base is missing")
    head_repo = head.get("repo")
    full_name = repository.get("full_name")
    if not isinstance(head_repo, dict) or head_repo.get("full_name") != full_name:
        raise LoopBlocked("fork pull requests cannot execute on the local Mac")
    association = pr.get("author_association")
    if association not in {"OWNER", "MEMBER", "COLLABORATOR"}:
        raise LoopBlocked("pull request author is not trusted for self-hosted execution")
    body = pr.get("body") or ""
    if not isinstance(body, str):
        raise ContractError("pull request body is invalid")
    milestone = milestone_from_pr_body(body)
    fixed_milestone_path(REPO_ROOT, milestone)
    labels = {
        item.get("name")
        for item in pr.get("labels", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    contract_change = "contract-change" in labels or "Contract-Change: true" in body
    if contract_change:
        check = "repository.all"
    else:
        import re

        matches = re.findall(r"(?m)^Work-Item: #([1-9][0-9]*)$", body)
        if len(matches) != 1:
            raise ContractError("ordinary pull request must reference exactly one Work-Item")
        issue_number = int(matches[0])
        snapshot = collect_snapshot(client, milestone)
        issue = next(
            (item for item in snapshot["issues"] if item.get("number") == issue_number),
            None,
        )
        if issue is None:
            raise ContractError("referenced Work Item is absent from the Milestone")
        check = parse_work_item(issue.get("body", "")).check
        catalog = json.loads((REPO_ROOT / "project" / "catalog.json").read_text(encoding="utf-8"))
        require_candidate_check(catalog, check)
    number = pr.get("number")
    if not isinstance(number, int):
        raise ContractError("pull request number is invalid")
    return {
        "pr": number,
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
            _write_output(pr_metadata(client, args.event))
            return 0
        if args.command == "authorize-real-invocation":
            validate_environment("real")
            _write_output(
                authorize_real_invocation(
                    client,
                    REPO_ROOT,
                    milestone=args.milestone,
                    entrypoint=args.entrypoint,
                    expected_sha=args.expected_sha,
                    expected_readiness_sha256=args.expected_readiness_sha256,
                    run_id=args.run_id,
                    run_attempt=args.run_attempt,
                )
            )
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
            result_path = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "milestone-result.json"
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
            if (
                not args.result.is_file()
                or args.result.is_symlink()
                or args.result.stat().st_size > 32_768
            ):
                raise ContractError("Milestone result artifact is missing or exceeds its bound")
            result = json.loads(args.result.read_text(encoding="utf-8"))
            validate_real_result_binding(
                result,
                milestone=args.milestone,
                entrypoint="milestone",
                expected_sha=args.expected_sha,
                expected_lease_sha256=args.expected_lease_sha256,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
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
            if status == "PASS":
                marker = "<!-- milestone-loop-verification: " + json.dumps(
                    record, sort_keys=True, separators=(",", ":")
                ) + " -->"
                client.comment(args.pr, "Trusted candidate verification PASS.\n\n" + marker)
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
            if status != "BLOCKED" and args.contract_change == "false":
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
