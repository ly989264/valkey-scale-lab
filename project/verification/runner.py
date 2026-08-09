from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verification.planning import PlannedTest


@dataclass(frozen=True)
class TestResult:
    test_id: str
    description: str
    status: str
    duration_seconds: float
    detail: str
    exit_code: int | None
    counts: dict[str, int]
    artifacts_dir: Path
    excerpt: str


def _tail(path: Path, limit: int) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-limit:]


def _failure_excerpt(stdout_path: Path, stderr_path: Path) -> str:
    stdout_lines = _tail(stdout_path, 20)
    stderr_lines = _tail(stderr_path, 20)
    sections: list[str] = []
    if stdout_lines:
        sections.append("stdout (tail):\n" + "\n".join(stdout_lines))
    if stderr_lines:
        sections.append("stderr (tail):\n" + "\n".join(stderr_lines))
    return "\n".join(sections)


def _junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    keys = ("tests", "failures", "errors", "skipped")
    if all(key in root.attrib for key in keys):
        return {key: int(root.attrib.get(key, "0")) for key in keys}
    suites = [
        element
        for element in root.iter("testsuite")
        if not any(child.tag == "testsuite" for child in element)
    ]
    return {
        key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
        for key in keys
    }


def _read_json_result(path: Path) -> tuple[str, str]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON result: {exc}") from exc
    if not isinstance(value, dict) or set(value) - {"status", "summary"}:
        raise ValueError("JSON result must contain only status and optional summary")
    # ERROR is a verdict a check can report about itself: the tool could not
    # complete the observation. It is the same status this runner already emits
    # when the harness cannot run a test, because it means the same thing.
    if value.get("status") not in {"PASS", "FAIL", "BLOCKED", "ERROR"}:
        raise ValueError("JSON result status must be PASS, FAIL, BLOCKED, or ERROR")
    summary = value.get("summary", "")
    if not isinstance(summary, str):
        raise ValueError("JSON result summary must be text")
    return value["status"], summary


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        process.wait()
        return
    process.wait()


def execute_test(planned: PlannedTest) -> TestResult:
    planned.artifacts_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = planned.artifacts_dir / "stdout.log"
    stderr_path = planned.artifacts_dir / "stderr.log"
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if planned.test.runner.type == "pytest":
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    started = time.monotonic()
    exit_code: int | None = None
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    status = "ERROR"
    detail = "runner did not start"
    try:
        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            process = subprocess.Popen(
                planned.argv,
                cwd=planned.cwd,
                env=environment,
                stdout=stdout_handle,
                stderr=stderr_handle,
                start_new_session=True,
            )
            try:
                exit_code = process.wait(timeout=planned.test.runner.timeout_seconds)
            except subprocess.TimeoutExpired:
                _terminate_process_group(process)
                status = "TIMEOUT"
                detail = f"exceeded {planned.test.runner.timeout_seconds}s timeout"
            except KeyboardInterrupt:
                _terminate_process_group(process)
                raise
            else:
                if planned.test.runner.result == "exit_code":
                    status = "PASS" if exit_code == 0 else "FAIL"
                    detail = f"exit code {exit_code}"
                elif planned.test.runner.result == "json":
                    if exit_code != 0:
                        status = "FAIL"
                        detail = f"exit code {exit_code}"
                    else:
                        try:
                            status, summary = _read_json_result(planned.result_path)
                            detail = summary or "JSON result"
                        except ValueError as exc:
                            status = "ERROR"
                            detail = str(exc)
                else:
                    try:
                        counts = _junit_counts(planned.result_path)
                    except (OSError, ValueError, ET.ParseError) as exc:
                        status = "ERROR"
                        detail = f"cannot read JUnit result: {exc}"
                    else:
                        status = (
                            "PASS"
                            if exit_code == 0
                            and counts["failures"] == 0
                            and counts["errors"] == 0
                            and counts["skipped"] == 0
                            else "FAIL"
                        )
                        detail = (
                            f"{counts['tests']} tests, {counts['failures']} failed, "
                            f"{counts['errors']} errors, {counts['skipped']} skipped"
                        )
    except (OSError, subprocess.SubprocessError) as exc:
        status = "ERROR"
        detail = f"cannot execute process: {exc}"
    duration = time.monotonic() - started
    excerpt = "" if status == "PASS" else _failure_excerpt(stdout_path, stderr_path)
    return TestResult(
        planned.test.test_id,
        planned.test.description,
        status,
        duration,
        detail,
        exit_code,
        counts,
        planned.artifacts_dir,
        excerpt,
    )
