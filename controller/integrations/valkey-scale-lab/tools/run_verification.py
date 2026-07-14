#!/usr/bin/env python3
"""Operator-owned verification receipt producer for a staged product snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


FINGERPRINT_SCRIPT = r'''
import hashlib, importlib.metadata, json, pathlib, sys

def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

closure = []
for name in ("pytest", "pluggy", "packaging", "iniconfig"):
    distribution = importlib.metadata.distribution(name)
    files = []
    for item in distribution.files or ():
        path = pathlib.Path(distribution.locate_file(item))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
            files.append({"path": str(item), "sha256": file_digest(path)})
    closure.append({"name": name, "version": distribution.version, "files": sorted(files, key=lambda row: row["path"])})
payload = json.dumps(closure, sort_keys=True, separators=(",", ":")).encode()
python_path = pathlib.Path(sys.executable).resolve()
print(json.dumps({
    "schema_version": "valkey-verification-policy-v1",
    "python_executable_sha256": file_digest(python_path),
    "pytest_version": importlib.metadata.version("pytest"),
    "pytest_package_digest": hashlib.sha256(payload).hexdigest(),
}, sort_keys=True))
'''


class ProducerError(RuntimeError):
    pass


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProducerError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProducerError(f"{path} must contain an object")
    return value


def product_tree_digest(product_root: Path) -> str:
    root = Path(product_root).resolve()
    if not root.is_dir() or root.is_symlink():
        raise ProducerError(f"product root must be a real directory: {root}")
    manifest: dict[str, dict[str, Any]] = {}
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in sorted((*directories, *files)):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                raise ProducerError(f"product snapshot contains a symlink: {relative}")
            if stat.S_ISDIR(info.st_mode):
                manifest[relative] = {"kind": "directory", "mode": mode}
            elif stat.S_ISREG(info.st_mode):
                manifest[relative] = {
                    "kind": "file",
                    "mode": mode,
                    "size": info.st_size,
                    "sha256": file_digest(path),
                }
            else:
                raise ProducerError(f"product snapshot contains a special file: {relative}")
    return canonical_digest(
        {"product": {"kind": "directory", "manifest": dict(sorted(manifest.items()))}}
    )


def fingerprint(python: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [str(Path(python).resolve()), "-c", FINGERPRINT_SCRIPT],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ProducerError(f"cannot fingerprint verification Python: {completed.stderr.strip()}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProducerError("verification Python returned an invalid fingerprint") from exc
    if not isinstance(value, dict):
        raise ProducerError("verification Python fingerprint is not an object")
    value["toolchain_digest"] = canonical_digest(value)
    return value


def _selected_suite_ids(milestone: dict[str, Any]) -> list[str]:
    values: set[str] = set()
    for condition in milestone.get("success_conditions", []):
        if isinstance(condition, dict):
            values.update(
                item for item in condition.get("suite_ids", []) if isinstance(item, str)
            )
    return sorted(values)


def produce(
    *,
    python: Path,
    workspace_root: Path,
    product_relative: str,
    milestone_id: str,
    run_id: str,
    expected_product_digest: str,
    evidence_root: Path,
    policy_path: Path,
    allowed_capabilities: list[str],
) -> dict[str, Any]:
    workspace = Path(workspace_root).resolve()
    product_root = (workspace / product_relative).resolve()
    if not product_root.is_relative_to(workspace):
        raise ProducerError("product root escapes the staged workspace")
    evidence = Path(evidence_root).resolve()
    if evidence.is_relative_to(workspace):
        raise ProducerError("operator evidence root must be outside the worker workspace")
    policy = load_json(policy_path)
    current_toolchain = fingerprint(python)
    if current_toolchain != policy:
        raise ProducerError("verification Python does not match the operator-sealed policy")
    before = product_tree_digest(product_root)
    if before != expected_product_digest:
        raise ProducerError("staged product digest does not match the CONTROLLER bind challenge")
    milestone_path = product_root / "milestones" / milestone_id / "milestone.json"
    catalog_path = product_root / "verification" / "catalog.json"
    runner_path = product_root / "verification" / "run.py"
    milestone = load_json(milestone_path)
    catalog = load_json(catalog_path)
    catalog_by_id = {
        row.get("id"): row
        for row in catalog.get("suites", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    producer_digest = file_digest(Path(__file__).resolve())
    receipt_root = evidence / "verification"
    log_root = receipt_root / "logs"
    result_root = receipt_root / "results"
    log_root.mkdir(parents=True, exist_ok=True)
    result_root.mkdir(parents=True, exist_ok=True)
    receipts: list[dict[str, Any]] = []
    for suite_id in _selected_suite_ids(milestone):
        suite = catalog_by_id.get(suite_id)
        if not isinstance(suite, dict):
            raise ProducerError(f"milestone references unknown suite {suite_id}")
        started = int(time.time())
        command = [
            str(Path(python).resolve()),
            str(runner_path),
            "suite",
            "--id",
            suite_id,
        ]
        for capability in allowed_capabilities:
            command.extend(["--allow-capability", capability])
        suite_result_path = result_root / f"{suite_id}.json"
        command.extend(["--result", str(suite_result_path)])
        environment = {
            "HOME": str(receipt_root / "home"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": str(Path(python).resolve().parent),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "TMPDIR": str(receipt_root / "tmp"),
        }
        Path(environment["HOME"]).mkdir(parents=True, exist_ok=True)
        Path(environment["TMPDIR"]).mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            command,
            cwd=product_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        captured = int(time.time())
        log_path = log_root / f"{suite_id}.log"
        log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
        relative_log = log_path.relative_to(evidence).as_posix()
        if suite_result_path.is_file():
            suite_result = load_json(suite_result_path)
        else:
            suite_result = {
                "schema_version": "verification-suite-result-v1",
                "suite_id": suite_id,
                "status": "FAIL",
                "exit_code": completed.returncode,
                "skipped": 0,
                "started_at_unix": started,
                "captured_at_unix": captured,
            }
            suite_result_path.write_text(
                json.dumps(suite_result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        expected_status = (
            "PASS" if completed.returncode == 0 else "BLOCKED" if completed.returncode == 2 else "FAIL"
        )
        if (
            suite_result.get("schema_version") != "verification-suite-result-v1"
            or suite_result.get("suite_id") != suite_id
            or suite_result.get("status") != expected_status
            or suite_result.get("exit_code") != completed.returncode
            or not isinstance(suite_result.get("skipped"), int)
        ):
            raise ProducerError(f"suite {suite_id} returned an invalid structured result")
        relative_result = suite_result_path.relative_to(evidence).as_posix()
        receipt: dict[str, Any] = {
            "suite_id": suite_id,
            "suite_definition_digest": canonical_digest(suite),
            "status": expected_status,
            "run_id": run_id,
            "product_digest": expected_product_digest,
            "started_at_unix": suite_result["started_at_unix"],
            "captured_at_unix": suite_result["captured_at_unix"],
            "exit_code": completed.returncode,
            "skipped": suite_result["skipped"],
            "command_digest": canonical_digest(suite.get("argv")),
            "log": {"path": relative_log, "sha256": file_digest(log_path)},
            "suite_result": {
                "path": relative_result,
                "sha256": file_digest(suite_result_path),
            },
            "producer_digest": producer_digest,
            "toolchain_digest": current_toolchain["toolchain_digest"],
        }
        receipt["receipt_digest"] = canonical_digest(receipt)
        receipts.append(receipt)
    after = product_tree_digest(product_root)
    if after != before:
        raise ProducerError("verification mutated the staged product snapshot")
    envelope: dict[str, Any] = {
        "schema_version": "verification-receipts-v2",
        "run_id": run_id,
        "product_digest": expected_product_digest,
        "milestone_digest": canonical_digest(milestone),
        "catalog_digest": canonical_digest(catalog),
        "generated_at_unix": int(time.time()),
        "producer_digest": producer_digest,
        "toolchain_digest": current_toolchain["toolchain_digest"],
        "receipts": receipts,
    }
    envelope["envelope_digest"] = canonical_digest(envelope)
    output = receipt_root / "receipts.json"
    output.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return envelope


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fingerprint_command = commands.add_parser("fingerprint")
    fingerprint_command.add_argument("--python", type=Path, required=True)
    fingerprint_command.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--python", type=Path, required=True)
    run.add_argument("--workspace-root", type=Path, required=True)
    run.add_argument("--product-relative", default="product")
    run.add_argument("--milestone", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--product-digest", required=True)
    run.add_argument("--evidence-root", type=Path, required=True)
    run.add_argument("--policy", type=Path, required=True)
    run.add_argument("--allow-capability", action="append", default=[])
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "fingerprint":
            value = fingerprint(args.python)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return 0
        envelope = produce(
            python=args.python,
            workspace_root=args.workspace_root,
            product_relative=args.product_relative,
            milestone_id=args.milestone,
            run_id=args.run_id,
            expected_product_digest=args.product_digest,
            evidence_root=args.evidence_root,
            policy_path=args.policy,
            allowed_capabilities=args.allow_capability,
        )
        return 0 if all(row["status"] == "PASS" for row in envelope["receipts"]) else 1
    except (ProducerError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: verification producer: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
