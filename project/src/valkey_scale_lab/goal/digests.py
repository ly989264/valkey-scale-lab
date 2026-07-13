from __future__ import annotations

import hashlib
from pathlib import Path


IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_digest(project_root: Path, relative_paths: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for raw in relative_paths:
        path = (project_root / raw).resolve()
        if not path.is_relative_to(project_root.resolve()) or not path.is_file():
            raise ValueError(f"kernel/evaluator manifest path is missing or escapes project: {raw}")
        digest.update(raw.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def product_tree_digest(
    project_root: Path,
    roots: tuple[str, ...] = ("src", "scripts", "schemas", "config", "templates"),
    excludes: tuple[str, ...] = (
        "src/valkey_scale_lab/goal",
        "src/valkey_scale_lab/meta_loop",
        "scripts/meta_m1_",
    ),
) -> str:
    project_root = project_root.resolve()
    digest = hashlib.sha256()
    for name in roots:
        root = project_root / name
        digest.update(name.encode())
        if not root.exists():
            digest.update(b"\0MISSING")
            continue
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
            relative = path.relative_to(project_root)
            if any(part in IGNORED_PARTS for part in relative.parts):
                continue
            label = relative.as_posix()
            if any(label == prefix or label.startswith(prefix.rstrip("/") + "/") or label.startswith(prefix) for prefix in excludes):
                continue
            digest.update(relative.as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def tree_digest(root: Path) -> str:
    root = root.resolve()
    digest = hashlib.sha256()
    if not root.exists():
        return hashlib.sha256(b"MISSING").hexdigest()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def repair_scope_digest(project_root: Path, allowed_paths: tuple[str, ...]) -> str:
    project_root = project_root.resolve()
    allowed = {(project_root / raw).resolve() for raw in allowed_paths}
    digest = hashlib.sha256()
    for name in ("src", "scripts", "tests", "schemas", "config", "templates", "docs", "codex"):
        root = project_root / name
        if not root.exists():
            continue
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
            if any(part in IGNORED_PARTS for part in path.relative_to(project_root).parts) or path.resolve() in allowed:
                continue
            relative = path.relative_to(project_root).as_posix()
            digest.update(relative.encode())
            digest.update(path.read_bytes())
    for name in ("AGENTS.md", "META_M1_START.md", "META_M1_V7_START.md", "README.md"):
        path = project_root / name
        if path.is_file() and path.resolve() not in allowed:
            digest.update(name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()
