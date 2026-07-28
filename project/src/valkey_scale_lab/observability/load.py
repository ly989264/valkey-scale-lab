from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from valkey_scale_lab.observability.contracts import CollectionError

TARGET_QPS = 10_000
QPS_TOLERANCE = 0.30


def per_connection_rate(primary_count: int) -> int:
    if primary_count <= 0:
        raise ValueError("observed primary count must be positive")
    return max(1, round(TARGET_QPS / primary_count))


@dataclass(frozen=True)
class LoadLanePaths:
    stdout: Path
    stderr: Path
    json: Path
    hdr_prefix: Path


class MemtierProcess:
    def __init__(
        self,
        process: subprocess.Popen[str],
        *,
        stdout_file: Any,
        stderr_file: Any,
        command: Sequence[str],
        paths: LoadLanePaths,
    ) -> None:
        self.process = process
        self._stdout_file = stdout_file
        self._stderr_file = stderr_file
        self.command = list(command)
        self.paths = paths

    def assert_running(self) -> None:
        code = self.process.poll()
        if code is not None:
            self.close_files()
            raise CollectionError(
                f"memtier exited before the requested window completed: {code}"
            )

    def stop(self, *, timeout: float = 15.0) -> int:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=timeout)
        code = int(self.process.returncode or 0)
        self.close_files()
        return code

    def close_files(self) -> None:
        if not self._stdout_file.closed:
            self._stdout_file.close()
        if not self._stderr_file.closed:
            self._stderr_file.close()


