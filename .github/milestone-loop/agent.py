from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

from contracts import ContractError


T = TypeVar("T")
CONTROL_ROOT = Path(__file__).resolve().parent
MAX_AGENT_OUTPUT_BYTES = 32_768


class AgentError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentResult:
    raw: str
    diagnostics: tuple[str, ...]


def _agent_environment() -> dict[str, str]:
    blocked_prefixes = (
        "GH_",
        "GITHUB_",
        "AWS_",
        "AZURE_",
        "GOOGLE_",
        "VALKEY_REAL_",
        "MILESTONE_LEASE_",
        "ACTIONS_ID_TOKEN_",
        "VSLAB_M2_",
    )
    allowed = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(blocked_prefixes) and key not in {"SSH_AUTH_SOCK"}
    }
    allowed["NO_COLOR"] = "1"
    allowed["PYTHONDONTWRITEBYTECODE"] = "1"
    allowed["GIT_CONFIG_COUNT"] = "2"
    allowed["GIT_CONFIG_GLOBAL"] = "/dev/null"
    allowed["GIT_CONFIG_NOSYSTEM"] = "1"
    allowed["GIT_CONFIG_KEY_0"] = "credential.helper"
    allowed["GIT_CONFIG_VALUE_0"] = ""
    allowed["GIT_CONFIG_KEY_1"] = "credential.interactive"
    allowed["GIT_CONFIG_VALUE_1"] = "false"
    allowed["GIT_TERMINAL_PROMPT"] = "0"
    allowed["GIT_ASKPASS"] = "/usr/bin/false"
    return allowed


def _terminate(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def invoke(
    *,
    role: str,
    cwd: Path,
    context_path: Path,
    output_path: Path,
    wall_timeout: int,
    silence_timeout: int,
    extra_instruction: str = "",
) -> AgentResult:
    if role not in {"planner", "worker"}:
        raise AgentError("agent role must be planner or worker")
    prompt_path = CONTROL_ROOT / "prompts" / f"{role}.md"
    schema_path = CONTROL_ROOT / "schemas" / f"{role}-output.schema.json"
    prompt = prompt_path.read_text(encoding="utf-8")
    prompt += f"\n\nBounded context file: {context_path}\n"
    if extra_instruction:
        prompt += f"\nDeterministic repair instruction:\n{extra_instruction}\n"
    sandbox = "read-only" if role == "planner" else "workspace-write"
    argv = [
        "codex",
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--sandbox",
        sandbox,
        "--cd",
        str(cwd),
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
        "--json",
        "-",
    ]
    started = time.monotonic()
    last_event = started
    diagnostics: list[str] = []
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_agent_environment(),
        start_new_session=True,
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(prompt)
    process.stdin.close()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while process.poll() is None:
            now = time.monotonic()
            if now - started > wall_timeout:
                raise AgentError(
                    f"{role} exceeded its {wall_timeout}s wall-clock timeout; "
                    f"bounded JSONL tail: {' | '.join(diagnostics[-5:])}"
                )
            if now - last_event > silence_timeout:
                raise AgentError(
                    f"{role} produced no JSONL event for {silence_timeout}s; "
                    f"bounded JSONL tail: {' | '.join(diagnostics[-5:])}"
                )
            for key, _ in selector.select(timeout=1):
                line = key.fileobj.readline()
                if not line:
                    continue
                last_event = time.monotonic()
                diagnostics.append(line.rstrip()[:4000])
                if len(diagnostics) > 200:
                    diagnostics = diagnostics[-200:]
        for line in process.stdout:
            diagnostics.append(line.rstrip()[:4000])
            if len(diagnostics) > 200:
                diagnostics = diagnostics[-200:]
    except BaseException:
        _terminate(process)
        raise
    finally:
        selector.close()
    if process.returncode != 0:
        raise AgentError(f"{role} exited {process.returncode}: {' | '.join(diagnostics[-5:])}")
    try:
        if output_path.stat().st_size > MAX_AGENT_OUTPUT_BYTES:
            raise AgentError(f"{role} final output exceeds {MAX_AGENT_OUTPUT_BYTES} bytes")
        raw = output_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentError(f"{role} did not produce its final output: {exc}") from exc
    return AgentResult(raw, tuple(diagnostics))


def invoke_with_one_repair(
    *,
    role: str,
    cwd: Path,
    context_path: Path,
    output_path: Path,
    parser: Callable[[str], T],
    wall_timeout: int,
    silence_timeout: int,
    initial_instruction: str = "",
) -> T:
    first = invoke(
        role=role,
        cwd=cwd,
        context_path=context_path,
        output_path=output_path,
        wall_timeout=wall_timeout,
        silence_timeout=silence_timeout,
        extra_instruction=initial_instruction,
    )
    try:
        return parser(first.raw)
    except ContractError as error:
        repair = (
            f"Your previous final output was rejected: {error}. Correct only the protocol error. "
            f"Previous output (bounded): {first.raw[:8192]}"
        )
        output_path.unlink(missing_ok=True)
        second = invoke(
            role=role,
            cwd=cwd,
            context_path=context_path,
            output_path=output_path,
            wall_timeout=wall_timeout,
            silence_timeout=silence_timeout,
            extra_instruction="\n\n".join(part for part in (initial_instruction, repair) if part),
        )
        try:
            return parser(second.raw)
        except ContractError as second_error:
            raise AgentError(f"{role} repair output was rejected: {second_error}") from second_error


def environment_fingerprint() -> dict[str, str]:
    def version(argv: list[str]) -> str:
        process = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if process.returncode != 0:
            raise AgentError(f"cannot fingerprint {' '.join(argv)}")
        return process.stdout.strip().splitlines()[0][:200]

    return {
        "platform": os.uname().sysname,
        "architecture": os.uname().machine,
        "codex": version(["codex", "--version"]),
        "python": version(["python3", "--version"]),
        "gh": version(["gh", "--version"]),
    }
