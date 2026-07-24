from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping, Sequence

from contracts import (
    ContractError,
    require_candidate_check,
    strict_json_loads,
    verification_metadata_path,
    verified_tree,
)
from coordinator import protected_changes


SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _run(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str] | None = None,
    timeout: int = 7200,
) -> tuple[int, str]:
    try:
        process = subprocess.run(
            list(argv),
            cwd=cwd,
            env=None if environment is None else dict(environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 125, str(exc)
    return process.returncode, process.stdout[-20_000:]


def _candidate_environment() -> dict[str, str]:
    blocked = (
        "GH_",
        "GITHUB_",
        "AWS_",
        "AZURE_",
        "GOOGLE_",
        "CODEX_",
        "OPENAI_",
        "VALKEY_REAL_",
        "MILESTONE_LEASE_",
    )
    result = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(blocked) and key != "SSH_AUTH_SOCK"
    }
    result.update(
        {
            "NO_COLOR": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
    )
    return result


def _docker_residue() -> tuple[str, ...]:
    commands = (
        ["docker", "ps", "-a", "-q", "--filter", "label=org.valkey-scale-lab.project=valkey-scale-lab"],
        ["docker", "network", "ls", "-q", "--filter", "label=org.valkey-scale-lab.project=valkey-scale-lab"],
    )
    found: list[str] = []
    for command in commands:
        code, output = _run(command, cwd=Path.cwd(), timeout=30)
        if code != 0:
            raise ContractError(f"Docker residue preflight unavailable: {output[-1000:].strip()}")
        found.extend(line.strip() for line in output.splitlines() if line.strip())
    return tuple(found)


def _git(cwd: Path, *args: str) -> str:
    code, output = _run(["git", *args], cwd=cwd, timeout=120)
    if code != 0:
        raise ContractError(f"git {' '.join(args)} failed: {output[-2000:].strip()}")
    return output.strip()


def verify(
    *,
    trusted_root: Path,
    candidate_root: Path,
    base_sha: str,
    head_sha: str,
    check_id: str,
    pr_number: int,
    contract_change: bool,
) -> dict[str, object]:
    if SHA_RE.fullmatch(base_sha) is None or SHA_RE.fullmatch(head_sha) is None:
        raise ContractError("base and head must be full lowercase Git SHAs")
    actual_head = _git(candidate_root, "rev-parse", "HEAD")
    if actual_head != head_sha:
        raise ContractError("candidate checkout does not match the event head SHA")
    metadata_path = verification_metadata_path()
    if not metadata_path.is_file() or metadata_path.is_symlink():
        raise ContractError("trusted live PR metadata is unavailable")
    metadata = strict_json_loads(
        metadata_path.read_text(encoding="utf-8"),
        max_bytes=8_192,
    )
    if (
        not isinstance(metadata, dict)
        or set(metadata)
        != {
            "action",
            "base_sha",
            "check",
            "contract_change",
            "head_sha",
            "merged",
            "milestone",
            "pr",
            "work_item",
        }
        or metadata.get("pr") != pr_number
        or metadata.get("base_sha") != base_sha
        or metadata.get("head_sha") != head_sha
        or metadata.get("check") != check_id
        or metadata.get("contract_change") is not contract_change
        or metadata.get("merged") is not False
        or isinstance(metadata.get("work_item"), bool)
        or not isinstance(metadata.get("work_item"), int)
        or metadata["work_item"] <= 0
    ):
        raise ContractError("trusted live PR metadata changed before verification")
    metadata_path.unlink()
    paths = tuple(
        path
        for path in _git(candidate_root, "diff", "--name-only", base_sha, head_sha).splitlines()
        if path
    )
    protected = protected_changes(paths)
    if protected and not contract_change:
        raise ContractError(f"ordinary Work Item PR changes protected contracts: {list(protected)}")
    if contract_change and not protected:
        raise ContractError("contract-change label is only valid when protected contracts change")
    catalog = json.loads((trusted_root / "project" / "catalog.json").read_text(encoding="utf-8"))
    check_command = require_candidate_check(catalog, check_id)
    residue_before = _docker_residue()
    if residue_before:
        raise ContractError(f"verifier preflight found residual project resources: {residue_before}")
    environment = _candidate_environment()
    results: list[dict[str, object]] = []
    commands: list[tuple[str, ...]] = [("./gate", "suite", "repository.all")]
    if check_command != commands[0]:
        commands.append(check_command)
    status = "PASS"
    for command in commands:
        code, output = _run(
            command,
            cwd=candidate_root / "project",
            environment=environment,
        )
        results.append({"command": list(command), "exit_code": code, "output_tail": output[-4000:]})
        if code == 125:
            status = "BLOCKED"
            break
        if code != 0:
            status = "FAIL"
            break
    if contract_change:
        code, output = _run(
            ["python3", ".github/milestone-loop/selftest.py"],
            cwd=candidate_root,
            environment=environment,
            timeout=1800,
        )
        results.append(
            {
                "command": ["python3", ".github/milestone-loop/selftest.py"],
                "exit_code": code,
                "output_tail": output[-4000:],
            }
        )
        if code == 125 and status != "FAIL":
            status = "BLOCKED"
        elif code != 0:
            status = "FAIL"
    residue_after = _docker_residue()
    if residue_after:
        status = "BLOCKED"
    tree_sha = _git(candidate_root, "rev-parse", "HEAD^{tree}")
    record = {
        "version": 1,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "tree_sha": tree_sha,
        "verified_tree": verified_tree(base_sha, head_sha, tree_sha),
        "baseline": "repository.all",
        "work_item_check": check_id,
        "work_item": metadata["work_item"],
        "contract_change": contract_change,
        "status": status,
    }
    return {
        "record": record,
        "protected_changes": list(protected),
        "commands": results,
        "residue_before": list(residue_before),
        "residue_after": list(residue_after),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trusted-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--check", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--contract-change", action="store_true")
    parser.add_argument("--result", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify(
            trusted_root=args.trusted_root.resolve(),
            candidate_root=args.candidate_root.resolve(),
            base_sha=args.base_sha,
            head_sha=args.head_sha,
            check_id=args.check,
            pr_number=args.pr,
            contract_change=args.contract_change,
        )
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        result = {"record": {"status": "BLOCKED"}, "error": str(exc)}
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = result["record"]["status"]
    if status == "PASS":
        print(json.dumps(result["record"], sort_keys=True))
        return 0
    print(json.dumps(result, sort_keys=True))
    return 1 if status == "FAIL" else 78


if __name__ == "__main__":
    raise SystemExit(main())
