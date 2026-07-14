from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from .digests import product_tree_digest
from .models import CheckDefinition


class ProgramRunnerError(RuntimeError):
    pass


class ProgramRunner:
    """Execute fixed argv checks and retain bounded context plus full on-disk logs."""

    def __init__(self, project_root: Path, workspace_root: Path, logs_root: Path, excerpt_bytes: int, *, product_roots: tuple[str, ...] = ("src", "scripts", "schemas", "config", "templates"), product_excludes: tuple[str, ...] = ("src/valkey_scale_lab/goal", "src/valkey_scale_lab/meta_loop", "scripts/meta_m1_")):
        self.project_root = project_root.resolve()
        self.workspace_root = workspace_root.resolve()
        self.logs_root = logs_root
        self.excerpt_bytes = excerpt_bytes
        self.product_roots = product_roots
        self.product_excludes = product_excludes

    def run(self, check: CheckDefinition, cache: dict[str, Any]) -> dict[str, Any]:
        self._validate_argv(check.command)
        before_digest = self.check_input_digest(check)
        before_key = self._cache_key(check, before_digest)
        cached = cache.get(before_key)
        if isinstance(cached, dict):
            result = dict(cached)
            result.update({"check_id": check.id, "level": check.level, "cached": True})
            return result

        started = time.monotonic()
        env = dict(os.environ)
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = f"{self.project_root / 'src'}{os.pathsep}{existing}" if existing else str(self.project_root / "src")
        # Never inherit a host cache path: Goal checks own all generated state.
        env["PYTHONPYCACHEPREFIX"] = str((self.logs_root.parent / "pycache").resolve())
        if check.digest_mode == "product_evidence" and check.level in {3, 4}:
            env["VSLAB_META_M1_CONTROLLER_OWNED"] = "1"
            env["VSLAB_META_M1_PRODUCT_DIGEST"] = product_tree_digest(self.project_root, self.product_roots, self.product_excludes)
        try:
            process = subprocess.run(
                list(check.command),
                cwd=self.project_root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=check.timeout_seconds,
                check=False,
            )
            returncode = process.returncode
            output = process.stdout or ""
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            returncode = 124
            captured = exc.stdout or ""
            output = captured.decode() if isinstance(captured, bytes) else captured
            output += f"\nTIMEOUT after {check.timeout_seconds} seconds\n"
            timed_out = True

        self.logs_root.mkdir(parents=True, exist_ok=True)
        log_path = self.logs_root / f"{check.id}-{uuid.uuid4().hex[:12]}.log"
        log_path.write_text(output, encoding="utf-8")
        input_digest = self.check_input_digest(check)
        cache_key = self._cache_key(check, input_digest)
        result = {
            "check_id": check.id,
            "level": check.level,
            "status": "PASS" if returncode == 0 else "FAIL",
            "returncode": returncode,
            "timed_out": timed_out,
            "duration_seconds": round(time.monotonic() - started, 3),
            "input_digest": input_digest,
            "cache_key": cache_key,
            "cached": False,
            "log_path": str(log_path),
            "excerpt": output[-self.excerpt_bytes :],
        }
        if not self._transient_environment_failure(result):
            cache[cache_key] = dict(result)
        return result

    def input_digest(self, input_paths: tuple[str, ...] | list[str]) -> str:
        digest = hashlib.sha256()
        for raw in sorted(input_paths):
            path = (self.project_root / raw).resolve()
            if not path.is_relative_to(self.workspace_root):
                raise ProgramRunnerError(f"input escapes workspace: {raw}")
            digest.update(raw.encode())
            if not path.exists():
                digest.update(b"\0MISSING")
                continue
            files = [path] if path.is_file() else sorted(
                candidate for candidate in path.rglob("*") if candidate.is_file() and not _ignored(candidate)
            )
            for candidate in files:
                digest.update(str(candidate.relative_to(self.workspace_root)).encode())
                digest.update(candidate.read_bytes())
        return digest.hexdigest()

    def check_input_digest(self, check: CheckDefinition) -> str:
        if check.digest_mode != "product_evidence":
            return self.input_digest(check.inputs)
        digest = hashlib.sha256()
        digest.update(product_tree_digest(self.project_root, self.product_roots, self.product_excludes).encode())
        evidence_inputs = tuple(raw for raw in check.inputs if "loop_evidence" in raw)
        digest.update(self.input_digest(evidence_inputs).encode())
        return digest.hexdigest()

    def _validate_argv(self, command: tuple[str, ...]) -> None:
        if not command or command[0] != "python3":
            raise ProgramRunnerError("program checks must use explicit python3 argv")
        if len(command) < 2 or command[1] in {"-c", "-"}:
            raise ProgramRunnerError("inline Python is forbidden")
        if command[1] == "-m":
            if len(command) < 3 or command[2] not in {"pytest", "compileall"}:
                raise ProgramRunnerError("only pytest and compileall modules are allowed")
            return
        script = (self.project_root / command[1]).resolve()
        if not script.is_relative_to(self.project_root) or script.suffix != ".py":
            raise ProgramRunnerError("check scripts must be project-local .py files")

    @staticmethod
    def _cache_key(check: CheckDefinition, input_digest: str) -> str:
        payload = {
            "command": check.command,
            "level": check.level,
            "timeout_seconds": check.timeout_seconds,
            "input_digest": input_digest,
            "environment": {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine()},
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _transient_environment_failure(result: dict[str, Any]) -> bool:
        if result.get("status") != "FAIL":
            return False
        excerpt = str(result.get("excerpt", "")).lower()
        return any(marker in excerpt for marker in (
            "docker daemon: permission denied",
            "permission denied while trying to connect to the docker api",
            "cannot connect to the docker daemon",
            "is the docker daemon running",
        ))


def _ignored(path: Path) -> bool:
    return any(part in {".git", "__pycache__", ".pytest_cache", ".mypy_cache"} for part in path.parts)
