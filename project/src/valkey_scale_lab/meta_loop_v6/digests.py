from __future__ import annotations

import hashlib
from pathlib import Path


IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}


def product_tree_digest(project_root: Path) -> str:
    """Hash product inputs without coupling real evidence to the meta harness."""
    project_root = project_root.resolve()
    digest = hashlib.sha256()
    roots = ("src", "scripts", "schemas", "config", "templates")
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
            if len(relative.parts) >= 3 and relative.parts[:2] == ("src", "valkey_scale_lab") and relative.parts[2].startswith("meta_loop"):
                continue
            if relative.parts[0] == "scripts" and relative.name.startswith("meta_m1_"):
                continue
            digest.update(relative.as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def files_digest(paths: list[Path], *, label_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(path.resolve() for path in paths if path.is_file()):
        try:
            label = path.relative_to(label_root.resolve()).as_posix()
        except ValueError:
            label = path.name
        digest.update(label.encode())
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


def repair_scope_digest(project_root: Path, allowed_paths: list[str]) -> str:
    """Hash the repository surfaces that evaluator repair is not allowed to edit."""
    project_root = project_root.resolve()
    allowed = [(project_root / raw).resolve() for raw in allowed_paths]
    roots = [
        project_root / name
        for name in ("src", "scripts", "tests", "schemas", "config", "templates", "docs", "codex")
    ]
    roots.extend(project_root / name for name in ("AGENTS.md", "META_M1_START.md", "README.md"))
    digest = hashlib.sha256()
    for root in roots:
        candidates = [root] if root.is_file() else sorted(path for path in root.rglob("*") if path.is_file()) if root.exists() else []
        for path in candidates:
            relative = path.relative_to(project_root)
            if any(part in IGNORED_PARTS for part in relative.parts):
                continue
            resolved = path.resolve()
            if any(resolved == item or (item.is_dir() and resolved.is_relative_to(item)) for item in allowed):
                continue
            digest.update(relative.as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()