class MemtierLoadLane:
    """Fixed V1 Load Lane; no runtime fallback or dynamic concurrency."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        primary_count: int,
        run_scope: str,
        artifacts_dir: Path,
        executable: str = "memtier_benchmark",
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    ) -> None:
        self.host = host
        self.port = port
        self.primary_count = primary_count
        self.run_scope = run_scope
        self.artifacts_dir = artifacts_dir
        self.executable = executable
        self._popen = popen

    def paths(self, label: str) -> LoadLanePaths:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        return LoadLanePaths(
            stdout=self.artifacts_dir / f"memtier_{label}.stdout.log",
            stderr=self.artifacts_dir / f"memtier_{label}.stderr.log",
            json=self.artifacts_dir / f"memtier_{label}.json",
            hdr_prefix=self.artifacts_dir / f"memtier_{label}_latency",
        )

    def command(self, paths: LoadLanePaths, *, duration_seconds: float) -> list[str]:
        return [
            self.executable,
            "--server",
            self.host,
            "--port",
            str(self.port),
            "--cluster-mode",
            "-c",
            "1",
            "-t",
            "1",
            "--pipeline=1",
            "--ratio=1:9",
            "--key-minimum=0",
            "--key-maximum=99999",
            "--data-size=32",
            f"--rate-limiting={per_connection_rate(self.primary_count)}",
            f"--key-prefix=vsl:load:{self.run_scope}:",
            f"--json-out-file={paths.json}",
            f"--hdr-file-prefix={paths.hdr_prefix}",
            f"--test-time={duration_seconds:g}",
        ]

    def _start(self, label: str, *, duration_seconds: float) -> MemtierProcess:
        if shutil.which(self.executable) is None:
            raise CollectionError(f"{self.executable} is not installed")
        paths = self.paths(label)
        stdout_file = paths.stdout.open("w", encoding="utf-8")
        stderr_file = paths.stderr.open("w", encoding="utf-8")
        command = self.command(paths, duration_seconds=duration_seconds)
        try:
            process = self._popen(
                command,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
            )
        except Exception:
            stdout_file.close()
            stderr_file.close()
            raise
        return MemtierProcess(
            process,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
            command=command,
            paths=paths,
        )

    def preflight(self, *, duration_seconds: float = 5.0) -> dict[str, Any]:
        process = self._start("preflight", duration_seconds=duration_seconds)
        try:
            time.sleep(min(max(duration_seconds * 0.1, 0.1), 1.0))
            process.assert_running()
            code = process.process.wait(timeout=duration_seconds + 30.0)
        except subprocess.TimeoutExpired as exc:
            process.stop()
            raise CollectionError("memtier preflight did not finish") from exc
        finally:
            process.close_files()
        if code != 0:
            raise CollectionError(f"memtier preflight exited with code {code}")
        self._validate_outputs(process.paths)
        self._validate_preflight_logs(process.paths)
        return {
            "status": "OK",
            "primary_count": self.primary_count,
            "target_qps": TARGET_QPS,
            "per_connection_rate": per_connection_rate(self.primary_count),
            "preflight_checks": {
                "cluster_connection": True,
                "process_stayed_running": True,
                "json_output": True,
                "hdr_output": True,
                "fd_or_connection_init_errors": False,
            },
            "command": process.command,
            "outputs": {
                "stdout": process.paths.stdout.as_posix(),
                "stderr": process.paths.stderr.as_posix(),
                "json": process.paths.json.as_posix(),
                "hdr_prefix": process.paths.hdr_prefix.as_posix(),
            },
        }

    def start(self, *, duration_seconds: float) -> MemtierProcess:
        process = self._start("formal", duration_seconds=duration_seconds)
        time.sleep(0.1)
        process.assert_running()
        return process

    def finish(
        self, process: MemtierProcess, *, planned_stop: bool = False
    ) -> dict[str, Any]:
        code = process.process.poll()
        if code is None:
            if planned_stop:
                code = process.stop()
            else:
                try:
                    code = process.process.wait(timeout=15.0)
                    process.close_files()
                except subprocess.TimeoutExpired:
                    code = process.stop()
        else:
            process.close_files()
        if code != 0 and not (planned_stop and code == -15):
            raise CollectionError(f"memtier formal window exited with code {code}")
        self._validate_outputs(process.paths)
        observed_qps = _read_qps(process.paths.json)
        warnings: list[str] = []
        if observed_qps is not None:
            lower = TARGET_QPS * (1.0 - QPS_TOLERANCE)
            upper = TARGET_QPS * (1.0 + QPS_TOLERANCE)
            if observed_qps < lower or observed_qps > upper:
                warnings.append(
                    f"observed QPS {observed_qps:.3f} is outside the "
                    f"reference range {lower:.0f}..{upper:.0f}"
                )
        else:
            warnings.append("memtier JSON did not expose an aggregate QPS")
        return {
            "status": "OK",
            "returncode": code,
            "target_qps": TARGET_QPS,
            "observed_qps": observed_qps,
            "qps_is_verdict_input": False,
            "warnings": warnings,
            "command": process.command,
        }

    @staticmethod
    def _validate_outputs(paths: LoadLanePaths) -> None:
        if not paths.json.is_file() or paths.json.stat().st_size == 0:
            raise CollectionError("memtier did not write a complete JSON result")
        try:
            json.loads(paths.json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CollectionError("memtier JSON result is invalid") from exc
        hdr_files = list(paths.hdr_prefix.parent.glob(f"{paths.hdr_prefix.name}*"))
        if not any(path.is_file() and path.stat().st_size > 0 for path in hdr_files):
            raise CollectionError("memtier did not write HDR latency output")

    @staticmethod
    def _validate_preflight_logs(paths: LoadLanePaths) -> None:
        text = ""
        for path in (paths.stdout, paths.stderr):
            try:
                text += "\n" + path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        lowered = text.lower()
        patterns = (
            "too many open files",
            "file descriptor",
            "fd limit",
            "connection refused",
            "connection timed out",
            "failed to connect",
            "error connecting",
            "connection initialization",
            "connect failed",
        )
        for pattern in patterns:
            if pattern in lowered:
                raise CollectionError(
                    "memtier preflight reported FD or connection initialization errors"
                )


def _read_qps(path: Path) -> float | None:
    document = json.loads(path.read_text(encoding="utf-8"))
    candidates: list[float] = []

    def visit(value: Any, path_parts: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = str(key).lower().replace("_", "").replace("/", "")
                if normalized in {"opssec", "opspersec", "qps"} and isinstance(
                    item, (int, float)
                ):
                    weight = 2 if any(
                        part.lower() in {"totals", "total", "all"}
                        for part in path_parts
                    ) else 1
                    candidates.extend([float(item)] * weight)
                visit(item, (*path_parts, str(key)))
        elif isinstance(value, list):
            for item in value:
                visit(item, path_parts)

    visit(document)
    return candidates[-1] if candidates else None
