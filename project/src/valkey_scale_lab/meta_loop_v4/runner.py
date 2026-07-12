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


class ProgramRunnerError(RuntimeError):
    pass


class ProgramRunner:
    """Runs fixed program checks; agent prose is never accepted as a result."""

    def __init__(self, project_root: Path, workspace_root: Path, logs_root: Path, excerpt_bytes: int):
        self.project_root = project_root.resolve()
        self.workspace_root = workspace_root.resolve()
        self.logs_root = logs_root
        self.excerpt_bytes = excerpt_bytes

    def run(self, check: dict[str, Any], cache: dict[str, Any]) -> dict[str, Any]:
        self._validate_argv(check["command"])
        input_digest = self.check_input_digest(check)
        cache_key = self._cache_key(check, input_digest)
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            result = dict(cached)
            result["cached_from_check_id"] = result.get("check_id")
            result["check_id"] = check["id"]
            result["level"] = check["level"]
            result["cached"] = True
            return result

        started = time.monotonic()
        env = dict(os.environ)
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = f"{self.project_root / 'src'}{os.pathsep}{existing}" if existing else str(self.project_root / "src")
        env.setdefault("PYTHONPYCACHEPREFIX", "/private/tmp/vslab-meta-pyc")
        try:
            process = subprocess.run(
                check["command"],
                cwd=self.project_root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=int(check["timeout_seconds"]),
                check=False,
            )
            returncode = process.returncode
            output = process.stdout or ""
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            returncode = 124
            captured = exc.stdout or ""
            output = captured.decode() if isinstance(captured, bytes) else captured
            output += f"\nTIMEOUT after {check['timeout_seconds']} seconds\n"
            timed_out = True

        self.logs_root.mkdir(parents=True, exist_ok=True)
        log_path = self.logs_root / f"{check['id']}-{uuid.uuid4().hex[:12]}.log"
        log_path.write_text(output, encoding="utf-8")
        input_digest = self.check_input_digest(check)
        cache_key = self._cache_key(check, input_digest)
        result = {
            "check_id": check["id"],
            "level": check["level"],
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
        cache[cache_key] = dict(result)
        return result

    def input_digest(self, input_paths: list[str]) -> str:
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
                candidate for candidate in path.rglob("*")
                if candidate.is_file() and not _ignored(candidate)
            )
            for candidate in files:
                digest.update(str(candidate.relative_to(self.workspace_root)).encode())
                with candidate.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
        return digest.hexdigest()

    def check_input_digest(self, check: dict[str, Any]) -> str:
        digest_mode = check.get("digest_mode")
        if digest_mode != "product_evidence":
            return self.input_digest(check["inputs"])
        digest = hashlib.sha256()
        digest.update(product_tree_digest(self.project_root).encode())
        evidence_inputs = [raw for raw in check["inputs"] if "loop_evidence" in raw]
        digest.update(self.input_digest(evidence_inputs).encode())
        return digest.hexdigest()

    def _validate_argv(self, command: list[str]) -> None:
        if not command or command[0] != "python3":
            raise ProgramRunnerError("program checks must use an explicit python3 argv; shell execution is forbidden")
        if len(command) < 2 or command[1] in {"-c", "-"}:
            raise ProgramRunnerError("inline Python is forbidden in program checks")
        if command[1] == "-m":
            if len(command) < 3 or command[2] not in {"pytest", "compileall"}:
                raise ProgramRunnerError("only pytest and compileall Python modules are allowed in program checks")
            return
        script = (self.project_root / command[1]).resolve()
        if not script.is_relative_to(self.project_root) or script.suffix != ".py":
            raise ProgramRunnerError("program check scripts must be project-local .py files")

    @staticmethod
    def _cache_key(check: dict[str, Any], input_digest: str) -> str:
        payload = {
            "command": check["command"],
            "level": check["level"],
            "timeout_seconds": check["timeout_seconds"],
            "input_digest": input_digest,
            "environment": {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine()},
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _ignored(path: Path) -> bool:
    return any(part in {".git", "__pycache__", ".pytest_cache", ".mypy_cache"} for part in path.parts)
