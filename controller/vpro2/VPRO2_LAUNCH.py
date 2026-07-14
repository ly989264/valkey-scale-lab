"""Isolated, verify-before-import bootstrap for the fixed VPRO2 release."""

from __future__ import annotations

import hashlib
import json
import os
import re
import runpy
import sys
from pathlib import Path, PurePosixPath


_MANIFEST_SCHEMA = "vpro2-framework-manifest-v1"
_RECEIPT_SCHEMA = "vpro2-framework-receipt-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_VERSION = re.compile(
    r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", re.ASCII
)


class _BootstrapError(RuntimeError):
    pass


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _json_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _BootstrapError(f"cannot load {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise _BootstrapError(f"{label} must be a JSON object")
    return value


def _exact_keys(value: dict, expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise _BootstrapError(
            f"{label} fields differ: "
            f"missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}"
        )


def _safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise _BootstrapError(f"{label} must be a safe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise _BootstrapError(f"{label} must be a safe relative path")
    return path.as_posix()


def _path_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise _BootstrapError(f"{label} must be a nonempty array")
    paths = tuple(_safe_relative(item, f"{label}[{index}]") for index, item in enumerate(value))
    if len(paths) != len(set(paths)):
        raise _BootstrapError(f"{label} must contain unique paths")
    return paths


def _member(root: Path, raw: str) -> Path:
    current = root
    for part in PurePosixPath(_safe_relative(raw, "framework path")).parts:
        current = current / part
        if current.is_symlink():
            raise _BootstrapError(f"framework path traverses a symlink: {raw}")
    try:
        current.relative_to(root)
    except ValueError as exc:  # pragma: no cover - lexical validation is primary
        raise _BootstrapError(f"framework path escapes release root: {raw}") from exc
    return current


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _reject_user_symlink_traversal(path: Path, label: str) -> None:
    current = path
    while True:
        if current.is_symlink() and current.lstat().st_uid != 0:
            raise _BootstrapError(f"{label} traverses a user-controlled symlink")
        if current == current.parent:
            return
        current = current.parent


def _verify_release(framework_root: Path, manifest_path: Path, receipt_path: Path) -> tuple[str, str]:
    raw_root = framework_root.absolute()
    raw_manifest = manifest_path.absolute()
    raw_receipt = receipt_path.absolute()
    _reject_user_symlink_traversal(raw_root, "framework root")
    _reject_user_symlink_traversal(raw_manifest, "framework manifest")
    _reject_user_symlink_traversal(raw_receipt, "external framework receipt")
    root = raw_root.resolve()
    manifest_path = raw_manifest.resolve()
    receipt_path = raw_receipt.resolve()
    if not root.is_dir() or root.is_symlink():
        raise _BootstrapError("framework root must be a real directory")
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise _BootstrapError("framework manifest must be a regular file")
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise _BootstrapError("external framework receipt must be a regular file")
    try:
        manifest_relative = manifest_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise _BootstrapError("framework manifest must be inside the framework root") from exc
    if _inside(receipt_path, root):
        raise _BootstrapError("external framework receipt must be outside the framework root")
    metadata = receipt_path.stat()
    if metadata.st_nlink != 1:
        raise _BootstrapError("external framework receipt must not have hard links")
    if metadata.st_mode & 0o022:
        raise _BootstrapError("external framework receipt must not be group/world writable")

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
    if manifest["schema_version"] != _MANIFEST_SCHEMA:
        raise _BootstrapError("unsupported VPRO2 framework manifest schema")
    if receipt["schema_version"] != _RECEIPT_SCHEMA:
        raise _BootstrapError("unsupported VPRO2 framework receipt schema")
    version = manifest["framework_version"]
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        raise _BootstrapError("framework version must be semantic version text")
    if receipt["framework_version"] != version:
        raise _BootstrapError("framework version does not match external receipt")
    manifest_digest = _digest(manifest_path)
    if receipt["manifest_sha256"] != manifest_digest:
        raise _BootstrapError("framework manifest is not authorized by the external receipt")

    roots = _path_list(manifest["roots"], "framework roots")
    if "src" not in roots:
        raise _BootstrapError("framework roots must seal the complete src tree")
    protected = _path_list(manifest["protected_paths"], "framework protected_paths")
    for index, left in enumerate(roots):
        for right in roots[index + 1 :]:
            if left.startswith(right + "/") or right.startswith(left + "/"):
                raise _BootstrapError(f"framework roots overlap: {left!r} and {right!r}")
    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise _BootstrapError("framework files must be a nonempty array")
    declared: dict[str, str] = {}
    for index, item in enumerate(files):
        location = f"framework files[{index}]"
        if not isinstance(item, dict):
            raise _BootstrapError(f"{location} must be an object")
        _exact_keys(item, {"path", "sha256"}, location)
        raw = _safe_relative(item["path"], f"{location}.path")
        claimed = item["sha256"]
        if raw in declared:
            raise _BootstrapError(f"duplicate framework file path: {raw}")
        if not isinstance(claimed, str) or _SHA256.fullmatch(claimed) is None:
            raise _BootstrapError(f"invalid framework file digest: {raw}")
        path = _member(root, raw)
        if not path.is_file() or path.is_symlink():
            raise _BootstrapError(f"framework file is missing or unsafe: {raw}")
        if _digest(path) != claimed:
            raise _BootstrapError(f"framework file drift: {raw}")
        declared[raw] = claimed

    discovered: set[str] = set()
    for raw in roots:
        path = _member(root, raw)
        if path.is_file():
            discovered.add(raw)
            continue
        if not path.is_dir() or path.is_symlink():
            raise _BootstrapError(f"framework root is missing or unsafe: {raw}")
        for candidate in path.rglob("*"):
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                raise _BootstrapError(f"framework closure contains a symlink: {relative}")
            if candidate.is_dir():
                continue
            if not candidate.is_file():
                raise _BootstrapError(
                    f"framework closure contains an unsupported entry: {relative}"
                )
            if "__pycache__" in candidate.parts or candidate.suffix == ".pyc":
                raise _BootstrapError(
                    f"framework closure contains a Python bytecode cache: {relative}"
                )
            discovered.add(relative)
    if discovered != set(declared):
        raise _BootstrapError(
            "framework manifest closure mismatch; "
            f"unlisted={sorted(discovered - set(declared))}, "
            f"outside_roots={sorted(set(declared) - discovered)}"
        )
    if manifest_relative not in protected or "VPRO2_LAUNCH.py" not in protected:
        raise _BootstrapError("manifest and launcher must both be protected paths")
    for raw in protected:
        path = _member(root, raw)
        if not path.exists() or path.is_symlink():
            raise _BootstrapError(f"protected framework path is missing or unsafe: {raw}")
        if raw != manifest_relative and raw not in declared:
            raise _BootstrapError(
                f"protected framework path is outside the hashed closure: {raw}"
            )
    return version, manifest_digest


def _main() -> None:
    if not sys.flags.isolated or not sys.flags.no_site or not sys.flags.dont_write_bytecode:
        raise _BootstrapError("VPRO2_LAUNCH requires Python flags -I -S -B")
    framework_root = Path(__file__).resolve().parent
    receipt_raw = os.environ.get("VPRO2_FRAMEWORK_RECEIPT")
    if not receipt_raw:
        raise _BootstrapError(
            "the protected operator launcher must set VPRO2_FRAMEWORK_RECEIPT"
        )
    receipt_path = Path(receipt_raw)
    if not receipt_path.is_absolute():
        raise _BootstrapError("VPRO2_FRAMEWORK_RECEIPT must be an absolute path")
    version, digest = _verify_release(
        framework_root,
        framework_root / "codex/vpro2/framework_manifest.json",
        receipt_path,
    )
    os.environ["VPRO2_VERIFIED_FRAMEWORK_VERSION"] = version
    os.environ["VPRO2_VERIFIED_FRAMEWORK_DIGEST"] = digest
    sys.path.insert(0, str(framework_root / "src"))
    runpy.run_module("vpro2", run_name="__main__", alter_sys=True)


try:
    _main()
except _BootstrapError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(1)
