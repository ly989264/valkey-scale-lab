from __future__ import annotations

import contextvars
import hashlib
import json
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from valkey_scale_lab import __version__

COMMAND_LOG_ARTIFACT_TYPE = "runtime_command_log_entry"
COMMAND_AUDIT_SUMMARY_ARTIFACT_TYPE = "command_audit_summary"
COMMAND_STATUSES = {"PASS", "FAIL", "TIMEOUT", "RETRY", "SKIPPED_WITH_REASON", "MISSING"}

_CURRENT_RECORDER: contextvars.ContextVar["CommandRecorder | None"] = contextvars.ContextVar("vslab_command_recorder", default=None)


def current_command_recorder() -> "CommandRecorder | None":
    return _CURRENT_RECORDER.get()


@contextmanager
def command_recorder_context(recorder: "CommandRecorder | None") -> Iterator[None]:
    token = _CURRENT_RECORDER.set(recorder)
    try:
        yield
    finally:
        _CURRENT_RECORDER.reset(token)


def classify_command_kind(argv: list[str]) -> str:
    upper = [item.upper() for item in argv]
    joined = " ".join(upper)
    if "CLUSTER MEET" in joined:
        return "cluster_meet"
    if "CLUSTER ADDSLOTS" in joined:
        return "cluster_addslots"
    if "CLUSTER REPLICATE" in joined:
        return "cluster_replicate"
    if "CLUSTER INFO" in joined or "CLUSTER NODES" in joined or " PING" in joined or upper[-1:] == ["PING"]:
        return "cluster_probe"
    if "CLUSTER SETSLOT" in joined:
        return "cluster_setslot"
    if "MIGRATE" in upper:
        return "cluster_migrate"
    if "CLUSTER FAILOVER" in joined:
        return "cluster_failover"
    if "CLUSTER FORGET" in joined:
        return "cluster_forget"
    if "CLUSTER RESET" in joined:
        return "cluster_reset"
    if any(word in upper for word in ["STOP", "RM", "KILL"]):
        return "cleanup"
    if any(word in upper for word in ["START", "RESTART"]):
        return "fault_clear"
    if upper[:2] == ["DOCKER", "NETWORK"]:
        return "cleanup"
    return "runtime_command"


def node_identity(node: dict[str, Any] | None) -> dict[str, Any]:
    node = node or {}
    return {
        "host_id": str(node.get("host") or node.get("nodehost_id") or "local"),
        "node_logical_id": str(node.get("logical_id") or "MISSING"),
        "nodehost_id": str(node.get("nodehost_id") or "MISSING"),
        "container_name": str(node.get("container_name") or node.get("nodehost_container_name") or "MISSING"),
        "client_port": int(node["client_port"]) if str(node.get("client_port", "")).isdigit() else {"status": "MISSING", "reason": "Command is not bound to a Valkey client port."},
    }


