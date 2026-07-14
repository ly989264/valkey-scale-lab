#!/usr/bin/env python3
"""Capture and verify the byte-preserving two-directory repository layout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

PHASE = "P46_REPOSITORY_LAYOUT_MIGRATION"
ROOTS = ("artifacts", "audit", "runs")
EXCLUDED_PREFIXES = (
    f"artifacts/phases/{PHASE}/",
    f"artifacts/gates/{PHASE}/",
    f"artifacts/goal_loop/{PHASE}/",
    f"artifacts/harness_exception/{PHASE}",
    f"audit/{PHASE}/",
)
ROOT_ALLOWLIST = (".git", ".github", ".gitignore", "AGENTS.md", "README.md", "loop_evidence", "project")
LINKS = {
    "artifacts": "../loop_evidence/artifacts",
    "audit": "../loop_evidence/audit",
    "runs": "../loop_evidence/runs",
    ".github": "../.github",
}
ACTIVE_DIRS = ("codex", "config", "docs", "schemas", "scripts", "src", "templates", "tests", "tools")
RETIRED = (
    "codex_goal_loop_m1",
    "codex_goal_loop_m1_hardening_v2",
    "GOAL_LOOP_PACKAGE_README.md",
    "MILESTONE1_GOAL_LOOP_PACKAGE_README.md",
    "MILESTONE1_HARDENING_V2_README.md",
    "PACKAGE_FILE_MANIFEST.md",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def excluded(logical_path: str) -> bool:
    return any(logical_path == p.rstrip("/") or logical_path.startswith(p) for p in EXCLUDED_PREFIXES)


def record_digest(rows: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(f"{row['logical_path']}\0{row['byte_count']}\0{row['sha256']}\n".encode("utf-8"))
    return digest.hexdigest()


def counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"file_count": len(rows), "byte_count": sum(r["byte_count"] for r in rows), "tree_sha256": record_digest(rows)}


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def tracked_paths(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z", "--", *ROOTS],
        check=True, capture_output=True,
    )
    paths = [p.decode("utf-8") for p in result.stdout.split(b"\0") if p]
    return sorted((p for p in paths if not excluded(p)), key=lambda p: p.encode("utf-8"))


def inventory(repo_root: Path, logical_paths: list[str], physical_prefix: Path | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for logical in logical_paths:
        posix = PurePosixPath(logical)
        if logical in seen or posix.is_absolute() or ".." in posix.parts or posix.parts[0] not in ROOTS:
            raise ValueError(f"invalid or duplicate logical path: {logical}")
        seen.add(logical)
        path = (physical_prefix / logical) if physical_prefix else (repo_root / logical)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"evidence is not a regular file: {logical}")
        rows.append({"logical_path": logical, "type": "regular", "byte_count": path.stat().st_size, "sha256": sha256_file(path)})
    return rows


def capture(repo_root: Path, baseline: Path) -> int:
    paths = tracked_paths(repo_root)
    rows = inventory(repo_root, paths)
    by_root = {root: counts([r for r in rows if r["logical_path"].split("/", 1)[0] == root]) for root in ROOTS}
    payload = {
        "schema_version": "v1", "artifact_type": "evidence_integrity", "hash_algorithm": "sha256",
        "record_format": "logical_path\\0byte_count\\0sha256\\n",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_logical_roots": list(ROOTS), "excluded_prefixes": list(EXCLUDED_PREFIXES),
        "roots": by_root, "aggregate": counts(rows), "files": rows,
    }
    atomic_json(baseline, payload)
    print(f"captured {payload['aggregate']['file_count']} files / {payload['aggregate']['byte_count']} bytes")
    return 0


def load_baseline(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("artifact_type") != "evidence_integrity" or data.get("hash_algorithm") != "sha256":
        raise ValueError("malformed evidence baseline header")
    files = data.get("files")
    if not isinstance(files, list):
        raise ValueError("malformed evidence baseline files")
    logical = [row.get("logical_path") for row in files if isinstance(row, dict)]
    if len(logical) != len(files) or not all(isinstance(item, str) for item in logical) or len(set(logical)) != len(logical):
        raise ValueError("baseline has malformed or duplicate logical paths")
    if logical != sorted(logical, key=lambda p: p.encode("utf-8")):
        raise ValueError("baseline files are not bytewise sorted")
    for row in files:
        if set(row) != {"logical_path", "type", "byte_count", "sha256"}:
            raise ValueError("baseline file record has invalid fields")
        logical_path = row["logical_path"]
        posix = PurePosixPath(logical_path)
        if (
            not isinstance(logical_path, str)
            or posix.is_absolute()
            or ".." in posix.parts
            or not posix.parts
            or posix.parts[0] not in ROOTS
            or excluded(logical_path)
            or row["type"] != "regular"
            or not isinstance(row["byte_count"], int)
            or isinstance(row["byte_count"], bool)
            or row["byte_count"] < 0
            or not isinstance(row["sha256"], str)
            or len(row["sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in row["sha256"])
        ):
            raise ValueError(f"baseline file record invalid: {logical_path!r}")
    if data.get("excluded_prefixes") != list(EXCLUDED_PREFIXES) or data.get("source_logical_roots") != list(ROOTS):
        raise ValueError("baseline roots or exclusions do not match the P46 contract")
    computed = counts(files)
    if computed != data.get("aggregate"):
        raise ValueError("baseline aggregate does not match file records")
    declared_roots = data.get("roots")
    if not isinstance(declared_roots, dict) or set(declared_roots) != set(ROOTS):
        raise ValueError("baseline roots declaration is malformed")
    for root in ROOTS:
        root_rows = [row for row in files if row["logical_path"].split("/", 1)[0] == root]
        if declared_roots[root] != counts(root_rows):
            raise ValueError(f"baseline root {root} does not match file records")
    return data


def validate_report_semantics(report: dict[str, Any]) -> list[str]:
    """Validate cross-field PASS invariants not expressible by the local schema subset."""
    if report.get("status") != "PASS":
        return []
    errors: list[str] = []
    for field in ("errors", "unexpected_root_entries"):
        if report.get(field) != []:
            errors.append(f"PASS requires empty {field}")
    integrity = report.get("integrity", {})
    for field in ("missing", "changed", "unexpected"):
        if integrity.get(field) != []:
            errors.append(f"PASS requires empty integrity.{field}")
    if integrity.get("baseline") != integrity.get("observed"):
        errors.append("PASS requires identical baseline and observed integrity counts")
    if report.get("expected_root_entries") != report.get("observed_root_entries"):
        errors.append("PASS requires expected and observed root entries to match exactly")
    classifications = report.get("classifications")
    if not isinstance(classifications, dict) or not classifications or not all(value is True for value in classifications.values()):
        errors.append("PASS requires every classification to be true")
    links = report.get("links")
    if not isinstance(links, list) or len(links) != len(LINKS) or not all(link.get("valid") is True for link in links if isinstance(link, dict)):
        errors.append("PASS requires exactly four valid links")
    observed_targets = {
        Path(link.get("path", "")).name: link.get("expected_target")
        for link in links or [] if isinstance(link, dict)
    }
    if observed_targets != LINKS:
        errors.append("PASS link names and expected targets do not match the layout contract")
    return errors


def verify(args: argparse.Namespace) -> int:
    repo, project, evidence = (Path(x).resolve() for x in (args.repo_root, args.project_root, args.evidence_root))
    errors: list[str] = []
    try:
        baseline = load_baseline(Path(args.baseline))
    except Exception as exc:
        baseline = {"files": [], "aggregate": counts([])}
        errors.append(f"baseline invalid: {exc}")
    expected_entries = list(ROOT_ALLOWLIST)
    observed_entries = sorted(p.name for p in repo.iterdir())
    unexpected = sorted(set(observed_entries) - set(expected_entries))
    missing_root = sorted(set(expected_entries) - set(observed_entries))
    if unexpected: errors.append(f"unexpected repository root entries: {unexpected}")
    if missing_root: errors.append(f"missing repository root entries: {missing_root}")

    link_rows = []
    for name, target in LINKS.items():
        path = project / name
        observed = os.readlink(path) if path.is_symlink() else None
        resolved = str(path.resolve()) if path.exists() else None
        expected_resolved = str((path.parent / target).resolve())
        valid = observed == target and not os.path.isabs(target) and resolved == expected_resolved and path.exists()
        if not valid: errors.append(f"invalid compatibility link: {path} -> {observed!r}")
        link_rows.append({"path": str(path), "expected_target": target, "observed_target": observed, "resolved_target": resolved, "valid": valid})

    classifications: dict[str, bool] = {}
    for name in ACTIVE_DIRS:
        classifications[f"project/{name}"] = (project / name).is_dir() and not (evidence / name).exists()
    retired_root = evidence / "retired_loop_packages"
    for name in RETIRED:
        classifications[f"retired/{name}"] = (retired_root / name).exists() and not (project / name).exists()
    classifications["evidence/artifacts"] = (evidence / "artifacts").is_dir()
    classifications["evidence/audit"] = (evidence / "audit").is_dir()
    classifications["evidence/runs"] = (evidence / "runs").is_dir()
    bad_classifications = sorted(k for k, value in classifications.items() if not value)
    if bad_classifications: errors.append(f"classification failures: {bad_classifications}")

    baseline_rows = baseline["files"]
    missing: list[str] = []
    changed: list[str] = []
    observed_rows: list[dict[str, Any]] = []
    for expected in baseline_rows:
        logical = expected["logical_path"]
        path = evidence / logical
        if path.is_symlink() or not path.is_file():
            missing.append(logical)
            continue
        actual = {"logical_path": logical, "type": "regular", "byte_count": path.stat().st_size, "sha256": sha256_file(path)}
        observed_rows.append(actual)
        if actual != expected: changed.append(logical)
    baseline_set = {row["logical_path"] for row in baseline_rows}
    extra: list[str] = []
    for root in ROOTS:
        for path in (evidence / root).rglob("*"):
            if path.is_file() and not path.is_symlink():
                logical = path.relative_to(evidence).as_posix()
                if logical not in baseline_set and not excluded(logical): extra.append(logical)
    if missing: errors.append(f"missing historical evidence: {len(missing)}")
    if changed: errors.append(f"changed historical evidence: {len(changed)}")
    if extra: errors.append(f"unexpected historical evidence: {len(extra)}")
    observed_counts = counts(observed_rows)
    if observed_counts != baseline.get("aggregate"): errors.append("evidence aggregate mismatch")

    report = {
        "schema_version": "v1", "artifact_type": "repository_layout_report", "phase_id": PHASE,
        "status": "PASS" if not errors else "FAIL", "repo_root": str(repo), "project_root": str(project), "evidence_root": str(evidence),
        "expected_root_entries": expected_entries, "observed_root_entries": observed_entries,
        "unexpected_root_entries": unexpected, "classifications": classifications, "links": link_rows,
        "integrity": {"baseline": baseline.get("aggregate", counts([])), "observed": observed_counts, "missing": missing, "changed": changed, "unexpected": sorted(extra)},
        "errors": errors,
    }
    atomic_json(Path(args.out), report)
    summary = {
        "schema_version": "v1", "artifact_type": "phase_summary", "phase_id": PHASE,
        "run_id": "p46-repository-layout", "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": {"name": "validate_repository_layout.py", "version": "v1"},
        "status": report["status"], "summary": "Repository layout and historical evidence integrity verified." if not errors else "; ".join(errors),
        "required_artifacts": [f"artifacts/phases/{PHASE}/phase_summary.json", f"artifacts/phases/{PHASE}/evidence_integrity.json", f"artifacts/phases/{PHASE}/repository_layout_report.json"],
        "missing_metrics": [], "risks": [],
    }
    atomic_json(Path(args.phase_summary), summary)
    for error in errors: print(error, file=sys.stderr)
    return 0 if not errors else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--capture", action="store_true")
    result.add_argument("--repo-root", required=True)
    result.add_argument("--project-root")
    result.add_argument("--evidence-root")
    result.add_argument("--baseline", required=True)
    result.add_argument("--out")
    result.add_argument("--phase-summary")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.capture:
        return capture(Path(args.repo_root).resolve(), Path(args.baseline))
    if not all((args.project_root, args.evidence_root, args.out, args.phase_summary)):
        parser().error("verification requires --project-root, --evidence-root, --out, and --phase-summary")
    return verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
