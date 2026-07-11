#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUSES = {"PASS", "FAIL", "BLOCKED_WITH_REASON"}
EXIT_CODES = {"PASS": 0, "FAIL": 1, "BLOCKED_WITH_REASON": 2}


def repo_root_from(path: Path) -> Path:
    current = path.resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return current


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def source_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"
    return result.stdout.strip() or "UNKNOWN"


def relpath(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def gate_result_path(root: Path, stage_id: str, gate_name: str) -> Path:
    return root / "runs" / "m1-hardening" / stage_id / "artifacts" / "gates" / f"{gate_name}.json"


def violation(
    code: str,
    message: str,
    *,
    path: str | None = None,
    line: int | None = None,
    claim_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "message": message}
    if path is not None:
        item["path"] = path
    if line is not None:
        item["line"] = line
    if claim_id is not None:
        item["claim_id"] = claim_id
    if details:
        item["details"] = details
    return item


def write_gate_result(
    *,
    root: Path,
    stage_id: str,
    gate_name: str,
    status: str,
    inputs: list[str],
    violations: list[dict[str, Any]] | None = None,
    blocked_reasons: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        status = "FAIL"
        violations = [
            *(violations or []),
            violation("invalid_status", f"Gate attempted to write invalid status {status!r}."),
        ]
    payload: dict[str, Any] = {
        "schema_version": "v1",
        "artifact_type": "m1h_gate_result",
        "stage_id": stage_id,
        "gate_name": gate_name,
        "status": status,
        "checked_at": utc_now(),
        "inputs": inputs,
        "violations": violations or [],
        "blocked_reasons": blocked_reasons or [],
        "source_commit": source_commit(root),
    }
    if extra:
        payload.update(extra)
    write_json(gate_result_path(root, stage_id, gate_name), payload)
    return payload


def exit_code(status: str, *, allow_blocked: bool = False) -> int:
    if status == "BLOCKED_WITH_REASON" and allow_blocked:
        return 0
    return EXIT_CODES.get(status, 1)


def print_gate_summary(result: dict[str, Any]) -> None:
    target = gate_result_path(Path("."), result["stage_id"], result["gate_name"])
    print(f"{result['status']}: {result['gate_name']} wrote {target.as_posix()}")
