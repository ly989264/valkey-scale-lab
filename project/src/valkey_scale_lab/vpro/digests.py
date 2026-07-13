from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import asdict, is_dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


DEFAULT_IGNORED_PARTS: frozenset[str] = frozenset()


def canonical_json_digest(value: Any) -> str:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def file_digest(path: Path) -> str:
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"digest input must not be a symlink: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(
    root: Path,
    *,
    ignored_parts: Iterable[str] = DEFAULT_IGNORED_PARTS,
) -> str:
    root = Path(root)
    if root.is_symlink():
        raise ValueError(f"digest root must not be a symlink: {root}")
    digest = hashlib.sha256()
    if not root.exists():
        digest.update(b"MISSING")
        return digest.hexdigest()
    _update_path_digest(digest, ".", root)
    if root.is_file():
        return digest.hexdigest()
    ignored = frozenset(ignored_parts)
    for relative, path in _walk(root, ignored):
        _update_path_digest(digest, relative, path)
    return digest.hexdigest()


def workspace_minus_allowed_digest(
    workspace_root: Path,
    allowed_paths: Iterable[str | Path],
    *,
    ignored_parts: Iterable[str] = DEFAULT_IGNORED_PARTS,
) -> str:
    root = Path(workspace_root).resolve()
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"workspace root must be a real directory: {workspace_root}")
    allowed = tuple(_relative_parts(value) for value in allowed_paths)
    ignored = frozenset(ignored_parts)
    digest = hashlib.sha256()
    _update_path_digest(digest, ".", root)
    for relative, path in _walk(root, ignored):
        parts = PurePosixPath(relative).parts
        if any(_contains(parent, parts) for parent in allowed):
            continue
        _update_path_digest(digest, relative, path)
    return digest.hexdigest()


def _walk(root: Path, ignored: frozenset[str]) -> Iterable[tuple[str, Path]]:
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_current = current_path.relative_to(root)
        directories[:] = sorted(name for name in directories if name not in ignored)
        files = sorted(name for name in files if name not in ignored)
        for name in tuple(directories):
            path = current_path / name
            if path.is_symlink():
                directories.remove(name)
                relative = (relative_current / name).as_posix()
                yield relative, path
            else:
                relative = (relative_current / name).as_posix()
                yield relative, path
        for name in files:
            path = current_path / name
            relative = (relative_current / name).as_posix()
            yield relative, path


def _update_path_digest(digest: Any, relative: str, path: Path) -> None:
    digest.update(b"PATH\0")
    digest.update(relative.encode("utf-8"))
    digest.update(b"\0")
    mode = path.lstat().st_mode
    digest.update(f"MODE\0{stat.S_IMODE(mode):04o}\0".encode("ascii"))
    if stat.S_ISLNK(mode):
        digest.update(b"SYMLINK\0")
        digest.update(hashlib.sha256(os.readlink(path).encode("utf-8")).digest())
    elif stat.S_ISDIR(mode):
        digest.update(b"DIRECTORY\0")
    elif stat.S_ISREG(mode):
        digest.update(b"FILE\0")
        content_digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                content_digest.update(chunk)
        digest.update(content_digest.digest())
    else:
        digest.update(f"SPECIAL\0{stat.S_IFMT(mode)}\0".encode("ascii"))


def _relative_parts(value: str | Path) -> tuple[str, ...]:
    raw = Path(value).as_posix()
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"allowed path must be a contained relative path: {value}")
    return path.parts


def _contains(parent: tuple[str, ...], child: tuple[str, ...]) -> bool:
    return len(parent) <= len(child) and child[: len(parent)] == parent
