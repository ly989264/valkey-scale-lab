from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


MANIFEST_SCHEMA = "vpro2-framework-manifest-v1"
RECEIPT_SCHEMA = "vpro2-framework-receipt-v1"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}", re.ASCII)
VERSION_PATTERN = re.compile(
    r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", re.ASCII
)


class FrameworkIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class FrameworkRelease:
    version: str
    manifest_digest: str
    root: Path
    manifest_path: Path
    receipt_path: Path
    roots: tuple[str, ...]
    protected_paths: tuple[str, ...]
    file_digests: tuple[tuple[str, str], ...]

    @property
    def digest(self) -> str:
        return self.manifest_digest


def verify_framework_release(
    framework_root: Path,
    manifest_path: Path,
    receipt_path: Path,
) -> FrameworkRelease:
    """Verify an externally authorized VPRO2 release filesystem closure."""

    raw_root = Path(framework_root).absolute()
    raw_manifest = Path(manifest_path).absolute()
    raw_receipt = Path(receipt_path).absolute()
    _reject_user_symlink_traversal(raw_root, "framework root")
    _reject_user_symlink_traversal(raw_manifest, "framework manifest")
    _reject_user_symlink_traversal(raw_receipt, "external framework receipt")
    root = raw_root.resolve()
    manifest_path = raw_manifest.resolve()
    receipt_path = raw_receipt.resolve()
    if not root.is_dir() or root.is_symlink():
        raise FrameworkIntegrityError("framework root must be a real directory")
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise FrameworkIntegrityError("framework manifest must be a regular file")
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise FrameworkIntegrityError("external framework receipt must be a regular file")
    try:
        manifest_relative = manifest_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise FrameworkIntegrityError("framework manifest must be inside the framework root") from exc
    if _inside(receipt_path, root):
        raise FrameworkIntegrityError("external framework receipt must be outside the framework root")
    receipt_metadata = receipt_path.stat()
    if receipt_metadata.st_nlink != 1:
        raise FrameworkIntegrityError("external framework receipt must not have hard links")
    if receipt_metadata.st_mode & 0o022:
        raise FrameworkIntegrityError(
            "external framework receipt must not be group/world writable"
        )

    manifest = _json_object(manifest_path, "framework manifest")
    receipt = _json_object(receipt_path, "external framework receipt")
    _exact_keys(
        manifest,
        {"schema_version", "framework_version", "roots", "files", "protected_paths"},
        "framework manifest",
    )
    _exact_keys(
        receipt,
        {"schema_version", "framework_version", "manifest_sha256"},
        "external framework receipt",
    )
    if manifest["schema_version"] != MANIFEST_SCHEMA:
        raise FrameworkIntegrityError("unsupported VPRO2 framework manifest schema")
    if receipt["schema_version"] != RECEIPT_SCHEMA:
        raise FrameworkIntegrityError("unsupported VPRO2 framework receipt schema")
    version = manifest["framework_version"]
    if not isinstance(version, str) or VERSION_PATTERN.fullmatch(version) is None:
        raise FrameworkIntegrityError("framework version must be semantic version text")
    if receipt["framework_version"] != version:
        raise FrameworkIntegrityError("framework version does not match external receipt")
    manifest_digest = file_digest(manifest_path)
    if receipt["manifest_sha256"] != manifest_digest:
        raise FrameworkIntegrityError(
            "framework manifest is not authorized by the external receipt"
        )

    roots = _path_list(manifest["roots"], "framework roots", nonempty=True)
    if "src" not in roots:
        raise FrameworkIntegrityError("framework roots must seal the complete src tree")
    protected = _path_list(
        manifest["protected_paths"], "framework protected_paths", nonempty=True
    )
    _reject_overlapping_roots(roots)
    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise FrameworkIntegrityError("framework files must be a nonempty array")
    declared: dict[str, str] = {}
    for index, item in enumerate(files):
        location = f"framework files[{index}]"
        if not isinstance(item, dict):
            raise FrameworkIntegrityError(f"{location} must be an object")
        _exact_keys(item, {"path", "sha256"}, location)
        raw = _safe_relative(item["path"], f"{location}.path")
        claimed = item["sha256"]
        if raw in declared:
            raise FrameworkIntegrityError(f"duplicate framework file path: {raw}")
        if not isinstance(claimed, str) or SHA256_PATTERN.fullmatch(claimed) is None:
            raise FrameworkIntegrityError(f"invalid framework file digest: {raw}")
        path = _member(root, raw)
        if not path.is_file() or path.is_symlink():
            raise FrameworkIntegrityError(f"framework file is missing or unsafe: {raw}")
        if file_digest(path) != claimed:
            raise FrameworkIntegrityError(f"framework file drift: {raw}")
        declared[raw] = claimed

    discovered = _discover_closure(root, roots)
    if discovered != set(declared):
        unlisted = sorted(discovered - set(declared))
        outside_roots = sorted(set(declared) - discovered)
        raise FrameworkIntegrityError(
            "framework manifest closure mismatch; "
            f"unlisted={unlisted}, outside_roots={outside_roots}"
        )
    if manifest_relative not in protected:
        raise FrameworkIntegrityError("framework manifest must be a protected path")
    if "VPRO2_LAUNCH.py" not in protected:
        raise FrameworkIntegrityError("VPRO2_LAUNCH.py must be a protected path")
    for raw in protected:
        path = _member(root, raw)
        if not path.exists() or path.is_symlink():
            raise FrameworkIntegrityError(f"protected framework path is missing or unsafe: {raw}")
        if raw != manifest_relative and raw not in declared:
            raise FrameworkIntegrityError(
                f"protected framework path is outside the hashed file closure: {raw}"
            )

    return FrameworkRelease(
        version=version,
        manifest_digest=manifest_digest,
        root=root,
        manifest_path=manifest_path,
        receipt_path=receipt_path,
        roots=roots,
        protected_paths=protected,
        file_digests=tuple(sorted(declared.items())),
    )


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(path: Path, label: str) -> dict[str, Any]:
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
        raise FrameworkIntegrityError(
            f"{label} fields differ: "
            f"missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}"
        )


