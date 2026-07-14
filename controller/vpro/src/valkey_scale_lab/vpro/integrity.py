from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class FrameworkIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class FrameworkRelease:
    version: str
    digest: str
    root: Path
    manifest_path: Path
    protected_paths: tuple[str, ...]


def verify_framework_release(project_root: Path, manifest_path: Path, anchor_path: Path) -> FrameworkRelease:
    """Verify a release manifest against an operator-supplied external anchor."""

    project_root = project_root.resolve()
    manifest_path = manifest_path.resolve()
    anchor_path = anchor_path.resolve()
    manifest = _object(manifest_path, "framework manifest")
    anchor = _object(anchor_path, "framework anchor")
    _exact_keys(
        manifest,
        {"schema_version", "framework_version", "roots", "files", "protected_paths"},
        "framework manifest",
    )
    _exact_keys(anchor, {"schema_version", "framework_version", "manifest_sha256"}, "framework anchor")
    if manifest.get("schema_version") != "vpro-framework-manifest-v1":
        raise FrameworkIntegrityError("unsupported framework manifest schema")
    if anchor.get("schema_version") != "vpro-framework-anchor-v1":
        raise FrameworkIntegrityError("unsupported framework anchor schema")
    version = manifest.get("framework_version")
    if not isinstance(version, str) or not version or anchor.get("framework_version") != version:
        raise FrameworkIntegrityError("framework version does not match external anchor")
    manifest_digest = _file_digest(manifest_path)
    if anchor.get("manifest_sha256") != manifest_digest:
        raise FrameworkIntegrityError("framework manifest is not authorized by the external anchor")

    roots = manifest.get("roots")
    files = manifest.get("files")
    protected_paths = manifest.get("protected_paths")
    if not isinstance(roots, list) or not roots or not all(isinstance(value, str) and value for value in roots):
        raise FrameworkIntegrityError("framework roots must be a non-empty string list")
    if not isinstance(files, list) or not files:
        raise FrameworkIntegrityError("framework files must be a non-empty list")
    if not isinstance(protected_paths, list) or not all(
        isinstance(value, str) and value for value in protected_paths
    ):
        raise FrameworkIntegrityError("framework protected_paths must be a string list")
    if len(protected_paths) != len(set(protected_paths)):
        raise FrameworkIntegrityError("framework protected_paths must be unique")
    declared: dict[str, str] = {}
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise FrameworkIntegrityError(f"framework files[{index}] must be an object")
        _exact_keys(item, {"path", "sha256"}, f"framework files[{index}]")
        raw = item.get("path")
        claimed = item.get("sha256")
        if not isinstance(raw, str) or not raw or raw in declared:
            raise FrameworkIntegrityError("framework file paths must be non-empty and unique")
        if not isinstance(claimed, str) or len(claimed) != 64:
            raise FrameworkIntegrityError(f"invalid framework file digest: {raw}")
        path = _project_path(project_root, raw)
        if not path.is_file() or path.is_symlink():
            raise FrameworkIntegrityError(f"framework file is missing or is a symlink: {raw}")
        if _file_digest(path) != claimed:
            raise FrameworkIntegrityError(f"framework file drift: {raw}")
        declared[raw] = claimed

    discovered: set[str] = set()
    for raw in roots:
        root = _project_path(project_root, raw)
        if root.is_file():
            discovered.add(raw)
            continue
        if not root.is_dir() or root.is_symlink():
            raise FrameworkIntegrityError(f"framework root is missing or is a symlink: {raw}")
        for candidate in root.rglob("*"):
            if candidate.is_symlink():
                raise FrameworkIntegrityError(f"framework root contains a symlink: {candidate}")
            if candidate.is_file() and "__pycache__" not in candidate.parts:
                discovered.add(candidate.relative_to(project_root).as_posix())
    if discovered != set(declared):
        missing = sorted(discovered - set(declared))
        extra = sorted(set(declared) - discovered)
        raise FrameworkIntegrityError(f"framework manifest closure mismatch; unlisted={missing}, outside_roots={extra}")
    for raw in protected_paths:
        path = _project_path(project_root, raw)
        if not path.exists() or path.is_symlink():
            raise FrameworkIntegrityError(f"protected framework path is missing or is a symlink: {raw}")
    return FrameworkRelease(
        version,
        manifest_digest,
        project_root,
        manifest_path,
        tuple(sorted({*declared, *protected_paths})),
    )


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrameworkIntegrityError(f"cannot load {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise FrameworkIntegrityError(f"{label} must be a JSON object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise FrameworkIntegrityError(f"{label} keys differ: missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}")


def _project_path(project_root: Path, raw: str) -> Path:
    if "\\" in raw or Path(raw).is_absolute() or any(part in {"", ".", ".."} for part in Path(raw).parts):
        raise FrameworkIntegrityError(f"invalid framework path: {raw}")
    path = project_root / raw
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise FrameworkIntegrityError(f"framework path escapes project: {raw}") from exc
    current = project_root
    for part in Path(raw).parts:
        current = current / part
        if current.is_symlink():
            raise FrameworkIntegrityError(f"framework path traverses a symlink: {raw}")
    if not path.is_relative_to(project_root):  # pragma: no cover - lexical validation is primary
        raise FrameworkIntegrityError(f"framework path escapes project: {raw}")
    return path


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
