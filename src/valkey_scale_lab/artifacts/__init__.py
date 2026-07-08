from __future__ import annotations

import hashlib
import json
import platform
import re
import resource
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__

MISSING_STATUSES = {"MISSING", "SKIPPED_WITH_REASON"}


@dataclass(frozen=True)
class RunContext:
    run_id: str
    run_root: Path
    artifact_root: Path
    log_root: Path
    report_root: Path
    state_root: Path
    metadata_path: Path
    manifest_path: Path


def missing(reason: str, *, impact: str | None = None) -> dict[str, str]:
    value = {"status": "MISSING", "reason": reason}
    if impact:
        value["impact"] = impact
    return value


def skipped(reason: str) -> dict[str, str]:
    return {"status": "SKIPPED_WITH_REASON", "reason": reason}


def create_run_context(run_id: str | None = None, runs_root: str | Path = "runs", *, create: bool = True) -> RunContext:
    safe_run_id = _safe_run_id(run_id or _generated_run_id())
    run_root = Path(runs_root) / safe_run_id
    context = RunContext(
        run_id=safe_run_id,
        run_root=run_root,
        artifact_root=run_root / "artifacts",
        log_root=run_root / "logs",
        report_root=run_root / "reports",
        state_root=run_root / "state",
        metadata_path=run_root / "state" / "run_metadata.json",
        manifest_path=run_root / "state" / "run_manifest.json",
    )
    if create:
        for directory in [context.artifact_root, context.log_root, context.report_root, context.state_root]:
            directory.mkdir(parents=True, exist_ok=True)
    return context


def build_run_metadata(
    context: RunContext,
    *,
    config_path: str | Path | None = None,
    inventory: Any | None = None,
    valkey_version: str | dict[str, Any] | None = None,
    runtime_provider: str | None = None,
    runtime_mode: str | None = None,
    port_ranges: Any | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": "run_metadata",
        "run_id": context.run_id,
        "created_at": created_at or _now_iso(),
        "git_sha": _git_sha(),
        "tool_version": __version__,
        "config_sha256": _sha256_path(config_path)
        if config_path
        else skipped("No config path was supplied for this run context."),
        "inventory_sha256": _sha256_jsonable(inventory)
        if inventory is not None
        else skipped("No runtime inventory was supplied for this run context."),
        "valkey_version": valkey_version
        if valkey_version
        else missing("Valkey endpoints were not probed while creating run metadata.", impact="Report cannot prove runtime Valkey version from metadata alone."),
        "host_facts": _host_facts(),
        "os_kernel": platform.release() or missing("platform.release() returned an empty kernel string."),
        "ulimit": _ulimit(),
        "port_ranges": port_ranges if port_ranges is not None else skipped("No port allocator range was supplied for this run context."),
        "runtime_provider": runtime_provider or skipped("Runtime provider is unknown until a concrete runtime path starts."),
        "runtime_mode": runtime_mode or skipped("Runtime mode is unknown until a concrete runtime path starts."),
        "artifact_root": context.artifact_root.as_posix(),
        "log_root": context.log_root.as_posix(),
        "report_root": context.report_root.as_posix(),
        "state_root": context.state_root.as_posix(),
    }


def write_run_metadata(context: RunContext, metadata: dict[str, Any]) -> Path:
    _write_json(context.metadata_path, metadata)
    return context.metadata_path


def write_run_manifest(
    context: RunContext,
    *,
    metadata: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    status: str = "PASS",
) -> dict[str, Any]:
    if metadata is None:
        metadata = load_json(context.metadata_path)
    manifest = {
        "schema_version": "v1",
        "artifact_type": "run_manifest",
        "run_id": context.run_id,
        "created_at": metadata.get("created_at", _now_iso()),
        "status": status,
        "run_root": context.run_root.as_posix(),
        "artifact_root": context.artifact_root.as_posix(),
        "log_root": context.log_root.as_posix(),
        "report_root": context.report_root.as_posix(),
        "state_root": context.state_root.as_posix(),
        "run_metadata_ref": _record(context.metadata_path),
        "artifacts": artifacts or _discover_artifacts(context),
    }
    _write_json(context.manifest_path, manifest)
    return manifest


def load_run_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = _manifest_path(Path(path))
    data = load_json(manifest_path)
    if data.get("artifact_type") != "run_manifest":
        raise ValueError(f"not a run_manifest artifact: {manifest_path}")
    data["_manifest_path"] = manifest_path.as_posix()
    return data


def resolve_artifact_input(path: str | Path) -> tuple[Path, dict[str, Any] | None]:
    source = Path(path)
    if source.is_file() or (source / "state" / "run_manifest.json").exists() or (source / "run_manifest.json").exists():
        manifest = load_run_manifest(source)
        manifest_path = Path(str(manifest["_manifest_path"]))
        artifact_root = _resolve_ref(manifest.get("artifact_root", "artifacts"), manifest_path.parent)
        return artifact_root, manifest
    return source, None


def load_json(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return data


def artifact_record(path: str | Path) -> dict[str, str]:
    return _record(Path(path))


def _manifest_path(path: Path) -> Path:
    if path.is_dir():
        state_manifest = path / "state" / "run_manifest.json"
        if state_manifest.exists():
            return state_manifest
        return path / "run_manifest.json"
    return path


def _resolve_ref(value: str, base: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidate = base / path
    return candidate if candidate.exists() else path


def _discover_artifacts(context: RunContext) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for root in [context.artifact_root, context.log_root, context.report_root, context.state_root]:
        if not root.exists():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            records.append(_record(path))
    return records


def _record(path: Path) -> dict[str, str]:
    return {"path": _rel(path), "sha256": _sha256_file(path)}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _generated_run_id() -> str:
    return "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_run_id(run_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", run_id).strip(".-")
    if not safe:
        raise ValueError("run_id must contain at least one portable path character")
    return safe


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_sha() -> str | dict[str, str]:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], check=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        return missing(f"git rev-parse HEAD failed: {exc}")
    sha = proc.stdout.strip()
    return sha if proc.returncode == 0 and sha else missing("git rev-parse HEAD did not return a commit SHA.")


def _sha256_path(path: str | Path | None) -> str | dict[str, str]:
    if path is None:
        return skipped("No path supplied.")
    file_path = Path(path)
    if not file_path.exists():
        return missing(f"Path does not exist: {file_path}")
    return _sha256_file(file_path)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_jsonable(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _host_facts() -> dict[str, Any]:
    return {
        "system": platform.system() or missing("platform.system() returned empty."),
        "machine": platform.machine() or missing("platform.machine() returned empty."),
        "processor": platform.processor() or skipped("platform.processor() returned empty on this host."),
        "python_version": platform.python_version(),
        "hostname": platform.node() or skipped("platform.node() returned empty on this host."),
    }


def _ulimit() -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name in ["RLIMIT_NOFILE", "RLIMIT_NPROC"]:
        limit = getattr(resource, name, None)
        if limit is None:
            values[name.lower()] = skipped(f"{name} is not available on this platform.")
            continue
        soft, hard = resource.getrlimit(limit)
        values[name.lower()] = {"soft": soft, "hard": hard}
    return values


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