def _path_list(value: Any, label: str, *, nonempty: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or (nonempty and not value):
        raise FrameworkIntegrityError(f"{label} must be a nonempty array")
    paths = tuple(_safe_relative(item, f"{label}[{index}]") for index, item in enumerate(value))
    if len(paths) != len(set(paths)):
        raise FrameworkIntegrityError(f"{label} must contain unique paths")
    return paths


def _safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise FrameworkIntegrityError(f"{label} must be a safe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise FrameworkIntegrityError(f"{label} must be a safe relative path")
    return path.as_posix()


def _member(root: Path, raw: str) -> Path:
    safe = _safe_relative(raw, "framework path")
    current = root
    for part in PurePosixPath(safe).parts:
        current = current / part
        if current.is_symlink():
            raise FrameworkIntegrityError(f"framework path traverses a symlink: {raw}")
    try:
        current.relative_to(root)
    except ValueError as exc:  # pragma: no cover - lexical checks are primary
        raise FrameworkIntegrityError(f"framework path escapes release root: {raw}") from exc
    return current


def _discover_closure(root: Path, roots: Iterable[str]) -> set[str]:
    discovered: set[str] = set()
    for raw in roots:
        path = _member(root, raw)
        if path.is_file():
            discovered.add(raw)
            continue
        if not path.is_dir() or path.is_symlink():
            raise FrameworkIntegrityError(f"framework root is missing or unsafe: {raw}")
        for candidate in path.rglob("*"):
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                raise FrameworkIntegrityError(f"framework closure contains a symlink: {relative}")
            if candidate.is_dir():
                continue
            if not candidate.is_file():
                raise FrameworkIntegrityError(
                    f"framework closure contains an unsupported filesystem entry: {relative}"
                )
            if "__pycache__" in candidate.parts or candidate.suffix == ".pyc":
                raise FrameworkIntegrityError(
                    f"framework closure must not contain Python bytecode caches: {relative}"
                )
            discovered.add(relative)
    return discovered


def _reject_overlapping_roots(roots: tuple[str, ...]) -> None:
    for index, left in enumerate(roots):
        for right in roots[index + 1 :]:
            if left.startswith(right + "/") or right.startswith(left + "/"):
                raise FrameworkIntegrityError(
                    f"framework roots must not overlap: {left!r} and {right!r}"
                )


def _reject_user_symlink_traversal(path: Path, label: str) -> None:
    current = path
    while True:
        if current.is_symlink() and current.lstat().st_uid != 0:
            raise FrameworkIntegrityError(f"{label} traverses a user-controlled symlink")
        if current == current.parent:
            return
        current = current.parent


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
