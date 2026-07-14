#!/usr/bin/env python3
"""Run declared verification suites and write their structured result bundle."""

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


class VerificationError(RuntimeError):
    pass


EXCLUDED_ROOTS = {".pytest_cache", "artifacts", "audit", "runs"}
EXCLUDED_DIRECTORIES = {"__pycache__"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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
        raise VerificationError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{path} must contain an object")
    return value


def product_tree_digest(product_root: Path) -> str:
    root = Path(product_root).resolve()
    if not root.is_dir() or root.is_symlink():
        raise VerificationError(f"product root must be a real directory: {root}")
    manifest: dict[str, dict[str, Any]] = {}
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if name not in EXCLUDED_DIRECTORIES
            and not (current_path == root and name in EXCLUDED_ROOTS)
        )
        for name in sorted((*directories, *files)):
            path = current_path / name
            if path.suffix in EXCLUDED_SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                raise VerificationError(f"product contains a symlink: {relative}")
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
                raise VerificationError(f"product contains a special file: {relative}")
    return canonical_digest(
        {"product": {"kind": "directory", "manifest": dict(sorted(manifest.items()))}}
    )


def _selected_suite_ids(milestone: dict[str, Any]) -> list[str]:
    return sorted(
        {
            suite_id
            for condition in milestone.get("success_conditions", [])
            if isinstance(condition, dict)
            for suite_id in condition.get("suite_ids", [])
            if isinstance(suite_id, str)
        }
    )


def produce(
    *,
    python: Path,
    workspace_root: Path,
    product_relative: str,
    milestone_id: str,
    run_id: str,
    expected_product_digest: str,
    evidence_root: Path,
) -> dict[str, Any]:
    workspace = Path(workspace_root).resolve()
    product_root = (workspace / product_relative).resolve()
    try:
        product_root.relative_to(workspace)
    except ValueError as exc:
        raise VerificationError("product root escapes the workspace") from exc
    before = product_tree_digest(product_root)
    if before != expected_product_digest:
        raise VerificationError("current product digest does not match the requested evaluation")
    milestone = load_json(product_root / "milestones" / milestone_id / "milestone.json")
    catalog = load_json(product_root / "verification/catalog.json")
    suites = {
        item.get("id"): item
        for item in catalog.get("suites", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    root = Path(evidence_root).resolve() / "verification"
    logs = root / "logs"
    structured = root / "structured"
    scratch = root / "scratch"
    for path in (logs, structured, scratch):
        path.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for suite_id in _selected_suite_ids(milestone):
        suite = suites.get(suite_id)
        if not isinstance(suite, dict):
            raise VerificationError(f"milestone references unknown suite {suite_id}")
        result_path = structured / f"{suite_id}.json"
        command = [
            str(Path(python).resolve()),
            str(product_root / "verification/run.py"),
            "suite",
            "--id",
            suite_id,
            "--result",
            str(result_path),
        ]
        started = int(time.time())
        environment = dict(os.environ)
        environment.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "TMPDIR": str(scratch),
            }
        )
        completed = subprocess.run(
            command,
            cwd=product_root,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        captured = int(time.time())
        log_path = logs / f"{suite_id}.log"
        log_path.write_text(completed.stdout, encoding="utf-8")
        if result_path.is_file():
            suite_result = load_json(result_path)
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
            result_path.write_text(json.dumps(suite_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        expected_status = "PASS" if completed.returncode == 0 else "BLOCKED" if completed.returncode == 2 else "FAIL"
        if (
            suite_result.get("schema_version") != "verification-suite-result-v1"
            or suite_result.get("suite_id") != suite_id
            or suite_result.get("status") != expected_status
            or suite_result.get("exit_code") != completed.returncode
            or not isinstance(suite_result.get("skipped"), int)
        ):
            raise VerificationError(f"suite {suite_id} returned an invalid structured result")
        row: dict[str, Any] = {
            "suite_id": suite_id,
            "suite_definition_digest": canonical_digest(suite),
            "status": expected_status,
            "run_id": run_id,
            "product_digest": expected_product_digest,
            "started_at_unix": suite_result["started_at_unix"],
            "captured_at_unix": suite_result["captured_at_unix"],
            "exit_code": completed.returncode,
            "skipped": suite_result["skipped"],
            "log": {
                "path": log_path.relative_to(Path(evidence_root).resolve()).as_posix(),
                "sha256": file_digest(log_path),
            },
            "structured_result": {
                "path": result_path.relative_to(Path(evidence_root).resolve()).as_posix(),
                "sha256": file_digest(result_path),
            },
        }
        row["result_digest"] = canonical_digest(row)
        results.append(row)
    if product_tree_digest(product_root) != before:
        raise VerificationError("verification modified the product")
    bundle: dict[str, Any] = {
        "schema_version": "verification-results-v1",
        "run_id": run_id,
        "product_digest": expected_product_digest,
        "milestone_digest": canonical_digest(milestone),
        "catalog_digest": canonical_digest(catalog),
        "generated_at_unix": int(time.time()),
        "results": results,
    }
    bundle["bundle_digest"] = canonical_digest(bundle)
    (root / "results.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--product-relative", default="product")
    parser.add_argument("--milestone", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--product-digest", required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        bundle = produce(
            python=args.python,
            workspace_root=args.workspace_root,
            product_relative=args.product_relative,
            milestone_id=args.milestone,
            run_id=args.run_id,
            expected_product_digest=args.product_digest,
            evidence_root=args.evidence_root,
        )
        return 0 if all(row["status"] == "PASS" for row in bundle["results"]) else 1
    except (OSError, ValueError, VerificationError) as exc:
        print(f"ERROR: verification: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
