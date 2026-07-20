from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts import ContractError, fixed_milestone_path
from coordinator import (
    CONTROL_LABEL,
    LoopBlocked,
    consume_lease,
    load_trusted_documents,
    m2_candidate_blockers,
    m2_discovery_eligible,
    parse_control,
)
from github_api import GitHubClient, collect_snapshot
from recovery import cleanup_owned_docker


_GATE_DIAGNOSTIC_MAX_CHARS = 3800
_GATE_DIAGNOSTIC_MAX_ROWS = 8
_GATE_DIAGNOSTIC_DETAIL_MAX_CHARS = 400
_GATE_DIAGNOSTIC_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}")
_M2_DISCOVERY_REPORT_NAME = "m2_candidate_discovery.json"
_M2_ADMISSION_REPORT_NAME = "m2_performance_report.json"


def _diagnostic_identifier(value: Any) -> str:
    if isinstance(value, str) and _GATE_DIAGNOSTIC_ID_RE.fullmatch(value):
        return value
    return "invalid"


def _m2_discovery_run_id() -> str:
    github_run_id = os.environ.get("GITHUB_RUN_ID", "")
    github_run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if not github_run_id and not github_run_attempt:
        return f"m2-discovery-local-{uuid.uuid4().hex}"
    if (
        re.fullmatch(r"[1-9][0-9]{0,19}", github_run_id) is None
        or re.fullmatch(r"[1-9][0-9]{0,9}", github_run_attempt) is None
    ):
        raise ContractError("GitHub M2 discovery run identity is invalid")
    return f"m2-discovery-gh-{github_run_id}-attempt-{github_run_attempt}"


