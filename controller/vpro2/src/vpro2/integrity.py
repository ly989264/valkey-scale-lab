from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


class IntegrityError(RuntimeError):
    pass


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise IntegrityError("path must be non-empty text")
    path = PurePosixPath(value)
    if path.is_absolute() or path == PurePosixPath(".") or ".." in path.parts:
        raise IntegrityError(f"unsafe relative path {value!r}")
    if any(part in {"", "."} for part in path.parts):
        raise IntegrityError(f"unsafe relative path {value!r}")
    return path


def resolve_inside(root: Path, relative: str) -> Path:
    root = Path(root).resolve()
    path = root.joinpath(*safe_relative_path(relative).parts)
    current = root
    for part in safe_relative_path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise IntegrityError(f"path traverses symlink: {relative}")
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise IntegrityError(f"path escapes root: {relative}")
    return resolved


def paths_overlap(left: str, right: str) -> bool:
    lhs = PurePosixPath(left).parts
    rhs = PurePosixPath(right).parts
    limit = min(len(lhs), len(rhs))
    return lhs[:limit] == rhs[:limit]


def covered(path: str, roots: Iterable[str]) -> bool:
    return any(paths_overlap(path, root) and len(PurePosixPath(path).parts) >= len(PurePosixPath(root).parts) for root in roots)


def tree_manifest(root: Path) -> dict[str, dict[str, Any]]:
    """Return a fail-closed manifest of every file and directory under root."""

    root = Path(root).resolve()
    if not root.is_dir() or root.is_symlink():
        raise IntegrityError(f"manifest root must be a real directory: {root}")
    manifest: dict[str, dict[str, Any]] = {}
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in sorted((*directories, *files)):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise IntegrityError(f"symlinks are not permitted in controlled trees: {relative}")
            mode = stat.S_IMODE(info.st_mode)
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
                raise IntegrityError(f"special files are not permitted in controlled trees: {relative}")
    return dict(sorted(manifest.items()))


def manifest_diff(
    before: Mapping[str, Mapping[str, Any]],
    after: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[str]]:
    before_paths = set(before)
    after_paths = set(after)
    return {
        "added": sorted(after_paths - before_paths),
        "removed": sorted(before_paths - after_paths),
        "changed": sorted(path for path in before_paths & after_paths if before[path] != after[path]),
    }


def changed_paths(diff: Mapping[str, Iterable[str]]) -> tuple[str, ...]:
    return tuple(sorted({path for values in diff.values() for path in values}))


def unauthorized_changes(diff: Mapping[str, Iterable[str]], allowed_paths: Iterable[str]) -> tuple[str, ...]:
    allowed = tuple(allowed_paths)
    return tuple(path for path in changed_paths(diff) if not covered(path, allowed))


def prepare_write_parents(workspace_root: Path, paths: Iterable[str]) -> None:
    workspace_root = Path(workspace_root).resolve()
    for relative in paths:
        target = resolve_inside(workspace_root, relative)
        parent = target if target.exists() and target.is_dir() else target.parent
        parent.mkdir(parents=True, exist_ok=True)


def snapshot_paths(workspace_root: Path, relative_paths: Iterable[str], snapshot_root: Path) -> dict[str, bool]:
    workspace_root = Path(workspace_root).resolve()
    snapshot_root = Path(snapshot_root).resolve()
    if snapshot_root.is_relative_to(workspace_root):
        raise IntegrityError("snapshot root must be outside the worker workspace")
    snapshot_root.mkdir(parents=True, exist_ok=False)
    presence: dict[str, bool] = {}
    for relative in sorted(set(relative_paths)):
        source = resolve_inside(workspace_root, relative)
        destination = snapshot_root.joinpath(*safe_relative_path(relative).parts)
        present = source.exists()
        presence[relative] = present
        if not present:
            continue
        if source.is_symlink():
            raise IntegrityError(f"cannot snapshot symlink {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, symlinks=False)
        elif source.is_file():
            shutil.copy2(source, destination)
        else:
            raise IntegrityError(f"cannot snapshot special file {relative}")
    (snapshot_root / ".presence.json").write_text(
        json.dumps(presence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return presence


def restore_snapshot(workspace_root: Path, snapshot_root: Path) -> None:
    workspace_root = Path(workspace_root).resolve()
    snapshot_root = Path(snapshot_root).resolve()
    try:
        presence = json.loads((snapshot_root / ".presence.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"cannot load rollback snapshot: {exc}") from exc
    if not isinstance(presence, dict) or not all(isinstance(key, str) and isinstance(value, bool) for key, value in presence.items()):
        raise IntegrityError("rollback snapshot presence map is invalid")
    for relative, was_present in sorted(presence.items(), key=lambda item: len(PurePosixPath(item[0]).parts), reverse=True):
        target = resolve_inside(workspace_root, relative)
        if target.exists():
            if target.is_symlink():
                raise IntegrityError(f"refusing to replace symlink during rollback: {relative}")
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        if not was_present:
            continue
        source = snapshot_root.joinpath(*safe_relative_path(relative).parts)
        if not source.exists() or source.is_symlink():
            raise IntegrityError(f"rollback content missing for {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, symlinks=False)
        else:
            shutil.copy2(source, target)


def snapshot_workspace(workspace_root: Path, snapshot_root: Path) -> None:
    """Capture a complete isolated Worker workspace for integrity rollback."""

    workspace_root = Path(workspace_root).resolve()
    snapshot_root = Path(snapshot_root).resolve()
    if snapshot_root.is_relative_to(workspace_root):
        raise IntegrityError("workspace snapshot must be outside the worker workspace")
    if snapshot_root.exists():
        raise IntegrityError("workspace snapshot destination already exists")
    # tree_manifest rejects symlinks and special files before copytree follows anything.
    tree_manifest(workspace_root)
    shutil.copytree(workspace_root, snapshot_root, symlinks=False)


def restore_workspace(workspace_root: Path, snapshot_root: Path) -> None:
    """Restore the complete isolated Worker workspace, including unauthorized paths."""

    workspace_root = Path(workspace_root).resolve()
    snapshot_root = Path(snapshot_root).resolve()
    if not snapshot_root.is_dir() or snapshot_root.is_symlink():
        raise IntegrityError("complete workspace snapshot is missing or unsafe")
    tree_manifest(snapshot_root)
    for child in workspace_root.iterdir():
        if child.is_symlink():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for source in snapshot_root.iterdir():
        target = workspace_root / source.name
        if source.is_dir():
            shutil.copytree(source, target, symlinks=False)
        else:
            shutil.copy2(source, target)
