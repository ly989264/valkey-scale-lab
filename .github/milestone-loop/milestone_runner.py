from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts import ContractError, fixed_milestone_path
from coordinator import CONTROL_LABEL, LoopBlocked, consume_lease, parse_control
from github_api import GitHubClient, collect_snapshot
from recovery import cleanup_owned_docker


def authorize(client: GitHubClient, repo_root: Path, milestone: str) -> dict[str, Any]:
    fixed_milestone_path(repo_root, milestone)
    snapshot = collect_snapshot(client, milestone)
    consumed = consume_lease(client, snapshot)
    return {
        "authorized": True,
        "milestone": milestone,
        "default_sha": snapshot["default_sha"],
        "lease_nonce": consumed.lease["nonce"],
        "lease_sha256": _lease_fingerprint(consumed.lease),
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


def _gate_environment() -> dict[str, str]:
    blocked = ("GH_", "GITHUB_", "CODEX_", "OPENAI_", "MILESTONE_LOOP_")
    result = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(blocked)
    }
    result["NO_COLOR"] = "1"
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    return result


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
            env=_gate_environment(),
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
            "summary": f"Gate exit={process.returncode}; summary status={summary.get('status') if isinstance(summary, dict) else 'invalid'}",
            "exit_code": process.returncode,
            "artifacts": str(artifacts),
        }
    finally:
        cleanup_owned_docker()