class CommandRecorder:
    def __init__(
        self,
        *,
        capability_id: str,
        run_id: str,
        scenario: str,
        artifacts_dir: str | Path,
        log_dir: str | Path | None = None,
        append: bool = False,
    ) -> None:
        self.capability_id = capability_id
        self.run_id = run_id
        self.scenario = scenario
        self.artifacts_dir = Path(artifacts_dir)
        self.command_log_path = self.artifacts_dir / "command_log.jsonl"
        self.summary_path = self.artifacts_dir / "command_audit_summary.json"
        self.log_dir = Path(log_dir) if log_dir else self.artifacts_dir.parent / "logs" / "commands"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._rows: list[dict[str, Any]] = []
        self._next_sequence = 1
        if append and self.command_log_path.exists():
            for line in self.command_log_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if isinstance(row, dict):
                    self._rows.append(row)
                    self._next_sequence = max(self._next_sequence, int(row.get("sequence", 0)) + 1)

    def record_subprocess(
        self,
        *,
        operation_id: str,
        step_id: str,
        command_kind: str,
        argv: list[str],
        timeout_ms: int,
        node: dict[str, Any] | None = None,
        retry_index: int = 0,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        started = time.time()
        started_monotonic_ms = time.monotonic() * 1000.0
        try:
            proc = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=max(timeout_ms / 1000.0, 0.001))
        except subprocess.TimeoutExpired as exc:
            ended = time.time()
            ended_monotonic_ms = time.monotonic() * 1000.0
            self.record_result(
                operation_id=operation_id,
                step_id=step_id,
                command_kind=command_kind,
                argv=argv,
                started_at_unix_ms=int(started * 1000),
                ended_at_unix_ms=int(ended * 1000),
                exit_code={"status": "MISSING", "reason": "subprocess timed out before exit code was available"},
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                timeout_ms=timeout_ms,
                status="TIMEOUT",
                error_type="timeout",
                node=node,
                retry_index=retry_index,
                started_at_monotonic_ms=started_monotonic_ms,
                ended_at_monotonic_ms=ended_monotonic_ms,
            )
            raise
        status = "PASS" if proc.returncode == 0 else ("RETRY" if retry_index > 0 else "FAIL")
        ended = time.time()
        ended_monotonic_ms = time.monotonic() * 1000.0
        self.record_result(
            operation_id=operation_id,
            step_id=step_id,
            command_kind=command_kind,
            argv=argv,
            started_at_unix_ms=int(started * 1000),
            ended_at_unix_ms=int(ended * 1000),
            exit_code=int(proc.returncode),
            stdout=proc.stdout,
            stderr=proc.stderr,
            timeout_ms=timeout_ms,
            status=status,
            error_type="" if proc.returncode == 0 else "nonzero_exit",
            node=node,
            retry_index=retry_index,
            started_at_monotonic_ms=started_monotonic_ms,
            ended_at_monotonic_ms=ended_monotonic_ms,
        )
        if check and proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, argv, output=proc.stdout, stderr=proc.stderr)
        return proc

    def record_result(
        self,
        *,
        operation_id: str,
        step_id: str,
        command_kind: str,
        argv: list[str],
        started_at_unix_ms: int,
        ended_at_unix_ms: int,
        exit_code: int | dict[str, Any],
        stdout: str,
        stderr: str,
        timeout_ms: int,
        status: str,
        error_type: str,
        node: dict[str, Any] | None = None,
        retry_index: int = 0,
        trace_refs: list[str] | None = None,
        started_at_monotonic_ms: float | None = None,
        ended_at_monotonic_ms: float | None = None,
    ) -> dict[str, Any]:
        if status not in COMMAND_STATUSES:
            raise ValueError(f"unsupported command status {status}")
        with self._lock:
            sequence = self._next_sequence
            self._next_sequence += 1
            command_id = f"cmd-{sequence:06d}"
        stdout_path, stdout_sha = self._write_stream(command_id, "stdout", stdout)
        stderr_path, stderr_sha = self._write_stream(command_id, "stderr", stderr)
        identity = node_identity(node)
        monotonic_start, monotonic_end, monotonic_duration = _monotonic_timing(
            started_at_monotonic_ms,
            ended_at_monotonic_ms,
        )
        row = {
            "schema_version": "v1",
            "artifact_type": COMMAND_LOG_ARTIFACT_TYPE,
            "capability_id": self.capability_id,
            "run_id": self.run_id,
            "scenario": self.scenario,
            "sequence": sequence,
            "operation_id": operation_id,
            "step_id": step_id,
            "command_id": command_id,
            "command_kind": command_kind,
            "command_scope": "owned_docker_or_local_valkey_client",
            "argv": [str(item) for item in argv],
            "started_at_unix_ms": started_at_unix_ms,
            "ended_at_unix_ms": ended_at_unix_ms,
            "duration_ms": max(0, ended_at_unix_ms - started_at_unix_ms),
            "started_at_monotonic_ms": monotonic_start,
            "ended_at_monotonic_ms": monotonic_end,
            "monotonic_duration_ms": monotonic_duration,
            "exit_code": exit_code,
            "stdout_path": stdout_path,
            "stdout_sha256": stdout_sha,
            "stderr_path": stderr_path,
            "stderr_sha256": stderr_sha,
            "retry_index": retry_index,
            "attempt_count": retry_index + 1,
            "timeout_ms": timeout_ms,
            "status": status,
            "error_type": error_type,
            "redaction": {"status": "PASS", "policy": "argv contains only local container names, ports, and Valkey commands"},
            "host_network_mutated": False,
            "global_firewall_mutated": False,
            "trace_refs": trace_refs or [],
            "producer": {"name": "valkey-scale-lab", "version": __version__},
            **identity,
        }
        with self._lock:
            self._rows.append(row)
            self._append_locked(row)
        return row

    def record_skipped(
        self,
        *,
        operation_id: str,
        step_id: str,
        command_kind: str,
        reason: str,
        node: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = int(time.time() * 1000)
        now_monotonic_ms = time.monotonic() * 1000.0
        return self.record_result(
            operation_id=operation_id,
            step_id=step_id,
            command_kind=command_kind,
            argv=["SKIPPED_WITH_REASON", reason],
            started_at_unix_ms=now,
            ended_at_unix_ms=now,
            exit_code={"status": "SKIPPED_WITH_REASON", "reason": reason},
            stdout="",
            stderr="",
            timeout_ms=0,
            status="SKIPPED_WITH_REASON",
            error_type="",
            node=node,
            started_at_monotonic_ms=now_monotonic_ms,
            ended_at_monotonic_ms=now_monotonic_ms,
        )

    def close(self, *, status: str | None = None) -> dict[str, Any]:
        with self._lock:
            rows = sorted(self._rows, key=lambda row: int(row.get("sequence", 0)))
            if rows:
                self._flush_locked()
            elif self.command_log_path.exists() and self.command_log_path.stat().st_size == 0:
                self.command_log_path.unlink()
        summary = build_command_audit_summary(
            capability_id=self.capability_id,
            run_id=self.run_id,
            scenario=self.scenario,
            command_log_path=self.command_log_path,
            rows=rows,
            status=status,
        )
        self.summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return summary

    def _write_stream(self, command_id: str, stream: str, value: str) -> tuple[str, str]:
        text = value or ""
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        path = self.log_dir / f"{command_id}.{stream}.log"
        path.write_text(text, encoding="utf-8")
        return _rel(path), digest

    def _append_locked(self, row: dict[str, Any]) -> None:
        """One row, one append - the cost of recording a command must not depend
        on how many were recorded before it.

        This used to rewrite the whole log on every row, which made the recorder
        quadratic. Measured 2026-08-10: 1.96 ms/row at 250 rows, 10.15 at 1000,
        47.39 at 4000, growing linearly with the rows already written. A real
        exact-200 records 12,086, and because the rewrite happens inside
        `self._lock` every recording thread queues behind it - the run failed in
        `_process_node_snapshots_parallel`, which has to get 200 nodes x 2
        commands through a 60s bound and reached about 160 of them.

        `close` still writes the file sorted by sequence from `_rows`, so the
        artifact this leaves behind is unchanged; only the during-the-run
        ordering is arrival order, and nothing reads it before `close`.
        """

        with self.command_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    def _flush_locked(self) -> None:
        rows = sorted(self._rows, key=lambda row: int(row.get("sequence", 0)))
        self.command_log_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def build_command_audit_summary(
    *,
    capability_id: str,
    run_id: str,
    scenario: str,
    command_log_path: str | Path,
    rows: list[dict[str, Any]],
    status: str | None = None,
) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    for row in rows:
        by_kind[str(row.get("command_kind", "MISSING"))] = by_kind.get(str(row.get("command_kind", "MISSING")), 0) + 1
    failures = [row for row in rows if row.get("status") == "FAIL"]
    timeouts = [row for row in rows if row.get("status") == "TIMEOUT"]
    retries = [row for row in rows if row.get("retry_index", 0) or row.get("status") == "RETRY"]
    operations: dict[str, list[str]] = {}
    for row in rows:
        operations.setdefault(str(row.get("operation_id", "MISSING")), []).append(str(row.get("command_id", "MISSING")))
    slowest = sorted(rows, key=lambda row: float(row.get("duration_ms", 0) or 0), reverse=True)[:10]
    summary_status = status or ("PASS" if rows and not failures and not timeouts else ("FAIL" if failures or timeouts else "MISSING"))
    return {
        "schema_version": "v1",
        "artifact_type": COMMAND_AUDIT_SUMMARY_ARTIFACT_TYPE,
        "capability_id": capability_id,
        "run_id": run_id,
        "scenario": scenario,
        "status": summary_status,
        "command_log_ref": _rel(Path(command_log_path)),
        "total_commands": len(rows),
        "pass_count": sum(1 for row in rows if row.get("status") == "PASS"),
        "failure_count": len(failures),
        "timeout_count": len(timeouts),
        "retry_count": len(retries),
        "by_command_kind": by_kind,
        "slowest_commands_topN": [_summary_row(row) for row in slowest],
        "failed_commands": [_summary_row(row) for row in failures],
        "timeout_commands": [_summary_row(row) for row in timeouts],
        "retry_commands": [_summary_row(row) for row in retries],
        "operation_traceability": [
            {"operation_id": operation_id, "command_log_refs": [f"command_log.jsonl#{command_id}" for command_id in command_ids], "status": "PASS"}
            for operation_id, command_ids in sorted(operations.items())
        ],
        "coverage": {
            "required_command_kinds": ["cluster_meet", "cluster_addslots", "cluster_replicate", "cluster_probe", "cleanup"],
            "observed_command_kinds": sorted(by_kind),
        },
        "missing_or_skipped": []
        if rows
        else [
            {
                "metric": "command_log.total_commands",
                "status": "MISSING",
                "reason": "No command rows were recorded.",
                "impact": "PASS operations cannot be audited.",
            }
        ],
    }


def _summary_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "command_id": row.get("command_id", "MISSING"),
        "operation_id": row.get("operation_id", "MISSING"),
        "step_id": row.get("step_id", "MISSING"),
        "command_kind": row.get("command_kind", "MISSING"),
        "duration_ms": row.get("duration_ms", "MISSING"),
        "status": row.get("status", "MISSING"),
        "exit_code": row.get("exit_code", "MISSING"),
        "retry_index": row.get("retry_index", 0),
        "error_type": row.get("error_type", ""),
    }


def _monotonic_timing(
    started_at_monotonic_ms: float | None,
    ended_at_monotonic_ms: float | None,
) -> tuple[float | dict[str, str], float | dict[str, str], float | dict[str, str]]:
    missing = {
        "status": "MISSING",
        "reason": "caller did not provide monotonic command bounds",
    }
    if started_at_monotonic_ms is None or ended_at_monotonic_ms is None:
        return dict(missing), dict(missing), dict(missing)
    started = float(started_at_monotonic_ms)
    ended = float(ended_at_monotonic_ms)
    if ended < started:
        raise ValueError("ended_at_monotonic_ms must not precede started_at_monotonic_ms")
    rounded_started = round(started, 3)
    rounded_ended = round(ended, 3)
    return rounded_started, rounded_ended, round(rounded_ended - rounded_started, 3)


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
