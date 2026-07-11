#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import exit_code, print_gate_summary, relpath, violation, write_gate_result

GATE = "assert_no_simulated_subagents"
FORBIDDEN_PHRASES = [
    "simulated design subagent",
    "simulated worker subagent",
    "simulated review subagent",
    "explicit subagent launch failed",
    "usage-limit error; this document preserves",
    "performed as a separate role artifact",
]
ROLE_FILES = {
    "agents/design.md": "design",
    "agents/worker.md": "worker",
    "agents/review.md": "review",
    "handoff/DESIGN_BRIEF.md": "design",
    "handoff/WORKER_SUMMARY.md": "worker",
    "handoff/REVIEW.md": "review",
}


def scan_stage_artifacts(root: Path, stage_id: str, *, require_all: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    stage_root = root / "runs" / "m1-hardening" / stage_id
    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    for subdir in ["agents", "handoff"]:
        directory = stage_root / subdir
        if not directory.exists():
            blocked.append(f"{relpath(root, directory)} is missing.")
            continue
        for path in directory.glob("*.md"):
            _scan_forbidden(root, path, violations)
    for rel, role in ROLE_FILES.items():
        path = stage_root / rel
        if not path.exists():
            if require_all:
                blocked.append(f"{relpath(root, path)} is missing.")
            continue
        _validate_metadata(root, path, role, stage_id, violations)
    return violations, blocked


def _scan_forbidden(root: Path, path: Path, violations: list[dict[str, Any]]) -> None:
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        lowered = line.lower()
        for phrase in FORBIDDEN_PHRASES:
            if phrase in lowered:
                violations.append(violation("forbidden_subagent_phrase", "Stage artifact contains a C12 forbidden phrase.", path=relpath(root, path), line=index, details={"phrase": phrase}))


def _validate_metadata(root: Path, path: Path, role: str, stage_id: str, violations: list[dict[str, Any]]) -> None:
    text = path.read_text(encoding="utf-8")
    required = {
        "role": f"role: {role}",
        "agent_invocation": "agent_invocation: real_subagent",
        "stage_id": f"stage_id: {stage_id}",
        "source_commit_before": "source_commit_before:",
    }
    for code, needle in required.items():
        if needle not in text:
            violations.append(violation(f"missing_{code}", f"Agent artifact is missing metadata {needle!r}.", path=relpath(root, path)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject simulated subagent artifacts.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--allow-blocked", action="store_true")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    violations, blocked = scan_stage_artifacts(root, args.stage, require_all=args.require_all)
    status = "FAIL" if violations else "BLOCKED_WITH_REASON" if blocked else "PASS"
    result = write_gate_result(
        root=root,
        stage_id=args.stage,
        gate_name=GATE,
        status=status,
        inputs=[f"runs/m1-hardening/{args.stage}/agents", f"runs/m1-hardening/{args.stage}/handoff"],
        violations=violations,
        blocked_reasons=blocked,
    )
    print_gate_summary(result)
    return exit_code(status, allow_blocked=args.allow_blocked)


if __name__ == "__main__":
    raise SystemExit(main())