def _diagnostic_detail(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    safe = "".join(
        " " if character in "@<>`" or not character.isprintable() else character
        for character in value
    )
    safe = re.sub(r"(?<![A-Za-z0-9])/(?:[^\s,;]+)", "[absolute-path]", safe)
    return " ".join(safe.split())[:_GATE_DIAGNOSTIC_DETAIL_MAX_CHARS]


def _gate_result_summary(
    *,
    milestone: str,
    gate_status: str,
    summary: dict[str, Any],
    exit_code: int,
    expected_sha: str,
    invocation_id: str,
) -> str:
    raw_status = summary.get("status")
    result = f"Gate exit={exit_code}; summary status={raw_status}"
    if milestone != "m2" or gate_status != "FAIL":
        return result

    tests = summary.get("tests")
    non_pass = []
    if isinstance(tests, list):
        non_pass = [
            row
            for row in tests
            if isinstance(row, dict) and row.get("status") != "PASS"
        ]
    diagnostic: dict[str, Any] = {
        "diagnostic_only": True,
        "tested_sha": (
            expected_sha
            if re.fullmatch(r"[0-9a-f]{40}", expected_sha)
            else "invalid"
        ),
        "invocation_id": _diagnostic_identifier(invocation_id),
        "non_pass_total": len(non_pass),
        "failures": [],
    }
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if re.fullmatch(r"[0-9]{1,20}", run_id):
        diagnostic["evidence_artifact"] = f"milestone-evidence-{run_id}"
        diagnostic["evidence_summary"] = "summary.json"

    prefix = result + "; diagnostic only, not Criterion or admission evidence: "
    for row in non_pass[:_GATE_DIAGNOSTIC_MAX_ROWS]:
        failure: dict[str, Any] = {
            "instance_id": _diagnostic_identifier(row.get("instance_id")),
            "criterion_id": _diagnostic_identifier(row.get("criterion_id")),
            "check_id": _diagnostic_identifier(row.get("check_id")),
            "test_id": _diagnostic_identifier(row.get("test_id")),
            "status": _diagnostic_identifier(row.get("status")),
        }
        if isinstance(row.get("exit_code"), int):
            failure["exit_code"] = row["exit_code"]
        detail = _diagnostic_detail(row.get("detail"))
        if detail:
            failure["detail"] = detail
        diagnostic["failures"].append(failure)
        diagnostic["omitted_non_pass"] = len(non_pass) - len(diagnostic["failures"])
        rendered = prefix + json.dumps(
            diagnostic, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        if len(rendered) > _GATE_DIAGNOSTIC_MAX_CHARS:
            diagnostic["failures"].pop()
            break

    diagnostic["omitted_non_pass"] = len(non_pass) - len(diagnostic["failures"])
    return prefix + json.dumps(
        diagnostic, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def authorize(client: GitHubClient, repo_root: Path, milestone: str) -> dict[str, Any]:
    fixed_milestone_path(repo_root, milestone)
    snapshot = collect_snapshot(client, milestone)
    entrypoint = "milestone"
    if milestone == "m2":
        actual = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if actual.returncode != 0 or actual.stdout.strip() != snapshot["default_sha"]:
            raise LoopBlocked("authorization checkout does not match the live default SHA")
        milestone_document, _catalog_document = load_trusted_documents(repo_root, milestone)
        candidate_blockers = m2_candidate_blockers(milestone_document, milestone)
        if m2_discovery_eligible(milestone_document, milestone):
            entrypoint = "discovery"
        elif candidate_blockers:
            raise LoopBlocked(
                "M2 candidate is not ready for real authorization: "
                + ", ".join(candidate_blockers)
            )
        live = collect_snapshot(client, milestone)
        if live["default_sha"] != snapshot["default_sha"]:
            raise LoopBlocked("default branch changed before Authorization Lease consumption")
    else:
        live = snapshot
    consumed = consume_lease(client, live)
    return {
        "authorized": True,
        "milestone": milestone,
        "default_sha": live["default_sha"],
        "lease_nonce": consumed.lease["nonce"],
        "lease_sha256": _lease_fingerprint(consumed.lease),
        "entrypoint": entrypoint,
    }


def _lease_fingerprint(lease: Any) -> str:
    return hashlib.sha256(
        json.dumps(lease, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_consumed_lease(snapshot: dict[str, Any], expected_sha256: str) -> None:
    controls = [
        issue
        for issue in snapshot.get("issues", [])
        if CONTROL_LABEL in issue.get("labels", [])
    ]
    if len(controls) != 1:
        raise LoopBlocked("Milestone must retain exactly one Control Issue")
    state = parse_control(controls[0], str(snapshot["milestone"]))
    if _lease_fingerprint(state.lease) != expected_sha256:
        raise LoopBlocked("Authorization Lease changed after consumption")
    try:
        expires = datetime.fromisoformat(str(state.lease["expires_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise LoopBlocked("consumed Authorization Lease expiration is invalid") from exc
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise LoopBlocked("consumed Authorization Lease expired before the real Gate started")


def _gate_environment(milestone: str) -> dict[str, str]:
    blocked = ("GH_", "GITHUB_", "CODEX_", "OPENAI_", "MILESTONE_LOOP_")
    result = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(blocked)
    }
    result["NO_COLOR"] = "1"
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result.pop("VSLAB_M2_REAL_AUTHORIZATION", None)
    if milestone == "m2":
        result["VSLAB_M2_REAL_AUTHORIZATION"] = "1"
    return result


def run_m2_discovery(
    *,
    client: GitHubClient,
    repo_root: Path,
    expected_sha: str,
    expected_lease_sha256: str,
) -> dict[str, Any]:
    fixed_milestone_path(repo_root, "m2")
    snapshot = collect_snapshot(client, "m2")
    if re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None:
        raise ContractError("authorized M2 discovery SHA is invalid")
    if re.fullmatch(r"[0-9a-f]{64}", expected_lease_sha256) is None:
        raise ContractError("consumed Authorization Lease fingerprint is invalid")
    _validate_consumed_lease(snapshot, expected_lease_sha256)
    if snapshot.get("milestone") != "m2" or snapshot.get("default_sha") != expected_sha:
        raise LoopBlocked("default branch changed after M2 discovery authorization")
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if actual.returncode != 0 or actual.stdout.strip() != expected_sha:
        raise LoopBlocked("valkey-real discovery checkout does not match the authorized default SHA")
    milestone_document, _catalog_document = load_trusted_documents(repo_root, "m2")
    if not m2_discovery_eligible(milestone_document, "m2"):
        raise LoopBlocked("M2 candidate bindings are not the canonical unresolved discovery state")

    runner_temp = Path(os.environ.get("RUNNER_TEMP", "/tmp")).resolve()
    artifacts = runner_temp / "m2-discovery-evidence"
    command_result = runner_temp / "m2-discovery-command-result.json"
    bounded_result = runner_temp / "m2-discovery-result.json"
    fallback_log = runner_temp / "m2-discovery-control.log"
    report_path = artifacts / _M2_DISCOVERY_REPORT_NAME
    for path in (artifacts, command_result, bounded_result, fallback_log):
        if path.exists():
            raise LoopBlocked(f"refusing pre-existing M2 discovery output: {path.name}")
    script = repo_root / "project" / "scripts" / "m2_candidate_discovery.py"
    if not script.is_file() or script.is_symlink():
        raise ContractError("fixed M2 candidate discovery producer is missing or is a symlink")

    run_id = _m2_discovery_run_id()
    environment = _gate_environment("m2")
    environment["PYTHONPATH"] = str(repo_root / "project" / "src")
    cleanup_owned_docker()
    try:
        process = subprocess.run(
            [
                "python3",
                "scripts/m2_candidate_discovery.py",
                "--run-id",
                run_id,
                "--artifacts-dir",
                str(artifacts),
                "--result-path",
                str(command_result),
                "--tested-sha",
                expected_sha,
            ],
            cwd=repo_root / "project",
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        fallback_log.write_text(process.stdout, encoding="utf-8")
        if artifacts.is_symlink() or (artifacts.exists() and not artifacts.is_dir()):
            return {
                "status": "FAIL",
                "summary": "M2 discovery evidence root is not a regular directory",
                "exit_code": process.returncode,
                "artifacts": str(fallback_log),
            }
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "control-plane.log").write_text(process.stdout, encoding="utf-8")
        if any(path.name == _M2_ADMISSION_REPORT_NAME for path in artifacts.rglob("*")):
            return {
                "status": "FAIL",
                "summary": "M2 discovery produced a forbidden admission report",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        if not command_result.is_file() or command_result.is_symlink():
            return {
                "status": "FAIL",
                "summary": "M2 discovery did not produce its bounded command result",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        if not report_path.is_file() or report_path.is_symlink():
            return {
                "status": "FAIL",
                "summary": f"M2 discovery did not produce {_M2_DISCOVERY_REPORT_NAME}",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        try:
            command = json.loads(command_result.read_text(encoding="utf-8"))
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {
                "status": "FAIL",
                "summary": f"M2 discovery output is unreadable: {exc}",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        command_status = command.get("status") if isinstance(command, dict) else None
        summary = command.get("summary") if isinstance(command, dict) else None
        if (
            not isinstance(command, dict)
            or set(command) != {"status", "summary"}
            or command_status not in {"PASS", "FAIL", "BLOCKED"}
            or not isinstance(summary, str)
        ):
            return {
                "status": "FAIL",
                "summary": "M2 discovery command result violates its bounded contract",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        report_valid = (
            isinstance(report, dict)
            and report.get("schema_version") == "m2-candidate-discovery-v1"
            and report.get("artifact_type") == "m2_candidate_discovery"
            and report.get("purpose") == "candidate-selection-only"
            and report.get("admission_evidence") is False
            and report.get("current_invocation") is True
            and report.get("tested_sha") == expected_sha
            and report.get("invocation_run_id") == run_id
            and report.get("campaign_id") == run_id
            and report.get("status") == command_status
            and "criterion_results" not in report
            and "selected_candidate" not in report
            and isinstance(report.get("report_digest"), str)
            and re.fullmatch(r"[0-9a-f]{64}", report["report_digest"]) is not None
        )
        if not report_valid:
            return {
                "status": "FAIL",
                "summary": "M2 discovery report is not the authorized selection-only artifact",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        if process.returncode != 0:
            return {
                "status": "FAIL",
                "summary": f"M2 discovery producer exited {process.returncode}",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        return {
            "status": command_status,
            "summary": " ".join(summary.split())[:2000],
            "exit_code": process.returncode,
            "artifacts": str(artifacts),
            "report": str(report_path),
        }
    finally:
        cleanup_owned_docker()


def run_gate(
    *,
    client: GitHubClient,
    repo_root: Path,
    milestone: str,
    expected_sha: str,
    expected_lease_sha256: str,
) -> dict[str, Any]:
    fixed_milestone_path(repo_root, milestone)
    snapshot = collect_snapshot(client, milestone)
    if len(expected_lease_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in expected_lease_sha256
    ):
        raise ContractError("consumed Authorization Lease fingerprint is invalid")
    _validate_consumed_lease(snapshot, expected_lease_sha256)
    if snapshot["default_sha"] != expected_sha:
        raise LoopBlocked("default branch changed after Authorization Lease consumption")
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if actual.returncode != 0 or actual.stdout.strip() != expected_sha:
        raise LoopBlocked("valkey-real checkout does not match the authorized default SHA")
    cleanup_owned_docker()
    gate_runs = repo_root / "project" / "artifacts" / "gate-runs"
    before = {path.name for path in gate_runs.iterdir()} if gate_runs.is_dir() else set()
    log_path = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "milestone-gate.log"
    try:
        process = subprocess.run(
            ["./gate", "milestone", milestone],
            cwd=repo_root / "project",
            env=_gate_environment(milestone),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        log_path.write_text(process.stdout, encoding="utf-8")
        after = {path.name for path in gate_runs.iterdir()} if gate_runs.is_dir() else set()
        created = sorted(after - before)
        if len(created) != 1:
            return {
                "status": "BLOCKED",
                "summary": f"Gate created {len(created)} invocation directories; expected exactly one",
                "exit_code": process.returncode,
                "artifacts": str(log_path),
            }
        artifacts = gate_runs / created[0]
        summary_path = artifacts / "summary.json"
        if not summary_path.is_file():
            return {
                "status": "BLOCKED",
                "summary": "Gate did not produce its required summary.json",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        try:
            summary: Any = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {
                "status": "BLOCKED",
                "summary": f"Gate summary is invalid JSON: {exc}",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        if (
            not isinstance(summary, dict)
            or summary.get("schema_version") != "gate-summary-v1"
            or summary.get("selection") != {"kind": "milestone", "id": milestone}
        ):
            return {
                "status": "BLOCKED",
                "summary": "Gate summary does not identify the fixed Milestone invocation",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        status = summary.get("status") if isinstance(summary, dict) else None
        if status not in {"PASS", "FAIL", "BLOCKED"}:
            status = "BLOCKED"
        if (status == "PASS") != (process.returncode == 0):
            status = "BLOCKED"
        return {
            "status": status,
            "summary": _gate_result_summary(
                milestone=milestone,
                gate_status=status,
                summary=summary,
                exit_code=process.returncode,
                expected_sha=expected_sha,
                invocation_id=artifacts.name,
            ),
            "exit_code": process.returncode,
            "artifacts": str(artifacts),
        }
    finally:
        cleanup_owned_docker()
