from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import struct
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from .models import CheckDefinition


class ProgramRunnerError(RuntimeError):
    pass


_SHELLS = {"bash", "csh", "dash", "fish", "ksh", "sh", "tcsh", "zsh"}
_INLINE_FLAGS = {
    "node": {"-e", "--eval"},
    "perl": {"-e"},
    "python": {"-c", "-"},
    "python3": {"-c", "-"},
    "ruby": {"-e"},
}
_SAFE_ENV = {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "SYSTEMROOT", "TMPDIR", "TZ"}


class ProgramRunner:
    """Run a sealed argv definition without a shell and retain auditable results."""

    def __init__(
        self,
        *,
        project_root: Path,
        workspace_root: Path,
        state_root: Path,
        logs_root: Path,
        excerpt_bytes: int,
        allowed_tools: Iterable[str],
        tool_seals: dict[str, dict[str, str]] | None,
        sandbox_seal: dict[str, str] | None,
        run_context: dict[str, str],
        evidence_roots: Iterable[str] = (),
        secret_paths: Iterable[Path] = (),
    ):
        self.project_root = project_root.resolve()
        self.workspace_root = workspace_root.resolve()
        self.state_root = state_root.resolve()
        self.logs_root = logs_root.resolve()
        self.excerpt_bytes = excerpt_bytes
        self.allowed_tools = frozenset(allowed_tools)
        self.tool_seals = dict(tool_seals or {})
        self.sandbox_seal = dict(sandbox_seal or {})
        self.run_context = dict(run_context)
        self.evidence_roots = tuple(evidence_roots)
        self.secret_paths = tuple(Path(path).resolve() for path in secret_paths)
        self._sandbox_pass_fds: tuple[int, ...] = ()

    def run(
        self,
        check: CheckDefinition,
        cache: dict[str, Any],
        *,
        cache_allowed: bool = True,
    ) -> dict[str, Any]:
        self._validate_argv(check.argv)
        definition_digest = self.definition_digest(check)
        before_digest = self.input_digest(check.inputs)
        cache_key = self._cache_key(check, definition_digest, before_digest)
        if cache_allowed and check.cache == "by_input_digest":
            cached = self.cached_result(check, cache)
            if cached is not None:
                result = dict(cached)
                result.update({"check_id": check.id, "cached": True})
                return result

        started = time.monotonic()
        env = {key: value for key, value in os.environ.items() if key in _SAFE_ENV}
        context = dict(self.run_context)
        if check.mode == "standard":
            context.pop("ownership_token", None)
            if not any(
                _path_covered(path, root)
                for path in check.inputs
                for root in self.evidence_roots
            ):
                context.pop("evidence_root", None)
        env.update({f"VPRO_{key.upper()}": value for key, value in context.items()})
        env["VPRO_SEALED_TOOLS_JSON"] = json.dumps(
            {tool: seal["path"] for tool, seal in self.tool_seals.items()},
            separators=(",", ":"),
            sort_keys=True,
        )
        env["PYTHONPYCACHEPREFIX"] = str(self.state_root / "pycache")
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        try:
            cwd = (self.project_root / check.cwd).resolve()
            if not cwd.is_relative_to(self.project_root) or not cwd.is_dir():
                raise ProgramRunnerError(f"check cwd is missing or escapes project: {check.cwd}")
            executable = self._sealed_executable(check.argv[0])
            env["PATH"] = os.pathsep.join(
                dict.fromkeys(str(Path(seal["path"]).parent) for seal in self.tool_seals.values())
            )
            command = [executable, *check.argv[1:]]
            if _is_python_tool(check.argv[0]):
                command = [executable, "-I", "-S", "-B", *check.argv[1:]]
            scratch = self.state_root / "scratch" / uuid.uuid4().hex
            scratch.mkdir(parents=True)
            output_parents = sorted({self._resolve_path(raw).parent for raw in check.outputs})
            for parent in output_parents:
                parent.mkdir(parents=True, exist_ok=True)
            env["HOME"] = str(scratch)
            env["TMPDIR"] = str(scratch)
            command = self._sandboxed_command(
                command,
                cwd=cwd,
                writable_paths=(scratch, *output_parents),
                readonly_paths=tuple(
                    path
                    for raw in check.inputs
                    if (path := self._resolve_path(raw)).exists()
                ),
                allow_external_services=bool(check.capabilities),
            )
            try:
                process = subprocess.run(
                    command,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=check.timeout_seconds,
                    check=False,
                    shell=False,
                    close_fds=True,
                    pass_fds=self._sandbox_pass_fds,
                )
            finally:
                self._close_sandbox_fds()
            returncode = process.returncode
            output = process.stdout or ""
            timed_out = False
        except (OSError, subprocess.TimeoutExpired) as exc:
            if isinstance(exc, subprocess.TimeoutExpired):
                captured = exc.stdout or ""
                output = captured.decode() if isinstance(captured, bytes) else captured
                output += f"\nTIMEOUT after {check.timeout_seconds} seconds\n"
                returncode = 124
                timed_out = True
            else:
                output = f"EXECUTION ERROR: {exc}\n"
                returncode = 126
                timed_out = False

        try:
            after_digest = self.input_digest(check.inputs)
            input_changed = before_digest != after_digest
        except (ProgramRunnerError, OSError) as exc:
            after_digest = "UNREADABLE"
            input_changed = True
            output += f"\nVPRO CONTROLLER VIOLATION: declared inputs became invalid: {exc}\n"
            returncode = 125
        if input_changed and after_digest != "UNREADABLE":
            output += "\nVPRO CONTROLLER VIOLATION: check changed its declared inputs\n"
            returncode = 125
        output_digest = None
        if check.outputs and returncode == 0:
            try:
                if not all(self._valid_output(self._resolve_path(raw)) for raw in check.outputs):
                    output += "\nVPRO CONTROLLER VIOLATION: check did not create every declared output\n"
                    returncode = 125
                else:
                    output_digest = self.input_digest(check.outputs)
            except (ProgramRunnerError, OSError) as exc:
                output += f"\nVPRO CONTROLLER VIOLATION: declared outputs are invalid: {exc}\n"
                returncode = 125
        self.logs_root.mkdir(parents=True, exist_ok=True)
        log_path = self.logs_root / f"{check.id}-{uuid.uuid4().hex[:12]}.log"
        log_path.write_text(output, encoding="utf-8")
        log_digest = _file_digest(log_path)
        result = {
            "check_id": check.id,
            "definition_digest": definition_digest,
            "tier": check.tier,
            "status": "PASS" if returncode == 0 else "FAIL",
            "returncode": returncode,
            "timed_out": timed_out,
            "input_changed": input_changed,
            "duration_seconds": round(time.monotonic() - started, 3),
            "input_digest": after_digest,
            "output_digest": output_digest,
            "cache_key": cache_key,
            "cached": False,
            "log_path": str(log_path),
            "log_digest": log_digest,
            "excerpt": output[-self.excerpt_bytes :],
        }
        if cache_allowed and check.cache == "by_input_digest" and result["status"] == "PASS":
            cache[cache_key] = dict(result)
        return result

    def input_digest(self, paths: Iterable[str]) -> str:
        digest = hashlib.sha256()
        for raw in sorted(paths):
            path, authority_root, authority = self._path_context(raw)
            digest.update(raw.encode())
            digest.update(f"\0{authority}\0".encode())
            if path.is_symlink():
                raise ProgramRunnerError(f"digest input is a symlink: {raw}")
            if not path.exists():
                digest.update(b"\0MISSING")
                continue
            self._update_input_digest(digest, path, authority_root, raw)
        return digest.hexdigest()

    def cached_result(self, check: CheckDefinition, cache: dict[str, Any]) -> dict[str, Any] | None:
        definition_digest = self.definition_digest(check)
        input_digest = self.input_digest(check.inputs)
        key = self._cache_key(check, definition_digest, input_digest)
        cached = cache.get(key)
        if not isinstance(cached, dict):
            return None
        log_path = Path(str(cached.get("log_path", "")))
        if not log_path.is_file() or cached.get("log_digest") != _file_digest(log_path):
            cache.pop(key, None)
            return None
        try:
            expected_output = self.input_digest(check.outputs) if check.outputs else None
        except (ProgramRunnerError, OSError):
            cache.pop(key, None)
            return None
        if cached.get("output_digest") != expected_output:
            cache.pop(key, None)
            return None
        if check.outputs and not all(
            self._valid_output(self._resolve_path(raw)) for raw in check.outputs
        ):
            cache.pop(key, None)
            return None
        return cached

    @staticmethod
    def _valid_output(path: Path) -> bool:
        return not path.is_symlink() and (path.is_file() or path.is_dir())

    def _resolve_path(self, raw: str) -> Path:
        path, _, _ = self._path_context(raw)
        return path

    def _path_context(self, raw: str) -> tuple[Path, Path, str]:
        base = self.state_root if any(_path_covered(raw, root) for root in self.evidence_roots) else self.project_root
        authority = "state" if base == self.state_root else "project"
        path = base / raw
        try:
            path.relative_to(base)
        except ValueError as exc:
            raise ProgramRunnerError(f"path escapes {authority} root: {raw}") from exc
        current = base
        for part in Path(raw).parts:
            if part in {"", ".", ".."}:
                raise ProgramRunnerError(f"path escapes {authority} root: {raw}")
            current = current / part
            if current.is_symlink():
                raise ProgramRunnerError(f"path traverses symlink: {raw}")
        return path, base, authority

    def _update_input_digest(self, digest: Any, path: Path, base: Path, raw: str) -> None:
        if path.is_file():
            self._update_file_digest(digest, path, base, raw)
            return
        if not path.is_dir():
            raise ProgramRunnerError(f"digest input is not a regular file or directory: {raw}")
        root_relative = path.relative_to(base).as_posix()
        root_mode = stat.S_IMODE(path.lstat().st_mode)
        digest.update(f"DIR\0{root_relative}\0MODE\0{root_mode:04o}\0".encode())
        for current, directories, files in os.walk(path, topdown=True, followlinks=False):
            current_path = Path(current)
            directories[:] = sorted(directories)
            files = sorted(files)
            for name in tuple(directories):
                candidate = current_path / name
                if candidate.is_symlink():
                    raise ProgramRunnerError(f"digest input contains a symlink: {candidate}")
                mode = stat.S_IMODE(candidate.lstat().st_mode)
                digest.update(
                    f"DIR\0{candidate.relative_to(base).as_posix()}\0MODE\0{mode:04o}\0".encode()
                )
            for name in files:
                candidate = current_path / name
                if candidate.is_symlink():
                    raise ProgramRunnerError(f"digest input contains a symlink: {candidate}")
                if not candidate.is_file():
                    raise ProgramRunnerError(f"digest input contains a special file: {candidate}")
                self._update_file_digest(digest, candidate, base, raw)

    @staticmethod
    def _update_file_digest(digest: Any, path: Path, base: Path, raw: str) -> None:
        try:
            relative = path.relative_to(base).as_posix()
        except ValueError as exc:  # pragma: no cover - guarded by _path_context
            raise ProgramRunnerError(f"digest input escapes its authority root: {raw}") from exc
        content_digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                content_digest.update(chunk)
        mode = stat.S_IMODE(path.lstat().st_mode)
        digest.update(f"FILE\0{relative}\0MODE\0{mode:04o}\0".encode())
        digest.update(content_digest.digest())

    @staticmethod
    def definition_digest(check: CheckDefinition) -> str:
        payload = check.as_dict()
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _validate_argv(self, argv: tuple[str, ...]) -> None:
        if not argv or any(not value or "\0" in value or "\n" in value for value in argv):
            raise ProgramRunnerError("check argv contains an invalid argument")
        tool = Path(argv[0]).name
        if argv[0] != tool or tool not in self.allowed_tools:
            raise ProgramRunnerError(f"check tool is not allowed: {argv[0]}")
        if tool in _SHELLS:
            raise ProgramRunnerError("shell executors are forbidden")
        if len(argv) > 1 and argv[1] in _INLINE_FLAGS.get(tool, set()):
            raise ProgramRunnerError("inline code execution is forbidden")
        self._sealed_executable(tool)

    def _sealed_executable(self, tool: str) -> str:
        seal = self.tool_seals.get(tool)
        if not isinstance(seal, dict) or set(seal) != {"entrypoint", "path", "sha256"}:
            raise ProgramRunnerError(f"check tool has no sealed identity: {tool}")
        path = Path(seal["path"])
        entrypoint = Path(seal["entrypoint"])
        try:
            resolved = path.resolve(strict=True)
            current_entrypoint = entrypoint.resolve(strict=True)
        except OSError as exc:
            raise ProgramRunnerError(f"sealed check tool is unavailable: {tool}: {exc}") from exc
        if resolved != path or current_entrypoint != path or not path.is_file() or not os.access(path, os.X_OK):
            raise ProgramRunnerError(f"sealed check tool path changed: {tool}")
        self._validate_tool_entrypoint(entrypoint, tool)
        self._validate_tool_path_security(path, tool)
        if _file_digest(path) != seal["sha256"]:
            raise ProgramRunnerError(f"sealed check tool content changed: {tool}")
        return str(path)

    @staticmethod
    def seal_tools(
        allowed_tools: Iterable[str],
        *,
        workspace_root: Path,
        state_root: Path,
    ) -> dict[str, dict[str, str]]:
        workspace = workspace_root.resolve()
        state = state_root.resolve()
        seals: dict[str, dict[str, str]] = {}
        for tool in sorted(set(allowed_tools)):
            located = shutil.which(tool)
            if located is None:
                raise ProgramRunnerError(f"allowed check tool is unavailable: {tool}")
            entrypoint = Path(located).absolute()
            try:
                path = entrypoint.resolve(strict=True)
            except OSError as exc:
                raise ProgramRunnerError(f"cannot resolve allowed check tool {tool}: {exc}") from exc
            if not path.is_file() or not os.access(path, os.X_OK):
                raise ProgramRunnerError(f"allowed check tool is not executable: {tool}")
            ProgramRunner._validate_external_entrypoint(entrypoint, tool, workspace, state)
            ProgramRunner._validate_external_tool(path, tool, workspace, state)
            seals[tool] = {"entrypoint": str(entrypoint), "path": str(path), "sha256": _file_digest(path)}
        return seals

    @staticmethod
    def seal_sandbox(*, workspace_root: Path, state_root: Path) -> dict[str, str]:
        system = platform.system()
        if system == "Darwin":
            backend, tool = "sandbox-exec", "sandbox-exec"
        elif system == "Linux":
            backend, tool = "bubblewrap", "bwrap"
            ProgramRunner._linux_seccomp_policy()
        else:
            raise ProgramRunnerError(f"VPRO has no filesystem sandbox backend for {system}")
        located = shutil.which(tool)
        if located is None:
            raise ProgramRunnerError(f"required VPRO filesystem sandbox is unavailable: {tool}")
        entrypoint = Path(located).absolute()
        try:
            path = entrypoint.resolve(strict=True)
        except OSError as exc:
            raise ProgramRunnerError(f"cannot resolve filesystem sandbox {tool}: {exc}") from exc
        ProgramRunner._validate_external_entrypoint(
            entrypoint,
            tool,
            workspace_root.resolve(),
            state_root.resolve(),
        )
        ProgramRunner._validate_external_tool(
            path,
            tool,
            workspace_root.resolve(),
            state_root.resolve(),
        )
        return {
            "backend": backend,
            "entrypoint": str(entrypoint),
            "path": str(path),
            "sha256": _file_digest(path),
        }

    @staticmethod
    def verify_tool_seals(
        seals: Any,
        allowed_tools: Iterable[str],
        *,
        workspace_root: Path,
        state_root: Path,
    ) -> None:
        if not isinstance(seals, dict) or set(seals) != set(allowed_tools):
            raise ProgramRunnerError("sealed tool set differs from the bound allowed tools")
        runner = ProgramRunner(
            project_root=workspace_root,
            workspace_root=workspace_root,
            state_root=state_root,
            logs_root=state_root,
            excerpt_bytes=1,
            allowed_tools=allowed_tools,
            tool_seals=seals,
            sandbox_seal=None,
            run_context={},
        )
        for tool in seals:
            runner._sealed_executable(tool)

    @staticmethod
    def verify_sandbox_seal(
        seal: Any,
        *,
        workspace_root: Path,
        state_root: Path,
    ) -> None:
        if not isinstance(seal, dict) or set(seal) != {"backend", "entrypoint", "path", "sha256"}:
            raise ProgramRunnerError("filesystem sandbox has no sealed identity")
        expected_backend = "sandbox-exec" if platform.system() == "Darwin" else "bubblewrap" if platform.system() == "Linux" else None
        if seal.get("backend") != expected_backend:
            raise ProgramRunnerError("filesystem sandbox backend changed")
        runner = ProgramRunner(
            project_root=workspace_root,
            workspace_root=workspace_root,
            state_root=state_root,
            logs_root=state_root,
            excerpt_bytes=1,
            allowed_tools=(),
            tool_seals=None,
            sandbox_seal=seal,
            run_context={},
        )
        runner._sealed_sandbox_executable()

    def _validate_tool_path_security(self, path: Path, tool: str) -> None:
        self._validate_external_tool(path, tool, self.workspace_root, self.state_root)

    def _validate_tool_entrypoint(self, path: Path, tool: str) -> None:
        self._validate_external_entrypoint(path, tool, self.workspace_root, self.state_root)

    def _sealed_sandbox_executable(self) -> str:
        seal = self.sandbox_seal
        if set(seal) != {"backend", "entrypoint", "path", "sha256"}:
            raise ProgramRunnerError("filesystem sandbox has no sealed identity")
        path = Path(seal["path"])
        entrypoint = Path(seal["entrypoint"])
        try:
            resolved = path.resolve(strict=True)
            current_entrypoint = entrypoint.resolve(strict=True)
        except OSError as exc:
            raise ProgramRunnerError(f"sealed filesystem sandbox is unavailable: {exc}") from exc
        if resolved != path or current_entrypoint != path or not path.is_file() or not os.access(path, os.X_OK):
            raise ProgramRunnerError("sealed filesystem sandbox path changed")
        self._validate_external_entrypoint(entrypoint, path.name, self.workspace_root, self.state_root)
        self._validate_external_tool(path, path.name, self.workspace_root, self.state_root)
        if _file_digest(path) != seal["sha256"]:
            raise ProgramRunnerError("sealed filesystem sandbox content changed")
        return str(path)

    def _sandboxed_command(
        self,
        command: list[str],
        *,
        cwd: Path,
        writable_paths: Iterable[Path],
        readonly_paths: Iterable[Path] = (),
        allow_external_services: bool = False,
    ) -> list[str]:
        self._close_sandbox_fds()
        executable = self._sealed_sandbox_executable()
        writable = tuple(dict.fromkeys(path.resolve() for path in writable_paths))
        readonly = tuple(dict.fromkeys(path.resolve() for path in readonly_paths))
        if any(not path.is_relative_to(self.state_root) for path in writable):
            raise ProgramRunnerError("check sandbox write path escapes controller state root")
        backend = self.sandbox_seal["backend"]
        if backend == "sandbox-exec":
            filters = " ".join(f"(subpath {json.dumps(str(path))})" for path in writable)
            secret_filters = " ".join(
                f"(literal {json.dumps(str(path))})" for path in self.secret_paths
            )
            readonly_filters = " ".join(
                f"(subpath {json.dumps(str(path))})" if path.is_dir()
                else f"(literal {json.dumps(str(path))})"
                for path in readonly
            )
            secret_rule = f"(deny file-read* {secret_filters})" if secret_filters else ""
            readonly_rule = f"(deny file-write* {readonly_filters})" if readonly_filters else ""
            network_rule = "" if allow_external_services else "(deny network*)"
            profile = (
                f"(version 1)(allow default)(deny file-write*){secret_rule}{network_rule}"
                f"(allow file-write* {filters}){readonly_rule}"
            )
            return [executable, "-p", profile, *command]
        if backend == "bubblewrap":
            sandbox = [
                executable,
                "--die-with-parent",
                "--new-session",
                "--unshare-pid",
                "--ro-bind",
                "/",
                "/",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
            ]
            if not allow_external_services:
                sandbox.extend(("--unshare-net", "--unshare-ipc", "--tmpfs", "/run"))
                seccomp_fd = self._no_external_services_seccomp_fd()
                self._sandbox_pass_fds = (seccomp_fd,)
                sandbox.extend(("--seccomp", str(seccomp_fd)))
            for path in self.secret_paths:
                sandbox.extend(("--ro-bind", "/dev/null", str(path)))
            for path in writable:
                sandbox.extend(("--bind", str(path), str(path)))
            for path in readonly:
                sandbox.extend(("--ro-bind", str(path), str(path)))
            return [*sandbox, "--chdir", str(cwd), "--", *command]
        raise ProgramRunnerError(f"unsupported filesystem sandbox backend: {backend}")

    def _close_sandbox_fds(self) -> None:
        for fd in self._sandbox_pass_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._sandbox_pass_fds = ()

    @staticmethod
    def _no_external_services_seccomp_fd() -> int:
        expected_arch, forbidden_syscalls, reject_x32 = ProgramRunner._linux_seccomp_policy()
        instructions = [
            (0x20, 0, 0, 4),
            (0x15, 1, 0, expected_arch),
            (0x06, 0, 0, 0x80000000),
            (0x20, 0, 0, 0),
        ]
        if reject_x32:
            instructions.extend(
                (
                    (0x45, 0, 1, 0x40000000),
                    (0x06, 0, 0, 0x00050000 | 1),
                )
            )
        for syscall_number in forbidden_syscalls:
            instructions.extend(
                (
                    (0x15, 0, 1, syscall_number),
                    (0x06, 0, 0, 0x00050000 | 1),
                )
            )
        instructions.append((0x06, 0, 0, 0x7FFF0000))
        read_fd, write_fd = os.pipe()
        try:
            payload = b"".join(struct.pack("HBBI", *instruction) for instruction in instructions)
            os.write(write_fd, payload)
        finally:
            os.close(write_fd)
        return read_fd

    @staticmethod
    def _linux_seccomp_policy() -> tuple[int, tuple[int, ...], bool]:
        machine = platform.machine().lower()
        if machine in {"x86_64", "amd64"}:
            return (
                0xC000003E,
                (
                    41,
                    42,
                    43,
                    49,
                    50,
                    248,
                    249,
                    250,
                    288,
                    425,
                    426,
                    427,
                    438,
                ),
                True,
            )
        if machine in {"aarch64", "arm64"}:
            return (
                0xC00000B7,
                (
                    198,
                    200,
                    201,
                    202,
                    203,
                    217,
                    218,
                    219,
                    242,
                    425,
                    426,
                    427,
                    438,
                ),
                False,
            )
        raise ProgramRunnerError(
            f"VPRO has no fail-closed Linux seccomp policy for architecture {machine}"
        )

    @staticmethod
    def _validate_external_entrypoint(path: Path, tool: str, workspace: Path, state: Path) -> None:
        if not path.is_absolute() or not path.exists():
            raise ProgramRunnerError(f"allowed check tool entrypoint is unavailable: {tool}")
        if path.is_relative_to(workspace) or path.is_relative_to(state):
            raise ProgramRunnerError(f"allowed check tool entrypoint is inside a writable root: {tool}")
        if path.lstat().st_uid == os.geteuid() or os.access(path, os.W_OK):
            raise ProgramRunnerError(f"allowed check tool entrypoint must be operator read-only: {tool}")
        ProgramRunner._validate_external_parents(path.parent, tool)

    @staticmethod
    def _validate_external_tool(path: Path, tool: str, workspace: Path, state: Path) -> None:
        if path.is_relative_to(workspace) or path.is_relative_to(state):
            raise ProgramRunnerError(f"allowed check tool is inside a worker/controller writable root: {tool}")
        if path.stat().st_uid == os.geteuid() or os.access(path, os.W_OK):
            raise ProgramRunnerError(f"allowed check tool must be operator read-only: {tool}")
        ProgramRunner._validate_external_parents(path.parent, tool)

    @staticmethod
    def _validate_external_parents(parent: Path, tool: str) -> None:
        while True:
            if parent.stat().st_uid == os.geteuid() or os.access(parent, os.W_OK):
                raise ProgramRunnerError(f"allowed check tool parent must be operator read-only: {tool}")
            if parent == parent.parent:
                break
            parent = parent.parent

    def _cache_key(self, check: CheckDefinition, definition_digest: str, input_digest: str) -> str:
        payload = {
            "definition_digest": definition_digest,
            "input_digest": input_digest,
            "tool_seal": self.tool_seals.get(check.argv[0]),
            "environment": {
                "machine": platform.machine(),
                "python": platform.python_version(),
                "system": platform.system(),
            },
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_covered(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _is_python_tool(tool: str) -> bool:
    return re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", tool.lower()) is not None
